# -*- coding: utf-8 -*-

import os, sys

import sqlite3
from sqlite3 import IntegrityError
[IntegrityError]


class DBError(Exception):
    pass


def get_db(dbfile, stderr=sys.stderr,
           create_version=(None, None), updaters={}, just_create=False):
    """Open or create the given db file. The parent directory must exist.
    create_version=(SCHEMA, VERNUM), and SCHEMA must have a 'version' table.
    Updaters is a {newver: commands} mapping, where e.g. updaters[2] is used
    to get from ver=1 to ver=2. Returns a (sqlite3,db) tuple, or raises
    DBError.
    """
    must_create = not os.path.exists(dbfile)
    try:
        db = sqlite3.connect(dbfile)
    except (EnvironmentError, sqlite3.OperationalError), e:
        raise DBError("Unable to create/open db file %s: %s" % (dbfile, e))

    schema, target_version = create_version
    c = db.cursor()

    # Enabling foreign keys allows stricter integrity checking.
    # The default is unspecified according to <http://www.sqlite.org/foreignkeys.html#fk_enable>.
    c.execute("PRAGMA foreign_keys = ON;")

    # For the next two PRAGMA settings, see
    # https://tahoe-lafs.org/pipermail/tahoe-dev/2012-December/007877.html
    # for discussion. Without these two settings, leasedb can handle about
    # 3.2 lease renewals per second on Zooko's Macbook Pro 5,3 with Linux,
    # ext4, and a spinning disk. With these two settings, leasedb can handle
    # about 250 lease renewals per second. These settings do not add any risk
    # of corruption or non-atomic update. They do add a risk of
    # non-durability, in which the db can rollback to an earlier (correct)
    # version due to a kernel panic or power failure. Such a rollback is not
    # a critical problem for the ways we currently use sqlite (leasedb and
    # backupdb).

    # Write-Ahead-Log — http://www.sqlite.org/wal.html — is more efficient
    # for our uses than the traditional rollback journal. It requires sqlite
    # >= v3.7.0 (released 2010-07-22). If the current sqlite is too old and
    # doesn't support Write-Ahead-Log, this PRAGMA will be ignored and do no
    # harm.
    c.execute("PRAGMA journal_mode = WAL;")
    c.execute("PRAGMA synchronous = NORMAL;")

    if must_create:
        c.executescript(schema)
        c.execute("INSERT INTO version (version) VALUES (?)", (target_version,))
        db.commit()

    try:
        c.execute("SELECT version FROM version")
        version = c.fetchone()[0]
    except sqlite3.DatabaseError, e:
        # this indicates that the file is not a compatible database format.
        # Perhaps it was created with an old version, or it might be junk.
        raise DBError("db file is unusable: %s" % e)

    if just_create: # for tests
        return (sqlite3, db)

    while version < target_version:
        c.executescript(updaters[version+1])
        db.commit()
        version = version+1
    if version != target_version:
        raise DBError("Unable to handle db version %s" % version)

    return (sqlite3, db)


