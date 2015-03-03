import os.path, simplejson
from twisted.trial import unittest
from twisted.python import usage

from allmydata.scripts import cli
from allmydata.util import fileutil
from allmydata.util.encodingutil import (quote_output, get_io_encoding,
                                         unicode_to_output, to_str)
from .no_network import GridTestMixin, config_hook_params_to_1_1_1
from .test_cli import CLITestMixin

timeout = 480 # deep_check takes 360s on Zandr's linksys box, others take > 240s

class Cp(GridTestMixin, CLITestMixin, unittest.TestCase):

    def test_not_enough_args(self):
        o = cli.CpOptions()
        self.failUnlessRaises(usage.UsageError,
                              o.parseOptions, ["onearg"])

    def test_unicode_filename(self):
        self.basedir = "cli/Cp/unicode_filename"

        fn1 = os.path.join(unicode(self.basedir), u"\u00C4rtonwall")
        try:
            fn1_arg = fn1.encode(get_io_encoding())
            artonwall_arg = u"\u00C4rtonwall".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        self.skip_if_cannot_represent_filename(fn1)

        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        DATA1 = "unicode file content"
        fileutil.write(fn1, DATA1)

        fn2 = os.path.join(self.basedir, "Metallica")
        DATA2 = "non-unicode file content"
        fileutil.write(fn2, DATA2)

        d = self.do_cli("create-alias", "tahoe")

        d.addCallback(lambda res: self.do_cli("cp", fn1_arg, "tahoe:"))

        d.addCallback(lambda res: self.do_cli("get", "tahoe:" + artonwall_arg))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA1))

        d.addCallback(lambda res: self.do_cli("cp", fn2, "tahoe:"))

        d.addCallback(lambda res: self.do_cli("get", "tahoe:Metallica"))
        d.addCallback(lambda (rc,out,err): self.failUnlessReallyEqual(out, DATA2))

        d.addCallback(lambda res: self.do_cli("ls", "tahoe:"))
        def _check((rc, out, err)):
            try:
                unicode_to_output(u"\u00C4rtonwall")
            except UnicodeEncodeError:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessReallyEqual(out, "Metallica\n")
                self.failUnlessIn(quote_output(u"\u00C4rtonwall"), err)
                self.failUnlessIn("files whose names could not be converted", err)
            else:
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessReallyEqual(out.decode(get_io_encoding()), u"Metallica\n\u00C4rtonwall\n")
                self.failUnlessReallyEqual(err, "")
        d.addCallback(_check)

        return d

    def test_dangling_symlink_vs_recursion(self):
        if not hasattr(os, 'symlink'):
            raise unittest.SkipTest("Symlinks are not supported by Python on this platform.")

        # cp -r on a directory containing a dangling symlink shouldn't assert
        self.basedir = "cli/Cp/dangling_symlink_vs_recursion"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})
        dn = os.path.join(self.basedir, "dir")
        os.mkdir(dn)
        fn = os.path.join(dn, "Fakebandica")
        ln = os.path.join(dn, "link")
        os.symlink(fn, ln)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("cp", "--recursive",
                                              dn, "tahoe:"))
        return d

    def test_copy_using_filecap(self):
        self.basedir = "cli/Cp/test_copy_using_filecap"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})
        outdir = os.path.join(self.basedir, "outdir")
        os.mkdir(outdir)
        fn1 = os.path.join(self.basedir, "Metallica")
        fn2 = os.path.join(outdir, "Not Metallica")
        fn3 = os.path.join(outdir, "test2")
        DATA1 = "puppies" * 10000
        fileutil.write(fn1, DATA1)

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign: self.do_cli("put", fn1))
        def _put_file((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.failUnlessIn("200 OK", err)
            # keep track of the filecap
            self.filecap = out.strip()
        d.addCallback(_put_file)

        # Let's try copying this to the disk using the filecap.
        d.addCallback(lambda ign: self.do_cli("cp", self.filecap, fn2))
        def _copy_file((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(fn2)
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_copy_file)

        # Test copying a filecap to local dir, which should fail without a
        # destination filename (#761).
        d.addCallback(lambda ign: self.do_cli("cp", self.filecap, outdir))
        def _resp((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error: you must specify a destination filename",
                              err)
            self.failUnlessReallyEqual(out, "")
        d.addCallback(_resp)

        # Create a directory, linked at tahoe:test .
        d.addCallback(lambda ign: self.do_cli("mkdir", "tahoe:test"))
        def _get_dir((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            self.dircap = out.strip()
        d.addCallback(_get_dir)

        # Upload a file to the directory.
        d.addCallback(lambda ign:
                      self.do_cli("put", fn1, "tahoe:test/test_file"))
        d.addCallback(lambda (rc, out, err): self.failUnlessReallyEqual(rc, 0))

        # Copying DIRCAP/filename to a local dir should work, because the
        # destination filename can be inferred.
        d.addCallback(lambda ign:
                      self.do_cli("cp",  self.dircap + "/test_file", outdir))
        def _get_resp((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(os.path.join(outdir, "test_file"))
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_get_resp)

        # ... and to an explicit filename different from the source filename.
        d.addCallback(lambda ign:
                      self.do_cli("cp",  self.dircap + "/test_file", fn3))
        def _get_resp2((rc, out, err)):
            self.failUnlessReallyEqual(rc, 0)
            results = fileutil.read(fn3)
            self.failUnlessReallyEqual(results, DATA1)
        d.addCallback(_get_resp2)

        # Test that the --verbose option prints correct indices (#1805).
        d.addCallback(lambda ign:
                      self.do_cli("cp", "--verbose", fn3, self.dircap))
        def _test_for_wrong_indices((rc, out, err)):
            lines = err.split('\n')
            self.failUnlessIn('examining 1 of 1', lines)
            self.failUnlessIn('starting copy, 1 files, 1 directories', lines)
            self.failIfIn('examining 0 of', err)
        d.addCallback(_test_for_wrong_indices)
        return d

    def test_cp_with_nonexistent_alias(self):
        # when invoked with an alias or aliases that don't exist, 'tahoe cp'
        # should output a sensible error message rather than a stack trace.
        self.basedir = "cli/Cp/cp_with_nonexistent_alias"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})
        d = self.do_cli("cp", "fake:file1", "fake:file2")
        def _check((rc, out, err)):
            self.failUnlessReallyEqual(rc, 1)
            self.failUnlessIn("error:", err)
        d.addCallback(_check)
        # 'tahoe cp' actually processes the target argument first, so we need
        # to check to make sure that validation extends to the source
        # argument.
        d.addCallback(lambda ign: self.do_cli("create-alias", "tahoe"))
        d.addCallback(lambda ign: self.do_cli("cp", "fake:file1",
                                              "tahoe:file2"))
        d.addCallback(_check)
        return d

    def test_unicode_dirnames(self):
        self.basedir = "cli/Cp/unicode_dirnames"

        fn1 = os.path.join(unicode(self.basedir), u"\u00C4rtonwall")
        try:
            fn1_arg = fn1.encode(get_io_encoding())
            del fn1_arg # hush pyflakes
            artonwall_arg = u"\u00C4rtonwall".encode(get_io_encoding())
        except UnicodeEncodeError:
            raise unittest.SkipTest("A non-ASCII command argument could not be encoded on this platform.")

        self.skip_if_cannot_represent_filename(fn1)

        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda res: self.do_cli("mkdir", "tahoe:test/" + artonwall_arg))
        d.addCallback(lambda res: self.do_cli("cp", "-r", "tahoe:test", "tahoe:test2"))
        d.addCallback(lambda res: self.do_cli("ls", "tahoe:test2/test"))
        def _check((rc, out, err)):
            try:
                unicode_to_output(u"\u00C4rtonwall")
            except UnicodeEncodeError:
                self.failUnlessReallyEqual(rc, 1)
                self.failUnlessReallyEqual(out, "")
                self.failUnlessIn(quote_output(u"\u00C4rtonwall"), err)
                self.failUnlessIn("files whose names could not be converted", err)
            else:
                self.failUnlessReallyEqual(rc, 0)
                self.failUnlessReallyEqual(out.decode(get_io_encoding()), u"\u00C4rtonwall\n")
                self.failUnlessReallyEqual(err, "")
        d.addCallback(_check)

        return d

    def test_cp_replaces_mutable_file_contents(self):
        self.basedir = "cli/Cp/cp_replaces_mutable_file_contents"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        # Write a test file, which we'll copy to the grid.
        test_txt_path = os.path.join(self.basedir, "test.txt")
        test_txt_contents = "foo bar baz"
        f = open(test_txt_path, "w")
        f.write(test_txt_contents)
        f.close()

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:test"))
        # We have to use 'tahoe put' here because 'tahoe cp' doesn't
        # know how to make mutable files at the destination.
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", test_txt_path, "tahoe:test/test.txt"))
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        def _check((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(out, test_txt_contents)
        d.addCallback(_check)

        # We'll do ls --json to get the read uri and write uri for the
        # file we've just uploaded.
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        def _get_test_txt_uris((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])

            self.failUnlessIn("rw_uri", data)
            self.rw_uri = to_str(data["rw_uri"])
            self.failUnlessIn("ro_uri", data)
            self.ro_uri = to_str(data["ro_uri"])
        d.addCallback(_get_test_txt_uris)

        # Now make a new file to copy in place of test.txt.
        new_txt_path = os.path.join(self.basedir, "new.txt")
        new_txt_contents = "baz bar foo" * 100000
        f = open(new_txt_path, "w")
        f.write(new_txt_contents)
        f.close()

        # Copy the new file on top of the old file.
        d.addCallback(lambda ignored:
            self.do_cli("cp", new_txt_path, "tahoe:test/test.txt"))

        # If we get test.txt now, we should see the new data.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, new_txt_contents))
        # If we get the json of the new file, we should see that the old
        # uri is there
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        def _check_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])

            self.failUnlessIn("ro_uri", data)
            self.failUnlessEqual(to_str(data["ro_uri"]), self.ro_uri)
            self.failUnlessIn("rw_uri", data)
            self.failUnlessEqual(to_str(data["rw_uri"]), self.rw_uri)
        d.addCallback(_check_json)

        # and, finally, doing a GET directly on one of the old uris
        # should give us the new contents.
        d.addCallback(lambda ignored:
            self.do_cli("get", self.rw_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, new_txt_contents))
        # Now copy the old test.txt without an explicit destination
        # file. tahoe cp will match it to the existing file and
        # overwrite it appropriately.
        d.addCallback(lambda ignored:
            self.do_cli("cp", test_txt_path, "tahoe:test"))
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test/test.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_txt_contents))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test/test.txt"))
        d.addCallback(_check_json)
        d.addCallback(lambda ignored:
            self.do_cli("get", self.rw_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_txt_contents))

        # Now we'll make a more complicated directory structure.
        # test2/
        # test2/mutable1
        # test2/mutable2
        # test2/imm1
        # test2/imm2
        imm_test_txt_path = os.path.join(self.basedir, "imm_test.txt")
        imm_test_txt_contents = test_txt_contents * 10000
        fileutil.write(imm_test_txt_path, imm_test_txt_contents)
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:test2"))
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", new_txt_path,
                        "tahoe:test2/mutable1"))
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", new_txt_path,
                        "tahoe:test2/mutable2"))
        d.addCallback(lambda ignored:
            self.do_cli('put', new_txt_path, "tahoe:test2/imm1"))
        d.addCallback(lambda ignored:
            self.do_cli("put", imm_test_txt_path, "tahoe:test2/imm2"))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2"))
        def _process_directory_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")
            self.failUnless(data['mutable'])
            self.failUnlessIn("children", data)
            children = data['children']

            # Store the URIs for later use.
            self.childuris = {}
            for k in ["mutable1", "mutable2", "imm1", "imm2"]:
                self.failUnlessIn(k, children)
                childtype, childdata = children[k]
                self.failUnlessEqual(childtype, "filenode")
                if "mutable" in k:
                    self.failUnless(childdata['mutable'])
                    self.failUnlessIn("rw_uri", childdata)
                    uri_key = "rw_uri"
                else:
                    self.failIf(childdata['mutable'])
                    self.failUnlessIn("ro_uri", childdata)
                    uri_key = "ro_uri"
                self.childuris[k] = to_str(childdata[uri_key])
        d.addCallback(_process_directory_json)
        # Now build a local directory to copy into place, like the following:
        # test2/
        # test2/mutable1
        # test2/mutable2
        # test2/imm1
        # test2/imm3
        def _build_local_directory(ignored):
            test2_path = os.path.join(self.basedir, "test2")
            fileutil.make_dirs(test2_path)
            for fn in ("mutable1", "mutable2", "imm1", "imm3"):
                fileutil.write(os.path.join(test2_path, fn), fn * 1000)
            self.test2_path = test2_path
        d.addCallback(_build_local_directory)
        d.addCallback(lambda ignored:
            self.do_cli("cp", "-r", self.test2_path, "tahoe:"))

        # We expect that mutable1 and mutable2 are overwritten in-place,
        # so they'll retain their URIs but have different content.
        def _process_file_json((rc, out, err), fn):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "filenode")

            if "mutable" in fn:
                self.failUnless(data['mutable'])
                self.failUnlessIn("rw_uri", data)
                self.failUnlessEqual(to_str(data["rw_uri"]), self.childuris[fn])
            else:
                self.failIf(data['mutable'])
                self.failUnlessIn("ro_uri", data)
                self.failIfEqual(to_str(data["ro_uri"]), self.childuris[fn])

        for fn in ("mutable1", "mutable2"):
            d.addCallback(lambda ignored, fn=fn:
                self.do_cli("get", "tahoe:test2/%s" % fn))
            d.addCallback(lambda (rc, out, err), fn=fn:
                self.failUnlessEqual(out, fn * 1000))
            d.addCallback(lambda ignored, fn=fn:
                self.do_cli("ls", "--json", "tahoe:test2/%s" % fn))
            d.addCallback(_process_file_json, fn=fn)

        # imm1 should have been replaced, so both its uri and content
        # should be different.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm1"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, "imm1" * 1000))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2/imm1"))
        d.addCallback(_process_file_json, fn="imm1")

        # imm3 should have been created.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm3"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, "imm3" * 1000))

        # imm2 should be exactly as we left it, since our newly-copied
        # directory didn't contain an imm2 entry.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test2/imm2"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, imm_test_txt_contents))
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test2/imm2"))
        def _process_imm2_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "filenode")
            self.failIf(data['mutable'])
            self.failUnlessIn("ro_uri", data)
            self.failUnlessEqual(to_str(data["ro_uri"]), self.childuris["imm2"])
        d.addCallback(_process_imm2_json)
        return d

    def test_cp_overwrite_readonly_mutable_file(self):
        # tahoe cp should print an error when asked to overwrite a
        # mutable file that it can't overwrite.
        self.basedir = "cli/Cp/overwrite_readonly_mutable_file"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        # This is our initial file. We'll link its readcap into the
        # tahoe: alias.
        test_file_path = os.path.join(self.basedir, "test_file.txt")
        test_file_contents = "This is a test file."
        fileutil.write(test_file_path, test_file_contents)

        # This is our replacement file. We'll try and fail to upload it
        # over the readcap that we linked into the tahoe: alias.
        replacement_file_path = os.path.join(self.basedir, "replacement.txt")
        replacement_file_contents = "These are new contents."
        fileutil.write(replacement_file_path, replacement_file_contents)

        d = self.do_cli("create-alias", "tahoe:")
        d.addCallback(lambda ignored:
            self.do_cli("put", "--mutable", test_file_path))
        def _get_test_uri((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            # this should be a write uri
            self._test_write_uri = out
        d.addCallback(_get_test_uri)
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", self._test_write_uri))
        def _process_test_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)
            filetype, data = simplejson.loads(out)

            self.failUnlessEqual(filetype, "filenode")
            self.failUnless(data['mutable'])
            self.failUnlessIn("ro_uri", data)
            self._test_read_uri = to_str(data["ro_uri"])
        d.addCallback(_process_test_json)
        # Now we'll link the readonly URI into the tahoe: alias.
        d.addCallback(lambda ignored:
            self.do_cli("ln", self._test_read_uri, "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))
        # Let's grab the json of that to make sure that we did it right.
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:"))
        def _process_tahoe_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")
            self.failUnlessIn("children", data)
            kiddata = data['children']

            self.failUnlessIn("test_file.txt", kiddata)
            testtype, testdata = kiddata['test_file.txt']
            self.failUnlessEqual(testtype, "filenode")
            self.failUnless(testdata['mutable'])
            self.failUnlessIn("ro_uri", testdata)
            self.failUnlessEqual(to_str(testdata["ro_uri"]), self._test_read_uri)
            self.failIfIn("rw_uri", testdata)
        d.addCallback(_process_tahoe_json)
        # Okay, now we're going to try uploading another mutable file in
        # place of that one. We should get an error.
        d.addCallback(lambda ignored:
            self.do_cli("cp", replacement_file_path, "tahoe:test_file.txt"))
        def _check_error_message((rc, out, err)):
            self.failUnlessEqual(rc, 1)
            self.failUnlessIn("replace or update requested with read-only cap", err)
        d.addCallback(_check_error_message)
        # Make extra sure that that didn't work.
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        d.addCallback(lambda ignored:
            self.do_cli("get", self._test_read_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        # Now we'll do it without an explicit destination.
        d.addCallback(lambda ignored:
            self.do_cli("cp", test_file_path, "tahoe:"))
        d.addCallback(_check_error_message)
        d.addCallback(lambda ignored:
            self.do_cli("get", "tahoe:test_file.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        d.addCallback(lambda ignored:
            self.do_cli("get", self._test_read_uri))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(out, test_file_contents))
        # Now we'll link a readonly file into a subdirectory.
        d.addCallback(lambda ignored:
            self.do_cli("mkdir", "tahoe:testdir"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))
        d.addCallback(lambda ignored:
            self.do_cli("ln", self._test_read_uri, "tahoe:test/file2.txt"))
        d.addCallback(lambda (rc, out, err):
            self.failUnlessEqual(rc, 0))

        test_dir_path = os.path.join(self.basedir, "test")
        fileutil.make_dirs(test_dir_path)
        for f in ("file1.txt", "file2.txt"):
            fileutil.write(os.path.join(test_dir_path, f), f * 10000)

        d.addCallback(lambda ignored:
            self.do_cli("cp", "-r", test_dir_path, "tahoe:"))
        d.addCallback(_check_error_message)
        d.addCallback(lambda ignored:
            self.do_cli("ls", "--json", "tahoe:test"))
        def _got_testdir_json((rc, out, err)):
            self.failUnlessEqual(rc, 0)

            filetype, data = simplejson.loads(out)
            self.failUnlessEqual(filetype, "dirnode")

            self.failUnlessIn("children", data)
            childdata = data['children']

            self.failUnlessIn("file2.txt", childdata)
            file2type, file2data = childdata['file2.txt']
            self.failUnlessEqual(file2type, "filenode")
            self.failUnless(file2data['mutable'])
            self.failUnlessIn("ro_uri", file2data)
            self.failUnlessEqual(to_str(file2data["ro_uri"]), self._test_read_uri)
            self.failIfIn("rw_uri", file2data)
        d.addCallback(_got_testdir_json)
        return d

    def test_cp_verbose(self):
        self.basedir = "cli/Cp/cp_verbose"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        # Write two test files, which we'll copy to the grid.
        test1_path = os.path.join(self.basedir, "test1")
        test2_path = os.path.join(self.basedir, "test2")
        fileutil.write(test1_path, "test1")
        fileutil.write(test2_path, "test2")

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign:
            self.do_cli("cp", "--verbose", test1_path, test2_path, "tahoe:"))
        def _check(res):
            (rc, out, err) = res
            self.failUnlessEqual(rc, 0, str(res))
            self.failUnlessIn("Success: files copied", out, str(res))
            self.failUnlessEqual(err, """\
attaching sources to targets, 2 files / 0 dirs in root
targets assigned, 1 dirs, 2 files
starting copy, 2 files, 1 directories
1/2 files, 0/1 directories
2/2 files, 0/1 directories
1/1 directories
""", str(res))
        d.addCallback(_check)
        return d

    def test_cp_copies_dir(self):
        # This test ensures that a directory is copied using
        # tahoe cp -r. Refer to ticket #712:
        # https://tahoe-lafs.org/trac/tahoe-lafs/ticket/712

        self.basedir = "cli/Cp/cp_copies_dir"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})
        subdir = os.path.join(self.basedir, "foo")
        os.mkdir(subdir)
        test1_path = os.path.join(subdir, "test1")
        fileutil.write(test1_path, "test1")

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign:
            self.do_cli("cp", "-r", subdir, "tahoe:"))
        d.addCallback(lambda ign:
            self.do_cli("ls", "tahoe:"))
        def _check(res, item):
            (rc, out, err) = res
            self.failUnlessEqual(rc, 0)
            self.failUnlessEqual(err, "")
            self.failUnlessIn(item, out, str(res))
        d.addCallback(_check, "foo")
        d.addCallback(lambda ign:
            self.do_cli("ls", "tahoe:foo/"))
        d.addCallback(_check, "test1")

        d.addCallback(lambda ign: fileutil.rm_dir(subdir))
        d.addCallback(lambda ign: self.do_cli("cp", "-r", "tahoe:foo", self.basedir))
        def _check_local_fs(ign):
            self.failUnless(os.path.isdir(self.basedir))
            self.failUnless(os.path.isfile(test1_path))
        d.addCallback(_check_local_fs)
        return d

    def test_ticket_2027(self):
        # This test ensures that tahoe will copy a file from the grid to
        # a local directory without a specified file name.
        # https://tahoe-lafs.org/trac/tahoe-lafs/ticket/2027
        self.basedir = "cli/Cp/cp_verbose"
        self.set_up_grid(num_servers=1, client_config_hooks={0: config_hook_params_to_1_1_1})

        # Write a test file, which we'll copy to the grid.
        test1_path = os.path.join(self.basedir, "test1")
        fileutil.write(test1_path, "test1")

        d = self.do_cli("create-alias", "tahoe")
        d.addCallback(lambda ign:
            self.do_cli("cp", test1_path, "tahoe:"))
        d.addCallback(lambda ign:
            self.do_cli("cp", "tahoe:test1", self.basedir))
        def _check(res):
            (rc, out, err) = res
            self.failUnlessIn("Success: file copied", out, str(res))
        return d
