
from collections import deque

from twisted.internet import defer, reactor, task
from twisted.python.failure import Failure

from zope.interface import Interface, implements
from allmydata.interfaces import IShareBase

from allmydata.util import log
from allmydata.util.assertutil import precondition, _assert
from allmydata.util.deferredutil import eventually_callback, eventually_errback, eventual_chain, gatherResults
from allmydata.storage.common import si_b2a, NUM_RE


# The container has keys of the form shares/$PREFIX/$STORAGEINDEX/$SHNUM.$CHUNK

def get_share_key(si, shnum=None):
    sistr = si_b2a(si)
    if shnum is None:
        return "shares/%s/%s/" % (sistr[:2], sistr)
    else:
        return "shares/%s/%s/%d" % (sistr[:2], sistr, shnum)

def get_chunk_key(share_key, chunknum):
    precondition(chunknum >= 0, chunknum=chunknum)
    if chunknum == 0:
        return share_key
    else:
        return "%s.%d" % (share_key, chunknum)


PREFERRED_CHUNK_SIZE = 512*1024
PIPELINE_DEPTH = 4

ZERO_CHUNKDATA = "\x00"*PREFERRED_CHUNK_SIZE

def get_zero_chunkdata(size):
    if size <= PREFERRED_CHUNK_SIZE:
        return ZERO_CHUNKDATA[: size]
    else:
        return "\x00"*size


class IContainer(Interface):
    """
    I represent a cloud container.
    """
    def create():
        """
        Create this container.
        """

    def delete():
        """
        Delete this container.
        The cloud service may require the container to be empty before it can be deleted.
        """

    def list_objects(prefix=''):
        """
        Get a ContainerListing that lists objects in this container.

        prefix: (str) limit the returned keys to those starting with prefix.
        """

    def put_object(object_name, data, content_type=None, metadata={}):
        """
        Put an object in this bucket.
        Any existing object of the same name will be replaced.
        """

    def get_object(object_name):
        """
        Get an object from this container.
        """

    def head_object(object_name):
        """
        Retrieve object metadata only.
        """

    def delete_object(object_name):
        """
        Delete an object from this container.
        Once deleted, there is no method to restore or undelete an object.
        """


def delete_chunks(container, share_key, from_chunknum=0):
    d = container.list_objects(prefix=share_key)
    def _delete(res):
        def _suppress_404(f):
            e = f.trap(container.ServiceError)
            if e.get_error_code() != 404:
                return f

        d2 = defer.succeed(None)
        for item in res.contents:
            key = item.key
            _assert(key.startswith(share_key), key=key, share_key=share_key)
            path = key.split('/')
            if len(path) == 4:
                (_, _, chunknumstr) = path[3].partition('.')
                chunknumstr = chunknumstr or "0"
                if NUM_RE.match(chunknumstr) and int(chunknumstr) >= from_chunknum:
                    d2.addCallback(lambda ign, key=key: container.delete_object(key))
                    d2.addErrback(_suppress_404)
        return d2
    d.addCallback(_delete)
    return d


class CloudShareBase(object):
    implements(IShareBase)
    """
    Attributes:
      _container:     (IContainer) the cloud container that stores this share
      _storage_index: (str) binary storage index
      _shnum:         (integer) share number
      _key:           (str) the key prefix under which this share will be stored (no .chunknum suffix)
      _data_length:   (integer) length of data excluding headers and leases
      _total_size:    (integer) total size of the sharefile

    Methods:
      _discard(self): object will no longer be used; discard references to potentially large data
    """
    def __init__(self, container, storage_index, shnum):
        precondition(IContainer.providedBy(container), container=container)
        precondition(isinstance(storage_index, str), storage_index=storage_index)
        precondition(isinstance(shnum, int), shnum=shnum)

        # These are always known immediately.
        self._container = container
        self._storage_index = storage_index
        self._shnum = shnum
        self._key = get_share_key(storage_index, shnum)

        # Subclasses must set _data_length and _total_size.

    def __repr__(self):
        return ("<%s at %r key %r>" % (self.__class__.__name__, self._container, self._key,))

    def get_storage_index(self):
        return self._storage_index

    def get_storage_index_string(self):
        return si_b2a(self._storage_index)

    def get_shnum(self):
        return self._shnum

    def get_data_length(self):
        return self._data_length

    def get_size(self):
        return self._total_size

    def get_used_space(self):
        # We're not charged for any per-object overheads in supported cloud services, so
        # total object data sizes are what we're interested in for statistics and accounting.
        return self.get_size()

    def unlink(self):
        self._discard()
        return delete_chunks(self._container, self._key)

    def _get_path(self):
        """
        When used with the mock cloud container, this returns the path of the file containing
        the first chunk. For a real cloud container, it raises an error.
        """
        # It is OK that _get_path doesn't exist on real cloud container objects.
        return self._container._get_path(self._key)


class CloudShareReaderMixin:
    """
    Attributes:
      _data_length: (integer) length of data excluding headers and leases
      _chunksize:   (integer) size of each chunk possibly excluding the last
      _cache:       (ChunkCache) the cache used to read chunks

      DATA_OFFSET:  (integer) offset to the start-of-data from start of the sharefile
    """
    def readv(self, readv):
        sorted_readv = sorted(zip(readv, xrange(len(readv))))
        datav = [None]*len(readv)
        for (v, i) in sorted_readv:
            (offset, length) = v
            datav[i] = self.read_share_data(offset, length)
        return gatherResults(datav)

    def read_share_data(self, offset, length):
        precondition(offset >= 0)

        # Reads beyond the end of the data are truncated.
        # Reads that start beyond the end of the data return an empty string.
        seekpos = self.DATA_OFFSET + offset
        actuallength = max(0, min(length, self._data_length - offset))
        if actuallength == 0:
            return defer.succeed("")

        lastpos = seekpos + actuallength - 1
        _assert(lastpos > 0, seekpos=seekpos, actuallength=actuallength, lastpos=lastpos)
        start_chunknum = seekpos / self._chunksize
        start_offset   = seekpos % self._chunksize
        last_chunknum  = lastpos / self._chunksize
        last_offset    = lastpos % self._chunksize
        _assert(start_chunknum <= last_chunknum, start_chunknum=start_chunknum, last_chunknum=last_chunknum)

        parts = deque()

        def _load_part(ign, chunknum):
            # determine which part of this chunk we need
            start = 0
            end = self._chunksize
            if chunknum == start_chunknum:
                start = start_offset
            if chunknum == last_chunknum:
                end = last_offset + 1
            #print "LOAD", get_chunk_key(self._key, chunknum), start, end

            # d2 fires when we should continue loading the next chunk; chunkdata_d fires with the actual data.
            chunkdata_d = defer.Deferred()
            d2 = self._cache.get(chunknum, chunkdata_d)
            if start > 0 or end < self._chunksize:
                chunkdata_d.addCallback(lambda chunkdata: chunkdata[start : end])
            parts.append(chunkdata_d)
            return d2

        d = defer.succeed(None)
        for i in xrange(start_chunknum, last_chunknum + 1):
            d.addCallback(_load_part, i)
        d.addCallback(lambda ign: gatherResults(parts))
        d.addCallback(lambda pieces: ''.join(pieces))
        return d


class CloudError(Exception):
    pass


BACKOFF_SECONDS_FOR_5XX = (0, 2, 10)


class ContainerRetryMixin:
    """
    I provide a helper method for performing an operation on a cloud container that will retry up to
    len(BACKOFF_SECONDS_FOR_5XX) times (not including the initial try). If the initial try fails, a
    single incident will be triggered after the operation has succeeded or failed.
    """

    def _do_request(self, description, operation, *args, **kwargs):
        d = defer.maybeDeferred(operation, *args, **kwargs)
        def _retry(f):
            d2 = self._handle_error(f, 1, None, description, operation, *args, **kwargs)
            def _trigger_incident(res):
                log.msg(format="error(s) on cloud container operation: %(description)s %(arguments)s %(kwargs)s",
                        arguments=args[:2], kwargs=kwargs, description=description,
                        level=log.WEIRD)
                return res
            d2.addBoth(_trigger_incident)
            return d2
        d.addErrback(_retry)
        return d

    def _handle_error(self, f, trynum, first_err_and_tb, description, operation, *args, **kwargs):
        f.trap(self.ServiceError)

        # Don't use f.getTracebackObject() since a fake traceback will not do for the 3-arg form of 'raise'.
        # tb can be None (which is acceptable for 3-arg raise) if we don't have a traceback.
        tb = getattr(f, 'tb', None)
        fargs = f.value.args
        if len(fargs) > 2 and fargs[2] and '<code>signaturedoesnotmatch</code>' in fargs[2].lower():
            fargs = fargs[:2] + ("SignatureDoesNotMatch response redacted",) + fargs[3:]

        args_without_data = args[:2]
        msg = "try %d failed: %s %s %s" % (trynum, description, args_without_data, kwargs)
        err = CloudError(msg, *fargs)

        # This should not trigger an incident; we want to do that at the end.
        log.msg(format="try %(trynum)d failed: %(description)s %(arguments)s %(kwargs)s %(fargs)s",
                trynum=trynum, arguments=args_without_data, kwargs=kwargs, description=description, fargs=repr(fargs),
                level=log.INFREQUENT)

        if first_err_and_tb is None:
            first_err_and_tb = (err, tb)

        if trynum > len(BACKOFF_SECONDS_FOR_5XX):
            # If we run out of tries, raise the error we got on the first try (which *may* have
            # a more useful traceback).
            (first_err, first_tb) = first_err_and_tb
            raise first_err.__class__, first_err, first_tb

        fargs = f.value.args
        if len(fargs) > 0 and int(fargs[0]) >= 500 and int(fargs[0]) < 600:
            # Retry on 5xx errors.
            d = task.deferLater(reactor, BACKOFF_SECONDS_FOR_5XX[trynum-1], operation, *args, **kwargs)
            d.addErrback(self._handle_error, trynum+1, first_err_and_tb, description, operation, *args, **kwargs)
            return d

        # If we get an error response other than a 5xx, raise that error even if it was on a retry.
        raise err.__class__, err, tb


def concat(seqs):
    """
    O(n), rather than O(n^2), concatenation of list-like things, returning a list.
    I can't believe this isn't built in.
    """
    total_len = 0
    for seq in seqs:
        total_len += len(seq)
    result = [None]*total_len
    i = 0
    for seq in seqs:
        for x in seq:
            result[i] = x
            i += 1
    _assert(i == total_len, i=i, total_len=total_len)
    return result


class ContainerListMixin:
    """
    S3 has a limitation of 1000 object entries returned on each list (GET Bucket) request.
    I provide a helper method to repeat the call as many times as necessary to get a full
    listing. The container is assumed to implement:

    def list_some_objects(self, **kwargs):
        # kwargs may include 'prefix' and 'marker' parameters as documented at
        # <http://docs.amazonwebservices.com/AmazonS3/latest/API/RESTBucketGET.html>.
        # returns Deferred ContainerListing

    Note that list_some_objects is assumed to be reliable; so, if retries are needed,
    the container class should also inherit from ContainerRetryMixin and list_some_objects
    should make the request via _do_request.

    The 'delimiter' parameter of the GET Bucket API is not supported.
    """
    def list_objects(self, prefix=''):
        kwargs = {'prefix': prefix}
        all_contents = deque()
        def _list_some():
            d2 = self.list_some_objects(**kwargs)
            def _got_listing(res):
                all_contents.append(res.contents)
                if res.is_truncated == "true":
                    _assert(len(res.contents) > 0)
                    marker = res.contents[-1].key
                    _assert('marker' not in kwargs or marker > kwargs['marker'],
                            "Not making progress in list_objects", kwargs=kwargs, marker=marker)
                    kwargs['marker'] = marker
                    return _list_some()
                else:
                    _assert(res.is_truncated == "false", is_truncated=res.is_truncated)
                    return res
            d2.addCallback(_got_listing)
            return d2

        d = _list_some()
        d.addCallback(lambda res: res.__class__(res.name, res.prefix, res.marker, res.max_keys,
                                                "false", concat(all_contents)))
        def _log(f):
            log.msg(f, level=log.WEIRD)
            return f
        d.addErrback(_log)
        return d


class BackpressurePipeline(object):
    """
    I manage a pipeline of Deferred operations that allows the data source to feel backpressure
    when the pipeline is "full". I do not actually limit the number of operations in progress.
    """
    OPEN = 0
    CLOSING = 1
    CLOSED = 2

    def __init__(self, capacity):
        self._capacity = capacity  # how full we can be before causing calls to 'add' to block
        self._gauge = 0            # how full we are
        self._waiting = []         # callers of add() who are blocked
        self._unfinished = 0       # number of pending operations
        self._result_d = defer.Deferred()
        self._state = self.OPEN

    def add(self, _size, _func, *args, **kwargs):
        if self._state == self.CLOSED:
            msg = "add() called on closed BackpressurePipeline"
            log.err(msg, level=log.WEIRD)
            def _already_closed(): raise AssertionError(msg)
            return defer.execute(_already_closed)
        self._gauge += _size
        self._unfinished += 1
        fd = defer.maybeDeferred(_func, *args, **kwargs)
        fd.addBoth(self._call_finished, _size)
        fd.addErrback(log.err, "BackpressurePipeline._call_finished raised an exception")
        if self._gauge < self._capacity:
            return defer.succeed(None)
        d = defer.Deferred()
        self._waiting.append(d)
        return d

    def fail(self, f):
        if self._state != self.CLOSED:
            self._state = self.CLOSED
            eventually_errback(self._result_d)(f)

    def flush(self):
        if self._state == self.CLOSED:
            return defer.succeed(self._result_d)

        d = self.close()
        d.addBoth(self.reopen)
        return d

    def close(self):
        if self._state != self.CLOSED:
            if self._unfinished == 0:
                self._state = self.CLOSED
                eventually_callback(self._result_d)(None)
            else:
                self._state = self.CLOSING
        return self._result_d

    def reopen(self, res=None):
        _assert(self._state == self.CLOSED, state=self._state)
        self._result_d = defer.Deferred()
        self._state = self.OPEN
        return res

    def _call_finished(self, res, size):
        self._unfinished -= 1
        self._gauge -= size
        if isinstance(res, Failure):
            self.fail(res)

        if self._state == self.CLOSING:
            # repeat the unfinished == 0 check
            self.close()

        if self._state == self.CLOSED:
            while self._waiting:
                d = self._waiting.pop(0)
                eventual_chain(self._result_d, d)
        elif self._gauge < self._capacity:
            while self._waiting:
                d = self._waiting.pop(0)
                eventually_callback(d)(None)
        return None


class ChunkCache(object):
    """I cache chunks for a specific share object."""

    def __init__(self, container, key, chunksize, nchunks=1, initial_cachemap={}):
        self._container = container
        self._key = key
        self._chunksize = chunksize
        self._nchunks = nchunks

        # chunknum -> deferred data
        self._cachemap = initial_cachemap
        self._pipeline = BackpressurePipeline(PIPELINE_DEPTH)

    def set_nchunks(self, nchunks):
        self._nchunks = nchunks

    def _load_chunk(self, chunknum, chunkdata_d):
        d = self._container.get_object(get_chunk_key(self._key, chunknum))
        eventual_chain(source=d, target=chunkdata_d)
        return d

    def get(self, chunknum, result_d):
        if chunknum in self._cachemap:
            # cache hit; never stall
            eventual_chain(source=self._cachemap[chunknum], target=result_d)
            return defer.succeed(None)

        # Evict any chunks other than the first and last two, until there are
        # three or fewer chunks left cached.
        for candidate_chunknum in self._cachemap.keys():
            if len(self._cachemap) <= 3:
                break
            if candidate_chunknum not in (0, self._nchunks-2, self._nchunks-1):
                self.flush_chunk(candidate_chunknum)

        # cache miss; stall when the pipeline is full
        chunkdata_d = defer.Deferred()
        d = self._pipeline.add(1, self._load_chunk, chunknum, chunkdata_d)
        def _check(res):
            _assert(res is not None)
            return res
        chunkdata_d.addCallback(_check)
        self._cachemap[chunknum] = chunkdata_d
        eventual_chain(source=chunkdata_d, target=result_d)
        return d

    def flush_chunk(self, chunknum):
        if chunknum in self._cachemap:
            del self._cachemap[chunknum]

    def close(self):
        self._cachemap = None
        return self._pipeline.close()
