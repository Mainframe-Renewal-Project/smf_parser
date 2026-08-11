from __future__ import annotations

import os
import struct
import unittest
from io import BytesIO
from collections import Counter
from collections.abc import Iterable
from importlib import import_module
from typing import ClassVar, cast

from pysmf import (
    SMFRecord,
    StructuredSMFRecord,
    parse_record,
    parse_records,
    read_dataset,
    read_records,
    read_structured_dataset,
    read_structured_records,
)


ZOS_DATASET_ENV = "PYSMF_ZOS_DATASET"
ZOS_EXPECTED_RECORD_TYPES_ENV = "PYSMF_ZOS_EXPECTED_RECORD_TYPES"
ZOS_MIN_RECORD_TYPES_ENV = "PYSMF_ZOS_MIN_RECORD_TYPES"
ZOS_RECORD_LIMIT_ENV = "PYSMF_ZOS_RECORD_LIMIT"


def expected_record_types() -> set[int]:
    configured = os.environ.get(ZOS_EXPECTED_RECORD_TYPES_ENV, "")
    return {int(value) for value in configured.replace(",", " ").split()}


def concrete_dataset_names(dataset_name: str) -> tuple[str, ...]:
    if dataset_name.startswith(("//", "DD:", "/")) or dataset_name.endswith(")"):
        return (dataset_name,)
    try:
        gdgs = import_module("zoautil_py.gdgs")
    except ImportError:
        return (dataset_name,)

    generation_data_group = gdgs.GenerationDataGroupView(dataset_name.upper())
    generations = generation_data_group.generations
    if callable(generations):
        generations = generations()
    generation_entries = cast(Iterable[object], generations)
    names = tuple(
        str(name)
        for generation in generation_entries
        if (name := getattr(generation, "name", None)) is not None
    )
    return names or (dataset_name,)


def structured_records(
    dataset_names: Iterable[str], *, record_limit: int
) -> tuple[StructuredSMFRecord, ...]:
    records: list[StructuredSMFRecord] = []
    for dataset_name in dataset_names:
        remaining = record_limit - len(records) if record_limit else 0
        if record_limit and remaining <= 0:
            break
        records.extend(
            read_structured_dataset(
                dataset_name,
                records=remaining,
                errors="skip",
            )
        )
    return tuple(records)


def raw_records(
    dataset_names: Iterable[str], *, record_limit: int
) -> tuple[SMFRecord, ...]:
    records: list[SMFRecord] = []
    for dataset_name in dataset_names:
        remaining = record_limit - len(records) if record_limit else 0
        if record_limit and remaining <= 0:
            break
        records.extend(read_dataset(dataset_name, records=remaining))
    return tuple(records)


def smf_stream(records: Iterable[SMFRecord]) -> bytes:
    return b"".join(record.data for record in records)


def rdw_stream(records: Iterable[SMFRecord]) -> bytes:
    return b"".join(
        struct.pack(">HH", len(record.data) + 4, 0) + record.data
        for record in records
    )


class ZOSSmokeTests(unittest.TestCase):
    sample_key: ClassVar[tuple[str, int] | None] = None
    sample_dataset_names: ClassVar[tuple[str, ...]] = ()
    sample_raw_records: ClassVar[tuple[SMFRecord, ...] | None] = None
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
            ZOSSmokeTests.sample_dataset_names = concrete_dataset_names(
                self.dataset_name
            )
            ZOSSmokeTests.sample_raw_records = None
            ZOSSmokeTests.sample_records = None
        if ZOSSmokeTests.sample_records is None:
            ZOSSmokeTests.sample_records = structured_records(
                ZOSSmokeTests.sample_dataset_names,
                record_limit=self.record_limit,
            )
        return ZOSSmokeTests.sample_records

    @property
    def dataset_names(self) -> tuple[str, ...]:
        if ZOSSmokeTests.sample_key != (self.dataset_name, self.record_limit):
            _ = self.records
        return ZOSSmokeTests.sample_dataset_names

    @property
    def raw_records(self) -> tuple[SMFRecord, ...]:
        if ZOSSmokeTests.sample_key != (self.dataset_name, self.record_limit):
            _ = self.records
        if ZOSSmokeTests.sample_raw_records is None:
            ZOSSmokeTests.sample_raw_records = raw_records(
                ZOSSmokeTests.sample_dataset_names,
                record_limit=self.record_limit,
            )
        return ZOSSmokeTests.sample_raw_records

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

        self.assertTrue(
            records,
            "expected at least one structured SMF record from "
            f"{', '.join(self.dataset_names)}",
        )
        record_types = Counter(record.record_type for record in records)
        self.assertGreater(record_types.total(), 0)

    def test_read_dataset_returns_raw_records_with_metadata(self) -> None:
        records = self.raw_records

        self.assertTrue(
            records,
            "expected at least one raw SMF record from "
            f"{', '.join(self.dataset_names)}",
        )
        for record in records[:25]:
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertIsInstance(record.data, bytes)
                self.assertEqual(record.header.record_type, record.record_type)
                self.assertEqual(
                    record.data[:2],
                    record.header.length.to_bytes(2, "big"),
                )
                self.assertIsInstance(record.header.system_id_text, str)

    def test_structured_dataset_matches_parse_records(self) -> None:
        raw_records = self.raw_records[:25]
        if not raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        structured_from_parse = tuple(parse_records(raw_records, errors="skip"))
        self.assertTrue(structured_from_parse)
        self.assertEqual(
            [record.record_type for record in structured_from_parse],
            [
                record.record_type
                for record in self.records[: len(structured_from_parse)]
            ],
        )

    def test_parse_record_accepts_one_raw_record(self) -> None:
        if not self.raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        structured = parse_record(self.raw_records[0])
        self.assertEqual(structured.record_type, self.raw_records[0].record_type)
        self.assertIs(structured.source, self.raw_records[0])

    def test_read_records_supports_smf_and_rdw_binary_forms(self) -> None:
        raw_records = self.raw_records[:10]
        if not raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        parsed_smf = tuple(read_records(BytesIO(smf_stream(raw_records))))
        parsed_rdw = tuple(
            read_records(BytesIO(rdw_stream(raw_records)), record_format="rdw")
        )

        self.assertEqual(
            [record.record_type for record in parsed_smf],
            [record.record_type for record in raw_records],
        )
        self.assertEqual(
            [record.record_type for record in parsed_rdw],
            [record.record_type for record in raw_records],
        )

    def test_read_structured_records_supports_binary_streams(self) -> None:
        raw_records = self.raw_records[:10]
        if not raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        structured = tuple(
            read_structured_records(BytesIO(smf_stream(raw_records)), errors="skip")
        )

        self.assertTrue(structured)
        self.assertEqual(
            [record.record_type for record in structured],
            [record.record_type for record in raw_records[: len(structured)]],
        )

    def test_record_type_filter_limits_raw_dataset_results(self) -> None:
        if not self.raw_records:
            self.skipTest("dataset sample did not include raw SMF records")
        selected_type = self.raw_records[0].record_type

        filtered = tuple(
            read_dataset(
                self.dataset_names[0],
                record_types={selected_type},
                records=self.record_limit,
            )
        )

        self.assertTrue(filtered)
        self.assertEqual({record.record_type for record in filtered}, {selected_type})

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

    def test_structured_record_metadata_helpers_are_populated(self) -> None:
        for record in self.records:
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertIsNotNone(record.source)
                self.assertIsNotNone(record.header)
                self.assertIsInstance(record.offset, int)
                self.assertIsInstance(record.system_id_text, str)
                self.assertIsInstance(record.subsystem_id_text, str)

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
