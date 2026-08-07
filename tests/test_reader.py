from __future__ import annotations

import struct
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from smf_parser import (
    HeaderCatalog,
    HeaderCatalogError,
    HeaderDefinition,
    SMFParseError,
    parse_header,
    read_records,
)

try:
    "".encode("cp1047")
except LookupError:
    EBCDIC_TEST_ENCODING = "cp037"
else:
    EBCDIC_TEST_ENCODING = "cp1047"


def ebcdic(value: str) -> bytes:
    return value.encode(EBCDIC_TEST_ENCODING)


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


def extended_v2_record(record_type: int, *, subtype: int = 0, body: bytes = b"") -> bytes:
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


def header_catalog(*record_types: int) -> HeaderCatalog:
    include_dir = Path("/compiled/zos")
    return HeaderCatalog(
        include_dir=include_dir,
        headers=(
            HeaderDefinition(name="ifasmfr.h", path=include_dir / "ifasmfr.h", record_types=record_types, generic=False),
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

    def test_parse_standard_header_without_subtype_flag(self) -> None:
        record = bytearray(standard_record(1, subtype=50374))
        record[4] = 0

        header = parse_header(record)

        self.assertEqual(header.record_type, 1)
        self.assertIsNone(header.subtype)
        self.assertFalse(header.has_subtype)

    def test_parse_header_uses_native_parser_when_available(self) -> None:
        from smf_parser import reader

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

        records = list(read_records(first + second, header_catalog=header_catalog(2, 30)))

        self.assertEqual([record.record_type for record in records], [2, 30])
        self.assertEqual(records[1].body, b"abc")
        self.assertIsNone(records[0].rdw)
        self.assertEqual(records[1].c_headers[0].name, "ifasmfr.h")

    def test_read_auto_external_rdw_records(self) -> None:
        record = standard_record(14, body=b"data")
        stream = struct.pack(">HH", len(record) + 4, 0) + record

        records = list(read_records(BytesIO(stream), header_catalog=header_catalog(14)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 14)
        self.assertEqual(records[0].offset, 4)
        self.assertIsNotNone(records[0].rdw)
        self.assertEqual(records[0].rdw.length, len(record) + 4)

    def test_reject_invalid_record_length(self) -> None:
        with self.assertRaises(SMFParseError):
            list(read_records(b"\0\x01\0\0", header_catalog=header_catalog(2)))

    def test_rejects_records_without_matching_c_header(self) -> None:
        with self.assertRaises(HeaderCatalogError):
            list(read_records(standard_record(30), header_catalog=header_catalog(2)))


class HeaderCatalogTests(unittest.TestCase):
    def test_discovers_retained_c_headers(self) -> None:
        include_dir = Path("/compiled/zos")
        definition = HeaderDefinition(
            name="ifasmfh.h",
            path=include_dir / "ifasmfh.h",
            record_types=(92,),
            generic=False,
        )
        with patch("smf_parser.headers._compiled_headers", return_value=(include_dir, (definition,))):
            catalog = HeaderCatalog.discover(include_dir)

        self.assertIsNotNone(catalog.by_name("ifasmfh"))
        self.assertTrue(any(header.name == "ifasmfh.h" for header in catalog.for_record_type(92)))

    def test_generic_headers_do_not_match_every_record_type(self) -> None:
        include_dir = Path("/compiled/zos")
        catalog = HeaderCatalog(
            include_dir=include_dir,
            headers=(
                HeaderDefinition(name="ifasmfh.h", path=include_dir / "ifasmfh.h", record_types=(), generic=True),
                HeaderDefinition(name="ifasmfr1.h", path=include_dir / "ifasmfr1.h", record_types=(1,), generic=False),
            ),
        )

        self.assertEqual(catalog.for_record_type(0), ())
        self.assertEqual(tuple(header.name for header in catalog.for_record_type(1)), ("ifasmfr1.h",))


if __name__ == "__main__":
    unittest.main()
