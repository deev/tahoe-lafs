
=====================
Lease database design
=====================

The target audience for this document is developers who wish to understand
the new lease database (leasedb) to be added in Tahoe-LAFS v1.11.0.


Motivation
----------

Before Tahoe-LAFS v1.11.0, leases were stored in share files. This has
several disadvantages:

- Updating a lease required modifying a share file (even for immutable
  shares). This significantly complicated the implementation of share
  classes and led to a security bug (ticket `#1528`_).

- The lease renewal and cancel functionality using individual secrets
  was complex and not fully used.

- When only the disk backend was supported, it was possible to read and
  update leases synchronously because the share files were stored locally
  to the storage server. For the cloud backend, accessing share files
  requires an HTTP request, and so must be asynchronous. Accepting this
  asynchrony for lease queries would be both inefficient and complex.
  Moving lease information out of shares and into a local database allows
  lease queries to stay synchronous.

The leasedb also provides a place to store summarized information, such as
total space usage of shares leased by an account, for accounting purposes.

.. _`#1528`: https://tahoe-lafs.org/trac/tahoe-lafs/ticket/1528


Design constraints
------------------

A backend share is represented as a collection of backend objects. The
backend storage may be remote from the storage server (for example, a cloud
storage service). Writing to the backend objects is in general not an atomic
operation. So the leasedb also keeps track of which shares are in an
inconsistent state because they have been partly written.

Leases are no longer stored in shares. The same share format is used as
before, but the lease slots are ignored, and are cleared when rewriting a
mutable share. The new design also does not use lease renewal or cancel
secrets. (They are accepted as parameters in the storage interface for
backward compatibility, but are ignored. Cancel secrets were already ignored
due to the fix for `#1528`_.)

The new design needs to be fail-safe in the sense that if the lease database
is lost or corruption is detected, no share data will be lost (even though
the metadata about leases held by particular accounts has been lost).


Accounting crawler
------------------

The accounting crawler replaces the current lease crawler. It performs the
following functions:

- delete backend objects for unleased shares -- that is, shares that have
  stable entries in the leasedb but no unexpired leases.

- discover shares that have been manually added to backend storage, via
  ``scp`` or some other out-of-band means.

- discover shares that are present when a storage server is upgraded to
  version v1.11.0 or later from a previous version, and give them
  "starter leases".

- recover from a situation where the leasedb is lost or detectably
  corrupted. This is handled in the same way as upgrading from a previous
  version.

- detect shares that have unexpectedly disappeared from backend storage.
  The disappearance of a share is logged, and its entry and leases are
  removed from the leasedb.


Accounts
--------

An account holds leases for some subset of shares stored by a server.
For the time being we only support two accounts: an anonymous account
and a starter account. The starter account is used for leases on shares
discovered by the accounting crawler; the anonymous account is used for
all other leases.

The leasedb has at most one lease entry per account per
(storage_index, shnum) pair. This entry stores the times when the lease
was last renewed and when it is set to expire (if the expiration policy
does not force it to expire earlier), represented as Unix
UTC-seconds-since-epoch timestamps.

For more on expiration policy, see
`docs/garbage-collection.rst <../garbage-collection.rst>`__.


Share states
------------

The diagram and descriptions below give the possible states, and transitions
between states, for any (storage_index, shnum) pair on each server::


       STATE_STABLE -------.
        ^   |    |         |
        |   v    |         v
   STATE_COMING  |    STATE_GOING
        ^        |         |
        |        v         |
        '----- NONE <------'


NONE:
    There is no entry in the ``shares`` table for this
    (storage_index, shnum) in this server's leasedb. This is the
    initial state.

    Transitions into this state:

    - STATE_GOING → NONE: all backend objects for the share have just been
      deleted.
    - STATE_STABLE → NONE: the AccountingCrawler just noticed that all the
      backend objects for this share disappeared unexpectedly.

STATE_COMING:
    The backend objects are being written to, but are not confirmed to all
    have been written.

    Transitions into this state:

    - NONE → STATE_COMING: a new share is being created.
    - STATE_STABLE → STATE_COMING: a mutable share is being modified.

STATE_STABLE:
    The backend objects have been written and are not in the process of being
    modified or deleted by the storage server. (It could have been modified
    or deleted behind the back of the storage server, but if it has, the
    server has not noticed that yet.) The share may or may not be leased.

    Transitions into this state:

    - STATE_COMING → STATE_STABLE: all backend objects have just been written.

STATE_GOING:
    The backend objects are being deleted.

    Transitions into this state:

    - STATE_STABLE → STATE_GOING: the share should be deleted because it is
      unleased.

The following constraints are needed to avoid race conditions:

- While a share is being deleted (entry in STATE_GOING), we do not accept
  any requests to recreate it. That would result in add and delete requests
  for backend objects being sent concurrently, with undefined results.

- While a share is being added or modified (entry in STATE_COMING), we treat
  it as leased.

- Creation or modification requests for a given mutable share are serialized.


Unresolved design issues
------------------------

- What happens if a write to backend storage for a new share fails permanently?
  If we delete the share entry, any backend objects that were written for that
  share will be deleted by the AccountingCrawler when it next gets to them.
  Is this sufficient, or should we attempt to delete those objects
  immediately? If the latter, do we need a direct STATE_COMING → STATE_GOING
  transition to handle this case?

- What happens if only some backend objects for a share disappear unexpectedly?
  This case is similar to only some objects having been written when we get
  an unrecoverable error during creation of a share, but perhaps we want to
  treat it differently in order to preserve information about the backend
  having lost data.

- Does the leasedb need to track corrupted shares?


Future directions
-----------------

Clients will have key pairs identifying accounts, and will be able to add
leases for a specific account. Various space usage policies can be defined.

Better migration tools ('tahoe storage export'?) will create export files
that include both the share data and the lease data, and then an import tool
will both put the share in the right place and update the recipient node's
leasedb.
