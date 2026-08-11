from __future__ import annotations

import os
import unittest
from collections import Counter
from importlib import import_module
from typing import ClassVar

from pysmf import StructuredSMFRecord, read_structured_dataset


ZOS_DATASET_ENV = "PYSMF_ZOS_DATASET"
ZOS_EXPECTED_RECORD_TYPES_ENV = "PYSMF_ZOS_EXPECTED_RECORD_TYPES"
ZOS_MIN_RECORD_TYPES_ENV = "PYSMF_ZOS_MIN_RECORD_TYPES"
ZOS_RECORD_LIMIT_ENV = "PYSMF_ZOS_RECORD_LIMIT"


def expected_record_types() -> set[int]:
    configured = os.environ.get(ZOS_EXPECTED_RECORD_TYPES_ENV, "")
    return {int(value) for value in configured.replace(",", " ").split()}


class ZOSSmokeTests(unittest.TestCase):
    sample_key: ClassVar[tuple[str, int] | None] = None
    sample_records: ClassVar[tuple[StructuredSMFRecord, ...] | None] = None

    def setUp(self) -> None:
        dataset_name = os.environ.get(ZOS_DATASET_ENV)
        if not dataset_name:
            self.skipTest(f"set {ZOS_DATASET_ENV} to run z/OS dataset smoke tests")
        self.dataset_name = dataset_name
        self.record_limit = int(os.environ.get(ZOS_RECORD_LIMIT_ENV, "1000"))
        self.min_record_types = int(os.environ.get(ZOS_MIN_RECORD_TYPES_ENV, "5"))

    @property
    def records(self) -> tuple[StructuredSMFRecord, ...]:
        sample_key = (self.dataset_name, self.record_limit)
        if ZOSSmokeTests.sample_key != sample_key:
            ZOSSmokeTests.sample_key = sample_key
            ZOSSmokeTests.sample_records = None
        if ZOSSmokeTests.sample_records is None:
            ZOSSmokeTests.sample_records = tuple(
                read_structured_dataset(
                    self.dataset_name,
                    records=self.record_limit,
                    errors="skip",
                )
            )
        return ZOSSmokeTests.sample_records

    def records_of_type(self, record_type: int) -> tuple[StructuredSMFRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.record_type == record_type
        )

    def test_native_extension_is_available(self) -> None:
        from pysmf import records

        self.assertIsNotNone(records._native)
        self.assertIsNotNone(records._native_parse_record)

    def test_compiled_header_manifest_has_real_header_coverage(self) -> None:
        try:
            compiled_headers_module = import_module("pysmf._compiled_headers")
        except ImportError:
            self.skipTest("compiled header manifest is not available")

        compiled_headers = tuple(compiled_headers_module.HEADERS)
        self.assertTrue(compiled_headers, "expected compiled z/OS header manifest")
        self.assertTrue(
            any(header["generic"] for header in compiled_headers),
            "expected at least one generic SMF header",
        )
        compiled_record_types = {
            record_type
            for header in compiled_headers
            for record_type in header["record_types"]
        }
        self.assertGreaterEqual(len(compiled_record_types), 20)

    def test_real_dataset_structured_records_parse(self) -> None:
        records = self.records

        self.assertTrue(records, "expected at least one structured SMF record")
        record_types = Counter(record.record_type for record in records)
        self.assertGreater(record_types.total(), 0)

    def test_real_dataset_observes_broad_record_mix(self) -> None:
        record_types = {record.record_type for record in self.records}
        self.assertGreaterEqual(
            len(record_types),
            self.min_record_types,
            f"expected at least {self.min_record_types} record types",
        )

    def test_real_dataset_expected_record_types_are_present(self) -> None:
        expected = expected_record_types()
        if not expected:
            self.skipTest(f"set {ZOS_EXPECTED_RECORD_TYPES_ENV} to enforce coverage")

        observed = {record.record_type for record in self.records}
        self.assertFalse(
            expected - observed,
            f"missing record types: {expected - observed}",
        )

    def test_real_dataset_fixed_header_fields_are_plausible(self) -> None:
        for record in self.records:
            prefix = f"smf{record.record_type}"
            type_field = f"{prefix}rty"
            fields = record.fields
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertTrue(fields, "expected parsed fields")
                if type_field in fields:
                    self.assertEqual(fields[type_field], record.record_type)
                length_field = f"{prefix}len"
                if length_field in fields and record.header is not None:
                    self.assertEqual(fields[length_field], record.header.length)
                self.assertFalse(
                    record.sections and "relocate_sections" in fields,
                    "section internals should not leak into scalar fields",
                )

    def test_real_dataset_field_richness_by_record_type(self) -> None:
        field_counts_by_type: dict[int, list[int]] = {}
        for record in self.records:
            field_counts_by_type.setdefault(record.record_type, []).append(
                len(record.fields)
            )

        for record_type, field_counts in field_counts_by_type.items():
            with self.subTest(record_type=record_type):
                self.assertGreaterEqual(max(field_counts), 4)

    def test_real_dataset_scalar_fields_keep_record_prefixes(self) -> None:
        for record in self.records:
            prefix = f"smf{record.record_type}"
            for field_name in record.fields:
                with self.subTest(record_type=record.record_type, field=field_name):
                    self.assertTrue(field_name.startswith(prefix), field_name)

    def test_real_dataset_sections_are_bounded(self) -> None:
        for record in self.records:
            record_length = record.header.length if record.header is not None else None
            for section in (*record.sections, *record.extended_sections):
                with self.subTest(
                    record_type=record.record_type,
                    offset=section.offset,
                ):
                    self.assertIsInstance(section.data_type, int)
                    self.assertIsInstance(section.offset, int)
                    self.assertIsInstance(section.data, bytes)
                    if record_length is not None:
                        self.assertLessEqual(section.offset, record_length)
                        self.assertLessEqual(
                            section.offset + len(section.data),
                            record_length,
                        )

    def test_real_dataset_text_helpers_do_not_fail(self) -> None:
        for record in self.records:
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertIsInstance(record.decoded_fields(), dict)
                self.assertIsInstance(record.decoded_texts(), tuple)

    def test_recent_generator_features_remain_available_when_present(self) -> None:
        checks = {
            90: ("smf90rty",),
            98: ("smf98len", "smf98rty", "smf98sty"),
            1154: ("smf1154len",),
        }
        for record_type, required_fields in checks.items():
            for record in self.records_of_type(record_type):
                with self.subTest(record_type=record_type, offset=record.offset):
                    for field_name in required_fields:
                        self.assertIn(field_name, record.fields)

    def test_real_type80_records_keep_racf_event_fields(self) -> None:
        type80_records = self.records_of_type(80)
        if not type80_records:
            self.skipTest("dataset sample did not include parsed SMF type 80 records")

        for record in type80_records:
            with self.subTest(offset=record.offset):
                for field_name in ("smf80evt", "smf80evq", "smf80des"):
                    self.assertIn(field_name, record.fields)

    def test_real_type90_records_have_fixed_or_adjacent_triplet_fields(self) -> None:
        type90_records = self.records_of_type(90)
        if not type90_records:
            self.skipTest("dataset sample did not include parsed SMF type 90 records")

        for record in type90_records:
            with self.subTest(offset=record.offset, subtype=record.subtype):
                self.assertIn("smf90rty", record.fields)
                if "smf90pof" in record.fields:
                    self.assertIn("smf90pln", record.fields)
                    self.assertIn("smf90pon", record.fields)

    def test_real_type98_records_have_sds_header_fields(self) -> None:
        type98_records = self.records_of_type(98)
        if not type98_records:
            self.skipTest("dataset sample did not include parsed SMF type 98 records")

        for record in type98_records:
            with self.subTest(offset=record.offset, subtype=record.subtype):
                for field_name in ("smf98len", "smf98rty", "smf98sty"):
                    self.assertIn(field_name, record.fields)
                if "smf98sdstripletsnum" in record.fields:
                    self.assertIsInstance(record.fields["smf98sdstripletsnum"], int)

    def test_real_type1154_records_have_common_triplet_fields(self) -> None:
        type1154_records = self.records_of_type(1154)
        if not type1154_records:
            self.skipTest("dataset sample did not include parsed SMF type 1154 records")

        for record in type1154_records:
            with self.subTest(offset=record.offset, subtype=record.subtype):
                self.assertIn("smf1154len", record.fields)
                if "smf1154_c_offset" in record.fields:
                    self.assertIn("smf1154_c_userid", record.fields)
                    self.assertIn("smf1154_c_jobname", record.fields)

    def test_real_type83_records_keep_fixed_header_layout(self) -> None:
        type83_records = self.records_of_type(83)
        if not type83_records:
            self.skipTest("dataset sample did not include parsed SMF type 83 records")

        for record in type83_records:
            with self.subTest(offset=record.offset, subtype=record.subtype):
                for field_name in (
                    "smf83len",
                    "smf83seg",
                    "smf83flg",
                    "smf83rty",
                    "smf83tme",
                    "smf83dte",
                    "smf83sid",
                    "smf83df1",
                ):
                    self.assertIn(field_name, record.fields)
                if record.subtype is None:
                    self.assertNotIn("smf83typ", record.fields)
                if "smf83typ" in record.fields:
                    self.assertEqual(record.fields["smf83typ"], 1)
                    self.assertIn("smf83trp", record.fields)
                    self.assertEqual(record.fields["smf83trp"], 3)
                if "smf83evt" in record.fields:
                    self.assertIn("smf83evq", record.fields)


if __name__ == "__main__":
    unittest.main()
