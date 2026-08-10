from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pysmf import HeaderCatalogError, SMFParseError, parse_record
from tests.helpers import ebcdic, standard_record


def native_type80_fields() -> dict[str, object]:
    return {
        "descriptor_flags": 1,
        "event_code": 2,
        "event_qualifier": 3,
        "user_id": ebcdic("SECADM1 "),
        "group": ebcdic("SYS1    "),
        "relocate_offset": 104,
        "relocate_count": 1,
        "authority": 4,
        "reason": 5,
        "terminal_level": 6,
        "command_error": 7,
        "terminal_id": ebcdic("TERMID  "),
        "job_name": ebcdic("JOBNAME "),
        "reader_time_hundredths": 12_345,
        "reader_date": b"\x00\x20\x23\x1f",
        "user_identification": ebcdic("USERID  "),
        "version": 8,
        "reason2": 9,
        "racf_version": ebcdic("7700"),
        "seclabel": ebcdic("SECLAB  "),
        "extended_relocate_offset": 140,
        "extended_relocate_count": 1,
        "authority2": 10,
        "relocate_sections": [
            {"offset": 104, "data_type": 1, "data": ebcdic("ALTUSER")},
        ],
        "extended_relocate_sections": [
            {"offset": 140, "data_type": 1024, "data": ebcdic("PERMIT")},
        ],
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
        self.assertEqual(parsed["event_code"], 2)
        self.assertEqual(parsed["event_qualifier"], 3)
        self.assertEqual(parsed.field_text("user_id"), "SECADM1")
        self.assertEqual(parsed.field_text("group"), "SYS1")
        self.assertEqual(parsed.field_text("job_name"), "JOBNAME")
        self.assertEqual(parsed.sections[0].data_type, 1)
        self.assertEqual(parsed.sections[0].text, "ALTUSER")
        self.assertEqual(parsed.extended_sections[0].data_type, 1024)
        self.assertEqual(parsed.extended_sections[0].text, "PERMIT")

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
