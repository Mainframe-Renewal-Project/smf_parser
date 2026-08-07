from __future__ import annotations

import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from smf_parser import (
    HeaderCatalog,
    HeaderDefinition,
    TruncatedSMFRecord,
    ZOAUMissingError,
    read_dataset,
    read_dataset_records,
)

try:
    "".encode("cp1047")
except LookupError:
    EBCDIC_TEST_ENCODING = "cp037"
else:
    EBCDIC_TEST_ENCODING = "cp1047"


def ebcdic(value: str) -> bytes:
    return value.encode(EBCDIC_TEST_ENCODING)


def standard_record(
    record_type: int,
    *,
    subtype: int = 0,
    system_id: str = "SYS1",
    date: bytes = b"\x00\x20\x23\x1f",
    body: bytes = b"",
) -> bytes:
    length = 24 + len(body)
    return (
        struct.pack(
            ">HHBBi4s4s4sH",
            length,
            0,
            0x40,
            record_type,
            12_345,
            date,
            ebcdic(system_id),
            ebcdic("SMF "),
            subtype,
        )
        + body
    )


def false_record_candidate() -> bytes:
    length = 472
    header = struct.pack(
        ">HHBBi4s4s4sH",
        length,
        0,
        0x40,
        240,
        12_345,
        b"\x00\x20\x23\x1f",
        ebcdic(".131"),
        ebcdic(".88."),
        61944,
    )
    return header + (b"\0" * (length - len(header)))


def false_type_0_candidate() -> bytes:
    length = 208
    header = struct.pack(
        ">HHBBi4s4s4sH",
        length,
        0,
        0x40,
        0,
        12_345,
        b"\x00\x20\x23\x1f",
        ebcdic("DBRA"),
        ebcdic("SMF "),
        0,
    )
    return header + (b"\0" * (length - len(header)))


def unsupported_record_with_embedded_supported_candidate() -> bytes:
    embedded = standard_record(1, system_id="YCPU")
    body = (b"x" * 16) + embedded + (b"y" * 16)
    return standard_record(240, body=body)


def incomplete_record_with_embedded_supported_candidate() -> bytes:
    embedded = standard_record(1, system_id="YCPU")
    return struct.pack(">H", 32756) + (b"x" * 16) + embedded


def invalid_length_with_embedded_supported_candidate() -> bytes:
    embedded = standard_record(1, system_id="YCPU")
    return struct.pack(">H", 2) + (b"x" * 16) + embedded


def header_catalog(*record_types: int) -> HeaderCatalog:
    include_dir = Path("/compiled/zos")
    return HeaderCatalog(
        include_dir=include_dir,
        headers=(
            HeaderDefinition(name="ifasmfr.h", path=include_dir / "ifasmfr.h", record_types=record_types, generic=False),
        ),
    )


class DatasetReaderTests(unittest.TestCase):
    def test_reads_dataset_records_that_are_smf_records(self) -> None:
        records = list(read_dataset_records([standard_record(30, subtype=2)], header_catalog=header_catalog(30)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 30)
        self.assertEqual(records[0].subtype, 2)
        self.assertIsNone(records[0].rdw)
        self.assertEqual(records[0].c_headers[0].name, "ifasmfr.h")

    def test_reassembles_continuation_dataset_chunks_by_default(self) -> None:
        smf_record = standard_record(30, subtype=2, body=b"a" * 2000)

        records = list(read_dataset_records([smf_record[:1408], smf_record[1408:]], header_catalog=header_catalog(30)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 30)
        self.assertEqual(records[0].subtype, 2)
        self.assertEqual(records[0].data, smf_record)

    def test_does_not_merge_incomplete_chunks_with_new_smf_headers(self) -> None:
        first = standard_record(30, subtype=2, body=b"a" * 2000)[:1408]
        second = standard_record(30, subtype=3, body=b"b" * 2000)[:896]

        records = list(read_dataset_records([first, second], header_catalog=header_catalog(30)))

        self.assertEqual(records, [])

    def test_skips_zero_padding_before_aligned_smf_record(self) -> None:
        record = standard_record(30, subtype=2)
        chunks = [(b"\0" * 14) + record]

        records = list(read_dataset_records(chunks, header_catalog=header_catalog(30)))

        self.assertEqual([record.record_type for record in records], [30])
        self.assertEqual(records[0].offset, 14)

    def test_does_not_resynchronize_after_false_record_candidates(self) -> None:
        valid = standard_record(30, subtype=2)

        records = list(read_dataset_records([false_record_candidate() + valid], header_catalog=header_catalog(30)))

        self.assertEqual(records, [])

    def test_does_not_resynchronize_after_candidates_without_compiled_record_header(self) -> None:
        valid = standard_record(30, subtype=2)

        records = list(read_dataset_records([false_type_0_candidate() + valid], header_catalog=header_catalog(30)))

        self.assertEqual(records, [])

    def test_skips_payload_candidates_inside_unsupported_records(self) -> None:
        false = unsupported_record_with_embedded_supported_candidate()
        valid = standard_record(30, subtype=2)

        records = list(read_dataset_records([false + valid], header_catalog=header_catalog(1, 30)))

        self.assertEqual(records, [])

    def test_does_not_scan_inside_incomplete_records(self) -> None:
        records = list(
            read_dataset_records(
                [incomplete_record_with_embedded_supported_candidate()],
                header_catalog=header_catalog(1),
            )
        )

        self.assertEqual(records, [])

    def test_does_not_scan_after_invalid_nonzero_length(self) -> None:
        records = list(
            read_dataset_records(
                [invalid_length_with_embedded_supported_candidate()],
                header_catalog=header_catalog(1),
            )
        )

        self.assertEqual(records, [])

    def test_system_id_filter_skips_header_shaped_payload(self) -> None:
        false = standard_record(1, subtype=50372, system_id="YCPU", body=b"payload")
        valid = standard_record(30, subtype=2, system_id="DBRA")

        records = list(read_dataset_records([false + valid], header_catalog=header_catalog(30), system_ids={"DBRA"}))

        self.assertEqual(records, [])

    def test_skips_records_with_non_packed_decimal_smf_date(self) -> None:
        record = standard_record(30, subtype=2, date=ebcdic("YCPU"))

        records = list(read_dataset_records([record], header_catalog=header_catalog(30)))

        self.assertEqual(records, [])

    def test_reads_dataset_records_that_include_external_rdw(self) -> None:
        smf_record = standard_record(14, body=b"payload")
        dataset_record = struct.pack(">HH", len(smf_record) + 4, 0) + smf_record

        records = list(read_dataset_records([dataset_record], header_catalog=header_catalog(14)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 14)
        self.assertEqual(records[0].body, b"payload")
        self.assertIsNotNone(records[0].rdw)
        self.assertEqual(records[0].offset, 4)

    def test_skips_short_dataset_records_by_default(self) -> None:
        records = list(read_dataset_records([b"\0\0\0\0", standard_record(30)], header_catalog=header_catalog(30)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 30)
        self.assertEqual(records[0].offset, 4)

    def test_can_fail_on_short_dataset_records(self) -> None:
        with self.assertRaises(TruncatedSMFRecord):
            list(read_dataset_records([b"\0\0\0\0"], skip_short_records=False, header_catalog=header_catalog(30)))

    def test_read_dataset_uses_zoau_read_as_bytes_lazily(self) -> None:
        calls: list[tuple[str, int, int, bool]] = []

        def read_as_bytes(dataset_name: str, *, records: int, offset: int, tail: bool) -> list[bytes]:
            calls.append((dataset_name, records, offset, tail))
            return [standard_record(2, system_id="DBRA")]

        fake_datasets = SimpleNamespace(read_as_bytes=read_as_bytes)

        with patch("smf_parser.datasets.import_module", return_value=fake_datasets):
            parsed = list(
                read_dataset(
                    "USER.SMF.UNLOAD",
                    records=10,
                    offset=3,
                    tail=True,
                    header_catalog=header_catalog(2),
                    system_ids={"DBRA"},
                )
            )

        self.assertEqual([record.record_type for record in parsed], [2])
        self.assertEqual(calls, [("USER.SMF.UNLOAD", 10, 3, True)])

    def test_read_dataset_reports_missing_zoau(self) -> None:
        with (
            patch("smf_parser.datasets.import_module", side_effect=ImportError("no zoau")),
            self.assertRaises(ZOAUMissingError),
        ):
            list(read_dataset("USER.SMF.UNLOAD"))


if __name__ == "__main__":
    unittest.main()
