from __future__ import annotations

from io import BytesIO
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from smf_parser import HeaderCatalog, HeaderCatalogError, SMFParseError, parse_header, read_records


def ebcdic(value: str) -> bytes:
    return value.encode("cp037")


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
    with TemporaryDirectory() as include_dir:
        lines = [f"/* SMF record type {record_type} */" for record_type in record_types]
        lines.append("struct smfrcd_fixture { int smf_len; };\n")
        Path(include_dir, "ifasmfr.h").write_text("\n".join(lines), encoding="utf-8")
        return HeaderCatalog.discover(include_dir)


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
        with TemporaryDirectory() as include_dir:
            Path(include_dir, "ifasmfh.h").write_text(
                "/* SMF record type 92 */\nstruct smfhdr { int smfhdr_len; };\n",
                encoding="utf-8",
            )

            catalog = HeaderCatalog.discover(include_dir)

        self.assertIsNotNone(catalog.by_name("ifasmfh"))
        self.assertIn("smfhdr", catalog.by_name("ifasmfh").structs)
        self.assertTrue(any(header.name == "ifasmfh.h" for header in catalog.for_record_type(92)))


if __name__ == "__main__":
    unittest.main()
