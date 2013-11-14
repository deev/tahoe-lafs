# -*- coding: utf-8-with-signature -*-

from twisted.internet import defer
from twisted.trial import unittest
from allmydata.mutable import filenode
from allmydata import uri
import mock
from foolscap.api import eventually
from allmydata.mutable.common import MODE_WRITE

class MockFileCap(uri.WriteableMDMFFileURI):
    def __init__(self, *args, **kwargs):
        uri.WriteableMDMFFileURI.__init__(self, 'MOCK WRITE KEY', 'MOCK FINGERPRINT', *args, **kwargs)
        self.readkey = 'MOCK READ KEY'
        self.storage_index = 'MOCK STORAGE INDEX'
    def is_readonly(self):
        return False
    def is_mutable(self):
        return True

k = 3
n = 10
default_encoding_parameters = { 'k': k, 'n': n }

filecontents = [ "FILE CONTENTS 1",  "FILE CONTENTS 2", "FILE CONTENTS 3",]

verinfos = [
    (0, 'mock root hash 0', 'mock IV', 99, len(filecontents[0]), k, n, 'mock prefix', ()),
    (1, 'mock root hash 1', 'mock IV', 99, len(filecontents[1]), k, n, 'mock prefix', ()),
    (2, 'mock root hash 2', 'mock IV', 99, len(filecontents[2]), k, n, 'mock prefix', ()),
    ]

class MutableTest(unittest.TestCase):

    def test_modify_existing_file(self):
        """
        If a mutable filenode is asked to modify the contents, and the
        servers serve up shares of version 1 any time you ask, then the
        mutable filenode ought to use version 1 when it is generating its new
        contents.
        """

        sM = mock.Mock()
        sM.best_recoverable_version.return_value = verinfos[0]
        sM.get_last_update.return_value = (MODE_WRITE,)
        sM.recoverable_versions.return_value = (verinfos[0],)
        sM.make_versionmap.return_value = {verinfos[0]: "SOMETHING"}
        sM.highest_seqnum.return_value = verinfos[0][0]

        mock_sM_class = mock.Mock()
        mock_sM_class.return_value = sM

        smU = mock.Mock()
        def mock_smU_class(filenode=filenode, *args, **kwargs):
            def mock_update(*args, **kwargs):
                # side effect of this is to set the pubkey
                filenode._populate_pubkey('DUMMY PUB KEY')
                filenode._populate_privkey('DUMMY PRIV KEY')
                return defer.succeed(sM)
            smU.update.side_effect = mock_update
            return smU

        import allmydata.mutable.filenode
        self.patch(allmydata.mutable.filenode, 'ServerMap', mock_sM_class)
        self.patch(allmydata.mutable.filenode, 'ServermapUpdater', mock_smU_class)

        mockDownloadResults = mock.Mock()
        mockDownloadResults.chunks = [filecontents[0],]

        mockRetrieveObj = mock.Mock()
        def mock_download(*args, **kwargs):
            return defer.succeed(mockDownloadResults)

        mockRetrieveObj.download.side_effect = mock_download

        mockRetrieveClass = mock.Mock()
        mockRetrieveClass.return_value = mockRetrieveObj
        self.patch(allmydata.mutable.filenode, 'Retrieve', mockRetrieveClass)

        saved_mutable_data = [None]
        mockPublishObj = mock.Mock()
        def mock_publish(mutabledata):
            saved_mutable_data[0] = mutabledata
            d = defer.Deferred()
            def _ev():
                d.callback(None)
            eventually(_ev)
            return d
        mockPublishObj.publish.side_effect = mock_publish

        mockPublishClass = mock.Mock()
        mockPublishClass.return_value = mockPublishObj
        self.patch(allmydata.mutable.filenode, 'Publish', mockPublishClass)

        mstorage_broker = mock.Mock()

        msecret_holder = mock.Mock(name='msecret_holder')
        mhistory = mock.Mock()
        mnodemaker = mock.Mock(name='mnodemaker')
        muploader = mock.Mock(name='muploader')
        mfilecap = MockFileCap()

        filenobj = filenode.MutableFileNode(mstorage_broker, msecret_holder, default_encoding_parameters, mhistory)
        filenobj.init_from_cap(mfilecap)
        
        def modifier(old):
            return old + "...NEW STUFF"

        d = filenobj.modify(modifier)
        def _then(ign):
            # Okay at the point the filenobj can get a green flag if it has
            # pushed the right new-version to the Publish object.
            smd = saved_mutable_data[0]
            pos = smd._filehandle.tell()
            smd._filehandle.seek(0)
            data = smd._filehandle.read()
            smd._filehandle.seek(pos)

            self.failUnlessEqual(data, filecontents[0] + "...NEW STUFF")
        d.addCallback(_then)
                          
        return d

    def test_write_collision(self):
        """
        If a mutable filenode is asked to modify the contents, and the
        servers serve up shares of version 1 when initially asked, but then
        server up shares of version 2 if asked a second time, then the
        mutable filenode ought to stop and report a UCWE and not do anything
        stupid like, say, blow away version 2, or get an internal KeyError.

        This is inspired by #1670:

        https://tahoe-lafs.org/trac/tahoe-lafs/ticket/1670
        """
        class MockServerMap(object):
            def __init__(self, *args, **kwargs):
                self.how_many_times_asked = 0

            def best_recoverable_version(self):
                verinfo = verinfos[self.how_many_times_asked]
                self.how_many_times_asked += 1
                return verinfo

            def get_last_update(self):
                return (MODE_WRITE,)

            def recoverable_versions(self):
                return (verinfos[self.how_many_times_asked],)

            def make_versionmap(self):
                return {verinfos[self.how_many_times_asked]: "SOMETHING"}

            def highest_seqnum(self):
                return verinfos[self.how_many_times_asked][0]

        sM = MockServerMap()

        mock_sM_class = mock.Mock()
        mock_sM_class.return_value = sM

        smU = mock.Mock()
        def mock_smU_class(filenode=filenode, *args, **kwargs):
            def mock_update(*args, **kwargs):
                # side effect of this is to set the pubkey
                filenode._populate_pubkey('DUMMY PUB KEY')
                filenode._populate_privkey('DUMMY PRIV KEY')
                return defer.succeed(sM)
            smU.update.side_effect = mock_update
            return smU

        import allmydata.mutable.filenode
        self.patch(allmydata.mutable.filenode, 'ServerMap', mock_sM_class)
        self.patch(allmydata.mutable.filenode, 'ServermapUpdater', mock_smU_class)

        mockDownloadResults = mock.Mock()
        mockDownloadResults.chunks = [filecontents[0],]

        mockRetrieveObj = mock.Mock()
        def mock_download(*args, **kwargs):
            return defer.succeed(mockDownloadResults)

        mockRetrieveObj.download.side_effect = mock_download

        mockRetrieveClass = mock.Mock()
        mockRetrieveClass.return_value = mockRetrieveObj
        self.patch(allmydata.mutable.filenode, 'Retrieve', mockRetrieveClass)

        saved_mutable_data = [None]
        mockPublishObj = mock.Mock()
        def mock_publish(mutabledata):
            saved_mutable_data[0] = mutabledata
            d = defer.Deferred()
            def _ev():
                d.callback(None)
            eventually(_ev)
            return d
        mockPublishObj.publish.side_effect = mock_publish

        mockPublishClass = mock.Mock()
        mockPublishClass.return_value = mockPublishObj
        self.patch(allmydata.mutable.filenode, 'Publish', mockPublishClass)

        mstorage_broker = mock.Mock()

        msecret_holder = mock.Mock(name='msecret_holder')
        mhistory = mock.Mock()
        mnodemaker = mock.Mock(name='mnodemaker')
        muploader = mock.Mock(name='muploader')
        mfilecap = MockFileCap()

        filenobj = filenode.MutableFileNode(mstorage_broker, msecret_holder, default_encoding_parameters, mhistory)
        filenobj.init_from_cap(mfilecap)
        
        def modifier(old):
            return old + "...NEW STUFF"

        d = filenobj.modify(modifier)
        def _then(ign):
            print "XXX sM how many times ", sM.how_many_times_asked

            # Okay at the point the filenobj gets a red flag if it has pushed
            # a version-1-based file, because that will have stomped on
            # someone else's version 2!
            smd = saved_mutable_data[0]
            pos = smd._filehandle.tell()
            smd._filehandle.seek(0)
            data = smd._filehandle.read()
            smd._filehandle.seek(pos)

            self.failIfEqual(data, filecontents[0] + "...NEW STUFF")
        d.addCallback(_then)
        return d

        #XXXdef _dump_calls(whatever):
        #XXX    print "xxx sMc got this: ", mock_sM_class.call_args
        #XXX    print "xxx sM got this: ", sM.method_calls
        #XXX    print "xxx smU got this: ", smU.call_args
        #XXX    print "xxx mockRetrieveObj got this: ", mockRetrieveObj.method_calls
        #XXX    print "xxx mockPublishObj got this: ", mockPublishObj.method_calls
        #XXX    
        #XXX    print "xxx mockPublishObj's saved_mutable_data: ", 
        #XXX    return whatever
        #XXXd.addBoth(_dump_calls)
