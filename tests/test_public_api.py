from __future__ import annotations

import unittest

import pysmf
from pysmf import HeaderCatalog, read_file


class PublicAPITests(unittest.TestCase):
    def test_pysmf_reexports_public_api(self) -> None:
        self.assertIs(pysmf.HeaderCatalog, HeaderCatalog)
        self.assertEqual(read_file.__name__, "read_file")
        self.assertIn("HeaderCatalog", pysmf.__all__)
        self.assertIn("read_file", pysmf.__all__)
