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
