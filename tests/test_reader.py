from __future__ import annotations

import struct
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pysmf import (
    SMFParseError,
    SMFRecordTypeDefinition,
    SMFRecordTypeRegistry,
    SMFRecordTypeSupportError,
    parse_header,
    read_records,
)
from tests.helpers import ebcdic


def standard_record(record_type: int, *, subtype: int = 0, body: bytes = b"") -> bytes:
    length = 24 + len(body)
    return (
        struct.pack(
            ">HHBBi4s4s4sH",
            length,
            0,
            0x40,
            record_type,
            12_345,
            b"\x00\x20\x23\x1f",
            ebcdic("SYS1"),
            ebcdic("SMF "),
            subtype,
        )
        + body
    )


def extended_v2_record(
    record_type: int, *, subtype: int = 0, body: bytes = b""
) -> bytes:
    length = 92 + len(body)
    standard_header = struct.pack(
        ">HHBBi4s4s4sH",
        length,
        0,
        0x60,
        126,
        12_345,
        b"\x00\x20\x23\x1f",
        ebcdic("SYS1"),
        ebcdic("SMF "),
        subtype,
    )
    extended_header = struct.pack(
        ">HBB16s8sH2sI16s16s",
        68,
        2,
        0,
        b"\0" * 16,
        b"\0" * 8,
        record_type,
        b"\0" * 2,
        0,
        b"\0" * 16,
        b"\0" * 16,
    )
    return standard_header + extended_header + body


def record_type_registry(*record_types: int) -> SMFRecordTypeRegistry:
    include_dir = Path("/compiled/zos")
    return SMFRecordTypeRegistry(
        include_dir=include_dir,
        definitions=(
            SMFRecordTypeDefinition(
                name="ifasmfr.h",
                path=include_dir / "ifasmfr.h",
                record_types=record_types,
                generic=False,
            ),
        ),
    )


class ReaderTests(unittest.TestCase):
    def test_parse_standard_header(self) -> None:
        record = standard_record(30, subtype=5, body=b"payload")

        header = parse_header(record)

        self.assertEqual(header.length, len(record))
        self.assertEqual(header.record_type, 30)
        self.assertEqual(header.subtype, 5)
        self.assertEqual(header.system_id_text, "SYS1")
        self.assertEqual(header.subsystem_id_text, "SMF")
        self.assertEqual(header.header_length, 24)

    def test_parse_standard_header_decodes_packed_time(self) -> None:
        from pysmf import reader

        record = bytearray(standard_record(30, subtype=5))
        record[6:10] = b"\x01\x26\x21\x9f"

        with patch.object(reader, "_native", None):
            header = parse_header(record)

        self.assertEqual(header.time_hundredths, 518_190)
        self.assertEqual(header.system_id_text, "SYS1")

    def test_parse_date_first_header(self) -> None:
        from pysmf import reader

        length = 20
        record = struct.pack(
            ">HHBB4s4s4sH",
            length,
            0x0054,
            0x40,
            102,
            b"\x01\x26\x21\x9f",
            ebcdic("SYS1"),
            ebcdic("SMF "),
            7,
        )

        with patch.object(reader, "_native", None):
            header = parse_header(record)

        self.assertEqual(header.record_type, 102)
        self.assertEqual(header.date, b"\x01\x26\x21\x9f")
        self.assertEqual(header.system_id_text, "SYS1")
        self.assertEqual(header.subsystem_id_text, "SMF")
        self.assertEqual(header.subtype, 7)
        self.assertEqual(header.header_length, 20)

    def test_parse_standard_header_without_subtype_flag(self) -> None:
        record = bytearray(standard_record(1, subtype=50374))
        record[4] = 0

        header = parse_header(record)

        self.assertEqual(header.record_type, 1)
        self.assertIsNone(header.subtype)
        self.assertFalse(header.has_subtype)

    def test_parse_header_uses_native_parser_when_available(self) -> None:
        from pysmf import reader

        native = SimpleNamespace(
            parse_header=lambda data: (
                len(data),
                len(data),
                0,
                0x40,
                30,
                12_345,
                b"\x00\x20\x23\x1f",
                ebcdic("SYS1"),
                ebcdic("SMF "),
                5,
                24,
                None,
                None,
                None,
                None,
            )
        )

        with patch.object(reader, "_native", native):
            header = parse_header(standard_record(30, subtype=5))

        self.assertEqual(header.record_type, 30)
        self.assertEqual(header.subtype, 5)
        self.assertEqual(header.system_id_text, "SYS1")

    def test_decode_smf_time_uses_native_helper_when_available(self) -> None:
        from pysmf import reader

        def decode_smf_time_hundredths(data: bytes) -> int:
            self.assertEqual(data, b"\0\0\0\0")
            return 42

        native = SimpleNamespace(decode_smf_time_hundredths=decode_smf_time_hundredths)

        with patch.object(reader, "_native", native):
            self.assertEqual(reader.decode_smf_time_hundredths(b"\0\0\0\0"), 42)

    def test_is_packed_smf_date_uses_native_helper_when_available(self) -> None:
        from pysmf import reader

        native = SimpleNamespace(is_packed_smf_date=lambda data: data == b"date")

        with patch.object(reader, "_native", native):
            self.assertTrue(reader.is_packed_smf_date(b"date"))
            self.assertFalse(reader.is_packed_smf_date(b"nope"))

    def test_parse_extended_v2_header(self) -> None:
        record = extended_v2_record(1154, subtype=128, body=b"payload")

        header = parse_header(record)

        self.assertEqual(header.record_type_indicator, 126)
        self.assertEqual(header.record_type, 1154)
        self.assertEqual(header.extended_version, 2)
        self.assertEqual(header.extended_header_length, 68)
        self.assertEqual(header.header_length, 92)

    def test_read_auto_smf_records(self) -> None:
        first = standard_record(2)
        second = standard_record(30, subtype=4, body=b"abc")

        records = list(
            read_records(
                first + second, record_type_registry=record_type_registry(2, 30)
            )
        )

        self.assertEqual([record.record_type for record in records], [2, 30])
        self.assertEqual(records[1].body, b"abc")
        self.assertIsNone(records[0].rdw)
        self.assertEqual(records[1].record_type_definitions[0].name, "ifasmfr.h")

    def test_read_auto_external_rdw_records(self) -> None:
        record = standard_record(14, body=b"data")
        stream = struct.pack(">HH", len(record) + 4, 0) + record

        records = list(
            read_records(BytesIO(stream), record_type_registry=record_type_registry(14))
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 14)
        self.assertEqual(records[0].offset, 4)
        rdw = records[0].rdw
        assert rdw is not None
        self.assertEqual(rdw.length, len(record) + 4)

    def test_reject_invalid_record_length(self) -> None:
        with self.assertRaises(SMFParseError):
            list(
                read_records(
                    b"\0\x01\0\0", record_type_registry=record_type_registry(2)
                )
            )

    def test_rejects_records_without_matching_c_header(self) -> None:
        with self.assertRaises(SMFRecordTypeSupportError):
            list(
                read_records(
                    standard_record(30), record_type_registry=record_type_registry(2)
                )
            )


class SMFRecordTypeRegistryTests(unittest.TestCase):
    def test_discovers_retained_record_type_definitions(self) -> None:
        include_dir = Path("/compiled/zos")
        definition = SMFRecordTypeDefinition(
            name="ifasmfh.h",
            path=include_dir / "ifasmfh.h",
            record_types=(92,),
            generic=False,
        )
        with patch(
            "pysmf.headers._compiled_headers",
            return_value=(include_dir, (definition,)),
        ):
            catalog = SMFRecordTypeRegistry.discover(include_dir)

        self.assertIsNotNone(catalog.by_name("ifasmfh"))
        self.assertTrue(
            any(header.name == "ifasmfh.h" for header in catalog.for_record_type(92))
        )

    def test_finds_ibm_uppercase_extensionless_headers_by_logical_name(self) -> None:
        include_dir = Path("/usr/include/IBM")
        catalog = SMFRecordTypeRegistry(
            include_dir=include_dir,
            definitions=(
                SMFRecordTypeDefinition(
                    name="ifasmfr.h",
                    path=include_dir / "IFASMFR",
                    record_types=(),
                    generic=True,
                ),
            ),
        )

        self.assertIsNotNone(catalog.by_name("ifasmfr"))
        self.assertIsNotNone(catalog.by_name("ifasmfr.h"))
        self.assertIsNotNone(catalog.by_name("IFASMFR"))

    def test_generic_definitions_do_not_match_every_record_type(self) -> None:
        include_dir = Path("/compiled/zos")
        catalog = SMFRecordTypeRegistry(
            include_dir=include_dir,
            definitions=(
                SMFRecordTypeDefinition(
                    name="ifasmfh.h",
                    path=include_dir / "ifasmfh.h",
                    record_types=(),
                    generic=True,
                ),
                SMFRecordTypeDefinition(
                    name="ifasmfr1.h",
                    path=include_dir / "ifasmfr1.h",
                    record_types=(1,),
                    generic=False,
                ),
            ),
        )

        self.assertEqual(catalog.for_record_type(0), ())
        self.assertEqual(
            tuple(header.name for header in catalog.for_record_type(1)), ("ifasmfr1.h",)
        )


if __name__ == "__main__":
    unittest.main()
