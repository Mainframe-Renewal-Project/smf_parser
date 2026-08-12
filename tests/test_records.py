from __future__ import annotations

import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from pysmf import (
    SMFParseError,
    SMFRecordTypeSupportError,
    parse_record,
    parse_records,
    read_structured_records,
)
from tests.helpers import ebcdic, record_type_registry, standard_record


def native_type80_fields() -> dict[str, object]:
    return {
        "smf80des": 1,
        "smf80rty": 80,
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
        "smf80mix": ebcdic("USER123") + b"\x00\xff",
        "smf80bin": ebcdic("IEFPROC A B C D E F G H"),
        "smf80ver": 8,
        "smf80re2": 9,
        "smf80vrm": ebcdic("7700"),
        "smf80sec": ebcdic("SECLAB  "),
        "smf80rl2": 140,
        "smf80ct2": 1,
        "smf80au2": 10,
        "relocate_sections": [
            {"data_type": 1, "offset": 104, "data": ebcdic("ALTUSER")},
            {"data_type": 2, "offset": 113, "data": ebcdic("SECADM1")},
        ],
        "extended_relocate_sections": [
            {"data_type": 257, "offset": 140, "data": ebcdic("PERMIT")},
        ],
    }


class StructuredRecordTests(unittest.TestCase):
    def test_parse_record_passes_full_record_to_generated_native_parser(self) -> None:
        from pysmf import records

        calls = []
        body = b"type-specific-data"
        smf_record = standard_record(80, body=body)

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            calls.append((record_type, data))
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parse_record(smf_record)

        self.assertEqual(calls, [(80, smf_record)])

    def test_parse_record_uses_generated_native_parser(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(parsed.record_type, 80)
        self.assertIsNone(parsed.source)
        self.assertIsNone(parsed.header)
        self.assertIsNone(parsed.offset)
        self.assertIsNone(parsed.subtype)
        self.assertEqual(parsed["smf80evt"], 2)
        self.assertEqual(parsed["smf80evq"], 3)
        self.assertEqual(parsed["smf80usr"], "SECADM1")
        self.assertEqual(parsed.raw_fields["smf80usr"], ebcdic("SECADM1 "))
        self.assertEqual(parsed.field_text("smf80usr"), "SECADM1")
        self.assertEqual(parsed.field_text("smf80grp"), "SYS1")
        self.assertEqual(parsed.field_text("smf80jbn"), "JOBNAME")

    def test_parse_record_uses_native_structured_field_normalizer(self) -> None:
        from pysmf import records

        calls: list[str] = []

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            calls.append("parse")
            return native_type80_fields()

        def structured_fields(
            fields: dict[str, object],
        ) -> tuple[
            dict[str, int | bytes | str],
            dict[str, int | bytes],
            tuple[tuple[int, bytes, int], ...],
            tuple[tuple[int, bytes, int], ...],
        ]:
            calls.append("normalize")
            self.assertIn("smf80usr", fields)
            return (
                {"smf80rty": 80, "smf80usr": "SECADM1"},
                {"smf80rty": 80, "smf80usr": ebcdic("SECADM1 ")},
                ((1, ebcdic("ALTUSER"), 104),),
                ((257, ebcdic("PERMIT"), 140),),
            )

        native = SimpleNamespace(
            parse_record=parse_native_record,
            structured_fields=structured_fields,
        )

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(calls, ["parse", "normalize"])
        self.assertEqual(parsed["smf80usr"], "SECADM1")
        self.assertEqual(parsed.raw_fields["smf80usr"], ebcdic("SECADM1 "))
        self.assertEqual(parsed.sections[0].text, "ALTUSER")
        self.assertEqual(parsed.extended_sections[0].text, "PERMIT")

    def test_parse_record_exposes_decoded_text_helpers(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(parsed.clean_field_text("smf80mix"), "USER123")
        self.assertEqual(parsed.decoded_fields()["smf80usr"], "SECADM1")
        decoded = parsed.decoded_texts()
        self.assertIn("JOBNAME", decoded)
        self.assertIn("ALTUSER", decoded)
        self.assertIn("PERMIT", decoded)
        self.assertNotIn("smf80bin", parsed.decoded_fields())

    def test_decoded_text_helpers_use_native_extension_when_available(self) -> None:
        from pysmf import records

        calls: list[str] = []

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        def clean_decoded_text(value: str) -> str:
            calls.append("clean")
            return " ".join(value.strip().split())

        def clean_ebcdic_text(data: bytes) -> str:
            calls.append("ebcdic")
            del data
            return "USER123"

        def decoded_tokens(
            text: str, *, min_length: int = 2, max_length: int = 64
        ) -> tuple[str, ...]:
            calls.append("tokens")
            del min_length, max_length
            return (text.upper(),)

        def text_matches(
            text: str, value: str, *, ignore_case: bool = True, token: bool = False
        ) -> bool:
            calls.append("matches")
            del ignore_case, token
            return value.upper() in text.upper()

        def is_plausible_fixed_text(text: str) -> bool:
            calls.append("plausible")
            return text != "IEFPROC A B C D E F G H"

        native = SimpleNamespace(
            parse_record=parse_native_record,
            clean_decoded_text=clean_decoded_text,
            clean_ebcdic_text=clean_ebcdic_text,
            is_plausible_fixed_text=is_plausible_fixed_text,
            decoded_tokens=decoded_tokens,
            text_matches=text_matches,
        )

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))
            parsed.clean_field_text("smf80usr")
            parsed.decoded_tokens()
            parsed.find_text("USER123")

        self.assertIn("ebcdic", calls)
        self.assertIn("clean", calls)
        self.assertIn("plausible", calls)
        self.assertIn("tokens", calls)
        self.assertIn("matches", calls)

    def test_parse_record_can_find_decoded_user_tokens(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(
            parsed.find_text("USER123", token=True),
            ("USER123",),
        )
        self.assertEqual(parsed.find_text("H091", token=True), ())

    def test_parse_record_exposes_decoded_tokens(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        tokens = set(parsed.decoded_tokens())

        self.assertIn("USER123", tokens)
        self.assertIn("ALTUSER", tokens)
        self.assertIn("PERMIT", tokens)
        self.assertNotIn("IEFPROC", tokens)

    def test_parse_record_exposes_smf80_relocation_sections(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = parse_record(standard_record(80))

        self.assertEqual(len(parsed.sections), 2)
        self.assertEqual(parsed.sections[0].data_type, 1)
        self.assertEqual(parsed.sections[0].offset, 104)
        self.assertEqual(parsed.sections[0].text, "ALTUSER")
        self.assertEqual(parsed.sections[1].data_type, 2)
        self.assertEqual(parsed.sections[1].text, "SECADM1")
        self.assertEqual(len(parsed.extended_sections), 1)
        self.assertEqual(parsed.extended_sections[0].data_type, 257)
        self.assertEqual(parsed.extended_sections[0].offset, 140)
        self.assertEqual(parsed.extended_sections[0].text, "PERMIT")

    def test_parse_records_can_skip_unsupported_records(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del data
            if record_type == 80:
                return native_type80_fields()
            raise NotImplementedError("unsupported SMF type")

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            parsed = tuple(
                parse_records(
                    [standard_record(81), standard_record(80)],
                    errors="skip",
                )
            )

        self.assertEqual([record.record_type for record in parsed], [80])

    def test_parse_records_rejects_unknown_error_mode(self) -> None:
        with self.assertRaises(ValueError):
            tuple(parse_records([], errors="ignore"))  # type: ignore[arg-type]

    def test_read_structured_records_reads_and_parses_records(self) -> None:
        from pysmf import records

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return native_type80_fields()

        native = SimpleNamespace(parse_record=parse_native_record)
        source = BytesIO(standard_record(80))

        with patch.object(records, "_native", native):
            parsed = tuple(
                read_structured_records(
                    source, record_type_registry=record_type_registry(80)
                )
            )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].record_type, 80)
        self.assertIsNotNone(parsed[0].source)
        self.assertIsNotNone(parsed[0].header)
        self.assertEqual(parsed[0].offset, 0)
        self.assertEqual(parsed[0].subtype, 0)
        self.assertEqual(parsed[0].system_id_text, "SYS1")
        self.assertEqual(parsed[0].subsystem_id_text, "SMF")
        self.assertEqual(parsed[0]["smf80usr"], "SECADM1")

    def test_parse_record_requires_native_header_support(self) -> None:
        from pysmf import records

        with patch.object(records, "_native", None):
            with self.assertRaises(SMFRecordTypeSupportError):
                parse_record(standard_record(80))

    def test_parse_record_reports_missing_structured_parser(self) -> None:
        from pysmf import records

        def parse_record_error(record_type: int, data: bytes) -> object:
            del record_type, data
            raise NotImplementedError("unsupported SMF type")

        native = SimpleNamespace(parse_record=parse_record_error)

        with patch.object(records, "_native", native):
            with self.assertRaises(SMFRecordTypeSupportError):
                parse_record(standard_record(81))

    def test_parse_record_maps_native_validation_errors(self) -> None:
        from pysmf import records

        def parse_record_error(record_type: int, data: bytes) -> object:
            del record_type, data
            raise ValueError("expected SMF record type 80")

        native = SimpleNamespace(parse_record=parse_record_error)

        with patch.object(records, "_native", native):
            with self.assertRaises(SMFParseError):
                parse_record(standard_record(80))

    def test_parse_record_rejects_shifted_native_fields(self) -> None:
        from pysmf import records

        fields = native_type80_fields()
        fields["smf80rty"] = 0

        def parse_native_record(record_type: int, data: bytes) -> dict[str, object]:
            del record_type, data
            return fields

        native = SimpleNamespace(parse_record=parse_native_record)

        with patch.object(records, "_native", native):
            with self.assertRaises(SMFParseError):
                parse_record(standard_record(80))


if __name__ == "__main__":
    unittest.main()
