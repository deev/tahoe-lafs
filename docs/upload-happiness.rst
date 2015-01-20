.. -*- coding: utf-8-with-signature -*-

=======================================
Happiness In Upload, the simple version
=======================================

*This is the introductory, end-user-oriented, documentation for the “Servers of Happiness” configuration parameter. For the more detailed specification of the algorithm, see* `specifications/servers-of-happiness.rst`_ *.*

.. _specifications/servers-of-happiness.rst: specifications/servers-of-happiness.rst

Tahoe-LAFS uses *erasure coding*, a redundancy-adding algorithm (like
RAID), which enables the downloader to recover the complete contents
of a file from a subset of the servers. The uploader can choose two
parameters: `shares.total` (*N*) and `shares.needed` (*K*). *N* is the
total number of shares that the uploader creates and writes to
servers, and *K* is the number of shares that the downloader requires
in order to be able to read the file.

The default configuration, and the most widely used configuration
among Tahoe-LAFS users, is to set *N* to 10 and *K* to 3.

Now there is another decision that the uploader needs to make when
uploading: what should it do if there are fewer than *N* servers
available? One option is: if there are fewer than *N* servers
available, abort the upload and report that the upload failed due to
insufficient servers.

Another option is: as long as there are *K* or more servers available,
go ahead and complete the upload. This is somewhat risky, because if,
for example there are only 3 servers available and the uploader
uploads one share to each server (when *K* is 3), then the subsequent
failure of any one server would render the file unrecoverable.

Another option is to pick a number between *K* and *N* to be “How many
servers do I need this file to be spread out over?”. For example, if
*K* is 3 and *N* is 10, you might say “If the file can get spread out
over 7 different servers, continue, but if there are fewer than 7
usable servers, then abort.”.

This question is the reason why there is a third configuration
parameter, next to `shares.needed` and `shares.total`. The third
parameter is called `shares.happy` and it basically means “How many
servers do I require the file to get spread out over, or else I'll
abort the upload?”.

Now the *precise* meaning of `shares.happy` is more complicated than
that, because the algorithm has to handle some weird edge cases, like
what if the uploader goes to upload a file, and it finds out that one
of the servers already has *many* different shares from that file one
it!? Or what if it finds out that there are many different servers,
and they each have a copy of the same share, and they are all in
read-only mode (meaning that their disks are full, or that for some
other reason they are refusing to accept new shares, but they are
continuing to serve up old shares)?

These kinds of weird edge case do actually crop up in practice, and it
is important that the upload algorithm handles them well. The upload
algorithm that we've implemented was invented by Daira Hopwood and
Kevan Carstensen, and was the topic of Kevan's thesis for his Master's
degree in computer science, `“Robust Resource Allocation in
Distributed Filesystems”`_.

.. _“Robust Resource Allocation in Distributed Filesystems”: https://tahoe-lafs.org/~davidsarah/Carstensen-2011-Robust_Resource_Allocation_In_Distributed_Filesystem.pdf

This upload algorithm is called “Servers Of Happiness”, and the way it
works, basically, is that if one server has multiple shares of a file,
then it counts only one of those shares, and if one share is present
on multiple servers, then it counts only one of those servers.

The end result is that regardless of whatever weird distribution of
shares was in place when the uploader started, it will proceed as long
as there is a way to nicely distribute the shares over at least
`shares.happy` servers. If there is no way to distribute the shares
over at least that many servers, then will abort the upload.

See `specifications/servers-of-happiness.rst`_ for details.
