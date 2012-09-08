
============================================
Want to Securely Store and Share Your Files?
============================================

Welcome to `the Tahoe-LAFS project`_, a secure, decentralized, fault-tolerant
storage system.

`What Makes Tahoe-LAFS Different`_

This page will get the software installed, and `the next page`_ will show you
how to use it.

.. _the Tahoe-LAFS project: https://tahoe-lafs.org
.. _What Makes Tahoe-LAFS Different: about.rst
.. _the next page: running.rst

How To Get Tahoe-LAFS
---------------------

See if Tahoe-LAFS is already `packaged for your system`_.

Or, run it from source. This doesn't require installing it into your system
and it doesn't require root privileges.

This procedure has been verified to work on Windows, Mac, OpenSolaris, and
too many flavors of Linux and of BSD to list.

.. _packaged for your system: https://tahoe-lafs.org/trac/tahoe-lafs/wiki/OSPackages

In Case Of Trouble
------------------

There are a few 3rd-party libraries that Tahoe-LAFS depends on that might
fail to build on your platform. If the following instructions don't work,
then please write to `the tahoe-dev mailing list`_ where friendly developers
will help you out. If you get a compile error, please read `this page`_

.. _the tahoe-dev mailing list: https://tahoe-lafs.org/cgi-bin/mailman/listinfo/tahoe-dev
.. _this page: https://tahoe-lafs.org/trac/tahoe-lafs/wiki/CompileError

Install Python
--------------

Check if you already have an adequate version of Python installed by running
``python -V``. Python v2.4 (v2.4.4 or greater), Python v2.5, Python v2.6, or
Python v2.7 will work. Python v3 does not work. On Windows, we recommend the
use of native Python, not Cygwin. If you don't have one of these versions of
Python installed, download and install `Python v2.7`_. Make sure that the
path to the installation directory has no spaces in it (e.g. on Windows, do
not install Python in the "Program Files" directory).

.. _Python v2.7: http://www.python.org/download/releases/2.7.2/

Get Tahoe-LAFS
--------------

Download the latest stable release, `Tahoe-LAFS v1.9.2`_.

.. _Tahoe-LAFS v1.9.2: https://tahoe-lafs.org/source/tahoe-lafs/releases/allmydata-tahoe-1.9.2.zip

Set Up Tahoe-LAFS
-----------------

Unpack the zip file and cd into the top-level directory.

Run ``python setup.py build`` to generate the ``tahoe`` executable in a
subdirectory of the current directory named ``bin``. This will download and
build anything you need from various websites.

On Windows, the ``build`` step might tell you to open a new Command Prompt
(or, on XP and earlier, to log out and back in again). This is needed the
first time you set up Tahoe-LAFS on a particular installation of Windows.

Optionally run ``python setup.py test`` to verify that it passes all of its
self-tests.

Run ``bin/tahoe --version`` (on Windows, ``bin\tahoe --version``) to verify
that the executable tool prints out the right version number after
"``allmydata-tahoe:``".

Run Tahoe-LAFS
--------------

Now you are ready to deploy a decentralized filesystem. The ``tahoe``
executable in the ``bin`` directory can configure and launch your Tahoe-LAFS
nodes. See `the next page`_ for instructions on how to do that.
