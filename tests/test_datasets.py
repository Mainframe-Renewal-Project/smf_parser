from __future__ import annotations

from types import SimpleNamespace
import struct
import unittest
from unittest.mock import patch

from smf_parser import TruncatedSMFRecord, ZOAUMissingError, read_dataset, read_dataset_records


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


class DatasetReaderTests(unittest.TestCase):
    def test_reads_dataset_records_that_are_smf_records(self) -> None:
        records = list(read_dataset_records([standard_record(30, subtype=2)]))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 30)
        self.assertEqual(records[0].subtype, 2)
        self.assertIsNone(records[0].rdw)

    def test_reads_dataset_records_that_include_external_rdw(self) -> None:
        smf_record = standard_record(14, body=b"payload")
        dataset_record = struct.pack(">HH", len(smf_record) + 4, 0) + smf_record

        records = list(read_dataset_records([dataset_record]))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 14)
        self.assertEqual(records[0].body, b"payload")
        self.assertIsNotNone(records[0].rdw)
        self.assertEqual(records[0].offset, 4)

    def test_skips_short_dataset_records_by_default(self) -> None:
        records = list(read_dataset_records([b"\0\0\0\0", standard_record(30)]))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_type, 30)
        self.assertEqual(records[0].offset, 4)

    def test_can_fail_on_short_dataset_records(self) -> None:
        with self.assertRaises(TruncatedSMFRecord):
            list(read_dataset_records([b"\0\0\0\0"], skip_short_records=False))

    def test_read_dataset_uses_zoau_read_as_bytes_lazily(self) -> None:
        calls: list[tuple[str, int, int, bool]] = []

        def read_as_bytes(dataset_name: str, *, records: int, offset: int, tail: bool) -> list[bytes]:
            calls.append((dataset_name, records, offset, tail))
            return [standard_record(2)]

        fake_datasets = SimpleNamespace(read_as_bytes=read_as_bytes)

        with patch("smf_parser.datasets.import_module", return_value=fake_datasets):
            parsed = list(read_dataset("USER.SMF.UNLOAD", records=10, offset=3, tail=True))

        self.assertEqual([record.record_type for record in parsed], [2])
        self.assertEqual(calls, [("USER.SMF.UNLOAD", 10, 3, True)])

    def test_read_dataset_reports_missing_zoau(self) -> None:
        with patch("smf_parser.datasets.import_module", side_effect=ImportError("no zoau")):
            with self.assertRaises(ZOAUMissingError):
                list(read_dataset("USER.SMF.UNLOAD"))


if __name__ == "__main__":
    unittest.main()
