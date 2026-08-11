from __future__ import annotations

import importlib
import unittest

import pysmf
from pysmf import (
    SMFRecordTypeRegistry,
    parse_record,
    read_file,
    read_structured_records,
)


class PublicAPITests(unittest.TestCase):
    def test_pysmf_reexports_public_api(self) -> None:
        self.assertIs(pysmf.SMFRecordTypeRegistry, SMFRecordTypeRegistry)
        self.assertEqual(read_file.__name__, "read_file")
        self.assertEqual(parse_record.__name__, "parse_record")
        self.assertEqual(read_structured_records.__name__, "read_structured_records")
        self.assertIn("SMFRecordTypeRegistry", pysmf.__all__)
        self.assertIn("parse_record", pysmf.__all__)
        self.assertIn("read_file", pysmf.__all__)
        self.assertIn("read_structured_records", pysmf.__all__)

    def test_smf_parser_package_is_not_public(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("smf_parser")
