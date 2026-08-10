from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pysmf import HeaderCatalogError, SMFParseError, parse_record
from tests.helpers import ebcdic, standard_record


def native_type80_fields() -> dict[str, object]:
    return {
        "smf80des": 1,
        "smf80evt": 2,
        "smf80evq": 3,
        "smf80usr": ebcdic("SECADM1 "),
        "smf80grp": ebcdic("SYS1    "),
        "smf80rel": 104,
        "smf80cnt": 1,
        "smf80ath": 4,
        "smf80rea": 5,
        "smf80tlv": 6,
        "smf80err": 7,
        "smf80trm": ebcdic("TERMID  "),
        "smf80jbn": ebcdic("JOBNAME "),
        "smf80rst": 12_345,
        "smf80rsd": b"\x00\x20\x23\x1f",
        "smf80uid": ebcdic("USERID  "),
        "smf80ver": 8,
        "smf80re2": 9,
        "smf80vrm": ebcdic("7700"),
        "smf80sec": ebcdic("SECLAB  "),
        "smf80rl2": 140,
        "smf80ct2": 1,
        "smf80au2": 10,
    }


class StructuredRecordTests(unittest.TestCase):
    def test_parse_record_uses_generated_native_parser(self) -> None:
        from pysmf import records

        native = SimpleNamespace(
            parse_record=lambda record_type, data: native_type80_fields()
        )

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(parsed.record_type, 80)
        self.assertEqual(parsed["smf80evt"], 2)
        self.assertEqual(parsed["smf80evq"], 3)
        self.assertEqual(parsed.field_text("smf80usr"), "SECADM1")
        self.assertEqual(parsed.field_text("smf80grp"), "SYS1")
        self.assertEqual(parsed.field_text("smf80jbn"), "JOBNAME")

    def test_parse_record_requires_native_header_support(self) -> None:
        from pysmf import records

        with patch.object(records, "_native", None):
            with self.assertRaises(HeaderCatalogError):
                parse_record(standard_record(80))

    def test_parse_record_reports_missing_structured_parser(self) -> None:
        from pysmf import records

        def parse_record_error(_record_type: int, _data: bytes) -> object:
            raise NotImplementedError("unsupported SMF type")

        native = SimpleNamespace(parse_record=parse_record_error)

        with patch.object(records, "_native", native):
            with self.assertRaises(HeaderCatalogError):
                parse_record(standard_record(81))

    def test_parse_record_maps_native_validation_errors(self) -> None:
        from pysmf import records

        def parse_record_error(_record_type: int, _data: bytes) -> object:
            raise ValueError("expected SMF record type 80")

        native = SimpleNamespace(parse_record=parse_record_error)

        with patch.object(records, "_native", native):
            with self.assertRaises(SMFParseError):
                parse_record(standard_record(80))


if __name__ == "__main__":
    unittest.main()
