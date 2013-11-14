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

class MutableTest(unittest.TestCase):

    def test_modify_existing_file(self):
        """
        If a mutable filenode is asked to modify the contents, and the
        servers serve up shares of version 1 when initially asked, but then
        server up shares of version 2 if asked a second time, then the
        mutable filenode ought to use the most recent version that it learned
        about when it is generating its new contents.

        This is inspired by #1670:

        https://tahoe-lafs.org/trac/tahoe-lafs/ticket/1670
        """

        orig = "OLD FILE CONTENTS"

        k = 3
        n = 10
        default_encoding_parameters = { 'k': k, 'n': n }

        verinfo_1 = (1, 'mock root hash 1', 'mock IV', 99, len(orig), k, n, 'mock prefix', ())
        verinfo_2 = (2, 'mock root hash 2', 'mock IV', 99, len(orig), k, n, 'mock prefix', ())
        verinfo_3 = (3, 'mock root hash 3', 'mock IV', 99, len(orig), k, n, 'mock prefix', ())

        sM = mock.Mock()
        sM.best_recoverable_version.return_value = verinfo_1
        sM.get_last_update.return_value = (MODE_WRITE,)
        sM.recoverable_versions.return_value = (verinfo_1,)
        sM.make_versionmap.return_value = {verinfo_1: "SOMETHING"}
        sM.highest_seqnum.return_value = verinfo_1[0]

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
        mockDownloadResults.chunks = [orig,]

        mockRetrieveObj = mock.Mock()
        def mock_download(*args, **kwargs):
            return defer.succeed(mockDownloadResults)

        mockRetrieveObj.download.side_effect = mock_download

        mockRetrieveClass = mock.Mock()
        mockRetrieveClass.return_value = mockRetrieveObj
        self.patch(allmydata.mutable.filenode, 'Retrieve', mockRetrieveClass)

        mockPublishObj = mock.Mock()
        #XXXmockPublishObj.publish.return_value = defer.succeed(mockPublishResults)
        #XXXmockPublishResults = mock.Mock()

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
        
        # XXX make it so if you download v1 you get "VERSION 1 STUFF" and if
        # you download v2 you get "VERSION 2 STUFF".

        def modifier(old):
            return old + "...NEW STUFF"

        d = filenobj.modify(modifier)
        def _then(ign):
            return filenobj.download_best_version()
        d.addCallback(_then)
                          
        def _then2(result):
            self.failUnlessEqual(result, orig + "...NEW STUFF")
        d.addCallback(_then2)

        def _dump_calls(whatever):
            print "xxx sMc got this: ", mock_sM_class.call_args
            print "xxx sM got this: ", sM.method_calls
            print "xxx smU got this: ", smU.call_args
            print "xxx mockRetrieveObj got this: ", mockRetrieveObj.method_calls
            print "xxx mockPublishObj got this: ", mockPublishObj.method_calls
            return whatever

        d.addBoth(_dump_calls)
        return d
    test_modify_existing_file.timeout = 2
