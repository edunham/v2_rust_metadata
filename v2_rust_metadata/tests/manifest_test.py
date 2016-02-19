#! /usr/bin/env python

import unittest
import v2_rust_metadata.manifest as v2

class test_decompose_name(unittest.TestCase):

    def test_mac_nightly(self):
        filename = "rustc-nightly-i686-apple-darwin.tar.gz"
        channel = "nightly"
        result = v2.decompose_name(filename, channel)
        self.assertEqual(result, ("i686-apple-darwin", "rustc"))

    def test_wrong_channel(self):
        filename = "rustc-nightly-i686-apple-darwin.tar.gz"
        channel = "beta"
        result = v2.decompose_name(filename, channel)
        self.assertEqual(result, None)

class get_version_and_components_from_archive(unittest.TestCase):

    def test_generic_archive(self):
        pass

    def test_missing_comp_list(self):
        pass

    def test_empty_comp_list(self):
        pass

    def test_missing_version(self):
        pass

    def test_empty_archive(self):
        pass

