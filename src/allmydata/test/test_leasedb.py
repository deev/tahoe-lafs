
import os, time
from twisted.trial import unittest
from twisted.internet import defer
from allmydata.util import fileutil
from allmydata.storage.leasedb import LeaseDB, SHARETYPE_IMMUTABLE, \
    SHARETYPE_MUTABLE
from allmydata.storage.accounting_crawler import AccountingCrawler
from allmydata.storage.expiration import ExpirationPolicy


BASE_ACCOUNTS = set([(0,u"anonymous"), (1,u"starter")])

class DB(unittest.TestCase):
    def make(self, testname):
        basedir = os.path.join("leasedb", "DB", testname)
        fileutil.make_dirs(basedir)
        dbfilename = os.path.join(basedir, "leasedb.sqlite")
        return dbfilename

    def test_create(self):
        dbfilename = self.make("create")
        l = LeaseDB(dbfilename)
        self.failUnlessEqual(set(l.get_all_accounts()), BASE_ACCOUNTS)

        # should be able to open an existing one too
        l2 = LeaseDB(dbfilename)
        self.failUnlessEqual(set(l2.get_all_accounts()), BASE_ACCOUNTS)


AB = ("abtnioga6deziyqd64gm65qbnu",  0, SHARETYPE_IMMUTABLE)
DE = ("dekrcoczhdj5xh6zd4v62xhdnu",  1, SHARETYPE_MUTABLE)
FG = ("fgxnicsxj4eaatcb5dayqiifsi", 19, SHARETYPE_IMMUTABLE)
ZZ = ("zzs6tetijo4zamjlkfzwaihkse",  8, SHARETYPE_MUTABLE)


class FakeStorageServer(object):
    def __init__(self, sharedir):
        self.sharedir = sharedir


#class Crawler(unittest.TestCase):
class OFF_Crawler:
    def make(self, testname):
        storedir = os.path.join("leasedb", "Crawler", testname)
        fileutil.make_dirs(storedir)
        dbfilename = os.path.join(storedir, "leasedb.sqlite")
        self.sharedir = os.path.join(storedir, "shares")
        fileutil.make_dirs(self.sharedir)
        self.statefile = os.path.join(storedir, "leasedb_crawler.state")
        self.leasedb = LeaseDB(dbfilename)
        ep = ExpirationPolicy(enabled=True, mode="age", override_lease_duration=2000)
        self.crawler = AccountingCrawler(FakeStorageServer(self.sharedir), self.statefile, self.leasedb)
        self.crawler.set_expiration_policy(ep)
        return (self.leasedb, self.crawler)

    def add_external_share(self, shareid):
        (si_s, shnum, _sharetype) = shareid
        prefix = si_s[:2]
        prefixdir = os.path.join(self.sharedir, prefix)
        bucketdir = os.path.join(prefixdir, si_s)
        sharefile = os.path.join(bucketdir, str(shnum))
        if not os.path.isdir(prefixdir):
            os.mkdir(prefixdir)
        if not os.path.isdir(bucketdir):
            os.mkdir(bucketdir)
        f = open(sharefile, "w")
        f.write("I'm a share!\n")
        f.close()
        return sharefile

    def add_share(self, leasedb, shareid):
        (si_s, shnum, sharetype) = shareid
        self.add_external_share()
        prefix = si_s[:2]
        leasedb.add_new_share(prefix, si_s, shnum, 20, sharetype)
        OWNER=3 ; EXPIRETIME=time.time() + 30*24*60*60
        leasedb.add_or_renew_leases(si_s, shnum, OWNER, EXPIRETIME)

    def delete_external_share(self, shareid):
        (si_s, shnum, _sharetype) = shareid
        prefix = si_s[:2]
        prefixdir = os.path.join(self.sharedir, prefix)
        bucketdir = os.path.join(prefixdir, si_s)
        sharefile = os.path.join(bucketdir, str(shnum))
        os.unlink(sharefile)
        try:
            os.rmdir(bucketdir)
            os.rmdir(prefixdir)
        except EnvironmentError:
            pass

    def have_sharefile(self, shareid):
        (si_s, shnum, _sharetype) = shareid
        prefix = si_s[:2]
        prefixdir = os.path.join(self.sharedir, prefix)
        bucketdir = os.path.join(prefixdir, si_s)
        sharefile = os.path.join(bucketdir, str(shnum))
        return os.path.exists(sharefile)

    def expire_share(self, shareid):
        (si_s, shnum, _sharetype) = shareid
        # accelerated expiration of all leases for this share
        c = self.leasedb._cursor
        c.execute("UPDATE `leases` SET `expiration_time`=0"
                  " WHERE `storage_index`=? AND `shnum`=?",
                  (si_s, shnum))
        self.leasedb._db.commit()

    def remove_garbage(self):
        # this returns the first bunch of shares without leases
        shareids = self.leasedb.get_unleased_shares_for_prefix('aa')
        #self.failUnlessEqual(shareids, [shareid])
        # this does an asynchronous delete of the given expired shares, and
        # removes their entries from the 'shares' table
        return self.crawler.remove_unleased_shares(shareids) #FIXME

    def count_shares(self):
        # query DB
        #
        # first, find all shares that have starter leases (including those
        # with additional non-starter leases)
        c = self.leasedb._cursor
        c = c.execute("SELECT `storage_index`, `shnum` FROM `leases`"
                      " WHERE `account_id` = 1")
        have_starter = set([tuple(row) for row in c.fetchall()])
        c = c.execute("SELECT `storage_index`, `shnum` FROM `leases`")
        #have_leases = set([tuple(row) for row in c.fetchall()])
        c = c.execute("SELECT `storage_index`, `shnum` FROM `leases`"
                      " WHERE `account_id` != 1")
        have_non_starter = set([tuple(row) for row in c.fetchall()])
        have_only_starter = have_starter - have_non_starter
        live = have_non_starter
        garbage = set([(row[0], row[1]) for row in self.leasedb.get_unleased_shares()])
        return (have_only_starter, live, garbage)

    def check_shares(self, starter=set(), live=set(), garbage=set()):
        got_starter, got_live, got_garbage = self.count_shares()
        self.failUnlessEqual(got_starter,  set([(row[0], row[1]) for row in starter]))
        self.failUnlessEqual(got_live,     set([(row[0], row[1]) for row in live]))
        self.failUnlessEqual(got_garbage,  set([(row[0], row[1]) for row in garbage]))

    def test_shares(self):
        # make sure the crawler handles shares being added and removed
        # externally, and that it deletes expired shares safely.
        l,c = self.make("shares")

        d = defer.maybeDeferred(c.crawl)
        def _then1(ign):
            self.check_shares()
            self.add_external_share(AB)
            self.check_shares()
            return c.crawl()
        d.addCallback(_then1)
        def _then2(ign):
            self.check_shares(starter=set([AB]))
            self.add_share(DE)
            self.add_share(FG)
            self.check_shares(starter=set([AB]), live=set([DE,FG]))
            return c.crawl()
        d.addCallback(_then2)
        def _then3(ign):
            self.check_shares(starter=set([AB]), live=set([DE,FG]))
            self.delete_external_share(DE)
            self.check_shares(starter=set([AB]), live=set([DE,FG]))
            return c.crawl()
        d.addCallback(_then3)
        def _then4(ign):
            self.check_shares(starter=set([AB]), live=set([FG]))
            self.expire_share(AB)
            # This deletes all expired leases. We assume DB operations are
            # synchronous, but removal of share files does not occur until
            # remove_unleased_shares is called.
            self.leasedb.remove_expired_leases() #FIXME
            self.failUnless(self.have_sharefile(AB))
            self.check_shares(live=set([FG]), garbage=set([AB]))
            return self.remove_garbage()
        d.addCallback(_then4)
        def _then5(ign):
            self.failIf(self.have_sharefile(AB))
            self.check_shares(live=set([FG]))
            return c.crawl()
        d.addCallback(_then4)
        def _then6(ign):
            self.check_shares(live=set([FG]))
        d.addCallback(_then5)

        return d
