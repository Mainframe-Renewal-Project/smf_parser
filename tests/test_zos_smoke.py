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


def normalized_smf_length(value: int) -> int:
    return value & 0x7FFF


def normalized_field_length(value: object) -> int | None:
    if not isinstance(value, int):
        return None
    return value & 0xFFFF & 0x7FFF


def is_expected_header_field_name(record_type: int, field_name: str) -> bool:
    return field_name.lower().startswith(f"smf{record_type}") or "_dummy_" in field_name


def section_signature(
    record: StructuredSMFRecord,
) -> tuple[tuple[int, int, bytes], ...]:
    return tuple(
        (section.data_type, section.offset, section.data)
        for section in (*record.sections, *record.extended_sections)
    )


def structured_output_signature(record: StructuredSMFRecord) -> tuple[object, ...]:
    return (
        record.record_type,
        record.subtype,
        record.fields,
        record.raw_fields,
        section_signature(record),
    )


def assert_decoded_field_is_searchable(
    test_case: unittest.TestCase,
    record: StructuredSMFRecord,
    field_name: str,
) -> bool:
    if field_name not in record.fields:
        return False
    test_case.assertIsInstance(record.raw_fields[field_name], bytes)
    text = record.field_text(field_name)
    clean_text = record.clean_field_text(field_name)
    test_case.assertIsInstance(text, str)
    test_case.assertIsInstance(clean_text, str)
    decoded_fields = record.decoded_fields()
    if field_name not in decoded_fields:
        return False
    test_case.assertEqual(decoded_fields[field_name], clean_text)
    test_case.assertIn(clean_text, record.decoded_texts())
    test_case.assertTrue(record.find_text(clean_text))
    return True


def assert_non_negative_int_field(
    test_case: unittest.TestCase,
    record: StructuredSMFRecord,
    field_name: str,
) -> int:
    value = record.fields[field_name]
    test_case.assertIsInstance(value, int)
    value = cast(int, value)
    test_case.assertGreaterEqual(value, 0)
    test_case.assertEqual(record.raw_fields[field_name], value)
    return value


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

    def structured_record_type_is_present(self, record_type: int) -> bool:
        if self.records_of_type(record_type):
            return True
        return any(
            read_structured_dataset(
                dataset_name,
                record_types={record_type},
                records=self.record_limit,
                errors="skip",
            )
            for dataset_name in self.dataset_names
        )

    def raw_records_of_type(self, record_type: int) -> tuple[SMFRecord, ...]:
        records: list[SMFRecord] = []
        for dataset_name in self.dataset_names:
            records.extend(
                read_dataset(
                    dataset_name,
                    record_types={record_type},
                    records=self.record_limit,
                )
            )
            if records:
                break
        return tuple(records)

    def structured_records_of_type(
        self, record_type: int
    ) -> tuple[StructuredSMFRecord, ...]:
        records: list[StructuredSMFRecord] = []
        for dataset_name in self.dataset_names:
            records.extend(
                read_structured_dataset(
                    dataset_name,
                    record_types={record_type},
                    records=self.record_limit,
                    errors="skip",
                )
            )
            if records:
                break
        return tuple(records)

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
                    record.header.raw_length.to_bytes(2, "big"),
                )
                self.assertEqual(
                    normalized_smf_length(record.header.raw_length),
                    record.header.length,
                )
                self.assertIsInstance(record.header.system_id_text, str)

    def test_structured_dataset_matches_parse_records(self) -> None:
        raw_records = self.raw_records[:25]
        if not raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        structured_from_parse = tuple(parse_records(raw_records, errors="skip"))
        structured_from_dataset = self.records[: len(structured_from_parse)]
        self.assertTrue(structured_from_parse)
        self.assertEqual(
            [structured_output_signature(record) for record in structured_from_parse],
            [structured_output_signature(record) for record in structured_from_dataset],
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

        parsed_smf = tuple(
            read_records(BytesIO(smf_stream(raw_records)), record_format="smf")
        )
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
        for raw_record, smf_record, rdw_record in zip(
            raw_records, parsed_smf, parsed_rdw, strict=True
        ):
            with self.subTest(record_type=raw_record.record_type):
                self.assertEqual(smf_record.data, raw_record.data)
                self.assertIsNone(smf_record.rdw)
                self.assertEqual(rdw_record.data, raw_record.data)
                self.assertIsNotNone(rdw_record.rdw)
                assert rdw_record.rdw is not None
                self.assertEqual(rdw_record.rdw.length, len(raw_record.data) + 4)
                self.assertEqual(rdw_record.rdw.segment_descriptor, 0)
                self.assertEqual(
                    rdw_record.header.raw_length,
                    raw_record.header.raw_length,
                )

    def test_read_structured_records_supports_binary_streams(self) -> None:
        raw_records = self.raw_records[:10]
        if not raw_records:
            self.skipTest("dataset sample did not include raw SMF records")

        structured = tuple(
            read_structured_records(
                BytesIO(smf_stream(raw_records)),
                record_format="smf",
                errors="skip",
            )
        )
        expected = tuple(parse_records(raw_records, errors="skip"))

        self.assertTrue(structured)
        self.assertEqual(
            [structured_output_signature(record) for record in structured],
            [structured_output_signature(record) for record in expected],
        )

    def test_parse_record_from_bytes_matches_source_record_output(self) -> None:
        for record in self.records[:25]:
            self.assertIsNotNone(record.source)
            assert record.source is not None
            parsed_from_bytes = parse_record(record.source.data)
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertIsNone(parsed_from_bytes.source)
                self.assertEqual(parsed_from_bytes.record_type, record.record_type)
                self.assertEqual(parsed_from_bytes.fields, record.fields)
                self.assertEqual(parsed_from_bytes.raw_fields, record.raw_fields)
                self.assertEqual(
                    section_signature(parsed_from_bytes),
                    section_signature(record),
                )

    def test_dataset_system_id_filter_limits_raw_results(self) -> None:
        if not self.raw_records:
            self.skipTest("dataset sample did not include raw SMF records")
        selected_system_id = self.raw_records[0].header.system_id_text

        filtered: list[SMFRecord] = []
        for dataset_name in self.dataset_names:
            filtered.extend(
                read_dataset(
                    dataset_name,
                    system_ids={selected_system_id},
                    records=self.record_limit,
                )
            )
            if filtered:
                break

        self.assertTrue(filtered)
        self.assertEqual(
            {record.header.system_id_text for record in filtered},
            {selected_system_id},
        )

    def test_structured_record_type_filter_preserves_deep_output(self) -> None:
        selected_type = next(iter({record.record_type for record in self.records}))

        structured = self.structured_records_of_type(selected_type)
        raw = self.raw_records_of_type(selected_type)
        expected = tuple(parse_records(raw, errors="skip"))

        self.assertTrue(structured)
        self.assertEqual({record.record_type for record in structured}, {selected_type})
        self.assertEqual(
            [structured_output_signature(record) for record in structured],
            [structured_output_signature(record) for record in expected],
        )

    def test_structured_records_expose_consistent_scalar_outputs(self) -> None:
        saw_text_field = False
        saw_bytes_field = False
        saw_int_field = False

        for record in self.records:
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertEqual(set(record.raw_fields), set(record.fields))
                for field_name, value in record.fields.items():
                    self.assertEqual(record[field_name], value)
                    raw_value = record.raw_fields[field_name]
                    if isinstance(value, str):
                        saw_text_field = True
                        self.assertIsInstance(raw_value, bytes)
                        self.assertEqual(record.field_text(field_name), value)
                    elif isinstance(value, bytes):
                        saw_bytes_field = True
                        self.assertIsInstance(raw_value, bytes)
                        self.assertIsInstance(record.field_text(field_name), str)
                    else:
                        saw_int_field = True
                        self.assertIsInstance(raw_value, int)
                        with self.assertRaises(TypeError):
                            record.field_text(field_name)

        self.assertTrue(saw_text_field, "expected at least one decoded text field")
        self.assertTrue(saw_bytes_field, "expected at least one retained bytes field")
        self.assertTrue(saw_int_field, "expected at least one integer field")

    def test_decoded_output_helpers_return_searchable_content(self) -> None:
        decoded_records = [record for record in self.records if record.decoded_texts()]
        if not decoded_records:
            self.skipTest("dataset sample did not include decoded text output")

        for record in decoded_records[:25]:
            decoded_fields = record.decoded_fields()
            decoded_texts = record.decoded_texts()
            tokens = record.decoded_tokens(min_length=2)
            with self.subTest(record_type=record.record_type, offset=record.offset):
                self.assertTrue(decoded_texts)
                self.assertTrue(set(decoded_fields.values()).issubset(decoded_texts))
                if tokens:
                    self.assertTrue(record.find_text(tokens[0], token=True))
                    self.assertEqual(record.find_text(""), ())

    def test_structured_sections_match_source_record_bytes(self) -> None:
        records_with_sections = [
            record
            for record in self.records
            if record.sections or record.extended_sections
        ]
        if not records_with_sections:
            self.skipTest("dataset sample did not include structured sections")

        for record in records_with_sections[:25]:
            self.assertIsNotNone(record.source)
            assert record.source is not None
            for section in (*record.sections, *record.extended_sections):
                with self.subTest(
                    record_type=record.record_type,
                    offset=section.offset,
                ):
                    self.assertEqual(
                        section.data,
                        record.source.data[
                            section.offset : section.offset + len(section.data)
                        ],
                    )
                    self.assertIsInstance(section.text, str)
                    self.assertIsInstance(section.clean_text, str)

    def test_record_type_filter_limits_raw_dataset_results(self) -> None:
        if not self.raw_records:
            self.skipTest("dataset sample did not include raw SMF records")
        selected_type = self.raw_records[0].record_type

        filtered = self.raw_records_of_type(selected_type)

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
        missing = {
            record_type
            for record_type in expected - observed
            if not self.structured_record_type_is_present(record_type)
        }
        self.assertFalse(
            missing,
            f"missing record types: {missing}",
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
                    self.assertEqual(
                        normalized_field_length(fields[length_field]),
                        record.header.length,
                    )
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
            for field_name in record.fields:
                with self.subTest(record_type=record.record_type, field=field_name):
                    self.assertTrue(
                        is_expected_header_field_name(record.record_type, field_name),
                        field_name,
                    )

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
            119: ("SMF119HDType", "SMF119HDSubType"),
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

    def test_real_type80_racf_fields_are_decoded_and_searchable(self) -> None:
        type80_records = self.records_of_type(80)
        if not type80_records:
            self.skipTest("dataset sample did not include parsed SMF type 80 records")

        saw_decoded_identity = False
        for record in type80_records:
            with self.subTest(offset=record.offset):
                for field_name in ("smf80evt", "smf80evq", "smf80des"):
                    assert_non_negative_int_field(self, record, field_name)

                for field_name in ("smf80usr", "smf80grp", "smf80jbn", "smf80trm"):
                    if assert_decoded_field_is_searchable(self, record, field_name):
                        saw_decoded_identity = True

        if not saw_decoded_identity:
            self.skipTest("dataset sample did not include decoded RACF identity fields")

    def test_real_type83_security_fields_are_decoded_when_present(self) -> None:
        type83_records = self.records_of_type(83)
        if not type83_records:
            self.skipTest("dataset sample did not include parsed SMF type 83 records")

        saw_security_record = False
        saw_decoded_identity = False
        for record in type83_records:
            if "smf83typ" not in record.fields:
                continue
            saw_security_record = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                self.assertEqual(
                    assert_non_negative_int_field(self, record, "smf83typ"),
                    1,
                )
                self.assertEqual(
                    assert_non_negative_int_field(self, record, "smf83trp"),
                    3,
                )
                for field_name in ("smf83evt", "smf83evq"):
                    if field_name in record.fields:
                        assert_non_negative_int_field(self, record, field_name)
                for field_name in ("smf83usr", "smf83jbn"):
                    if assert_decoded_field_is_searchable(self, record, field_name):
                        saw_decoded_identity = True

        if not saw_security_record:
            self.skipTest(
                "dataset sample did not include SMF type 83 subtype 1 records"
            )
        if not saw_decoded_identity:
            self.skipTest("dataset sample did not include decoded SMF type 83 fields")

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

    def test_real_type90_adjacent_triplets_are_consistent_when_present(self) -> None:
        type90_records = self.records_of_type(90)
        if not type90_records:
            self.skipTest("dataset sample did not include parsed SMF type 90 records")

        saw_adjacent_triplet = False
        for record in type90_records:
            if "smf90pof" not in record.fields:
                continue
            saw_adjacent_triplet = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                offset = assert_non_negative_int_field(self, record, "smf90pof")
                length = assert_non_negative_int_field(self, record, "smf90pln")
                count = assert_non_negative_int_field(self, record, "smf90pon")
                if count:
                    self.assertGreater(offset, 0)
                    self.assertGreater(length, 0)
                self.assertGreaterEqual(len(record.sections), count)

        if not saw_adjacent_triplet:
            self.skipTest(
                "dataset sample did not include SMF type 90 adjacent triplets"
            )

    def test_real_type41_triplet_directory_is_consistent_when_present(self) -> None:
        type41_records = self.records_of_type(41)
        if not type41_records:
            self.skipTest("dataset sample did not include parsed SMF type 41 records")

        saw_triplets = False
        saw_populated_triplets = False
        for record in type41_records:
            if "smf41trp" not in record.fields:
                continue
            saw_triplets = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                triplet_count = assert_non_negative_int_field(self, record, "smf41trp")
                if "smf41opd" in record.fields:
                    assert_non_negative_int_field(self, record, "smf41opd")
                if triplet_count:
                    saw_populated_triplets = True
                    self.assertTrue(record.sections)

        if not saw_triplets:
            self.skipTest("dataset sample did not include SMF type 41 triplet fields")
        if not saw_populated_triplets:
            self.skipTest(
                "dataset sample did not include populated SMF type 41 triplets"
            )

    def test_real_type42_subtype_triplets_are_consistent_when_present(self) -> None:
        type42_records = self.records_of_type(42)
        if not type42_records:
            self.skipTest("dataset sample did not include parsed SMF type 42 records")

        subtype_triplets = {
            1: ("smf42bmo", "smf42bml", "smf42bmn"),
            2: ("smf42cuo", "smf42cul", "smf42cun"),
            3: ("smf42eao", "smf42eal", "smf42ean"),
            4: ("smf42cco", "smf42ccl", "smf42ccn"),
            5: ("smf42sro", "smf42srl", "smf42srn"),
            6: ("smf42jho", "smf42jhl", "smf42jhn"),
            9: ("smf42abo", "smf42abl", "smf42abn"),
            10: ("smf42vsf", "smf42vsl", "smf42vsn"),
            11: ("smf42xro", "smf42xrl", "smf42xrn"),
            15: ("smf42fc1", "smf42fc2", "smf42fc3"),
            16: ("smf42gd1", "smf42gd2", "smf42gd3"),
            17: ("smf42hl1", "smf42hl2", "smf42hl3"),
            18: ("smf42im1", "smf42im2", "smf42im3"),
            19: ("smf42jn1", "smf42jn2", "smf42jn3"),
            20: ("smf42kn1", "smf42kn2", "smf42kn3"),
            21: ("smf42ln1", "smf42ln2", "smf42ln3"),
            22: ("smf4222aud", "smf4222lad", "smf4222nad"),
            23: ("smf4223sec", "smf4223lsc", "smf4223nsc"),
            24: ("smf42pn1", "smf42pn2", "smf42pn3"),
            25: ("smf42qn1", "smf42qn2", "smf42qn3"),
            27: ("smf4227r1", "smf4227r2", "smf4227r3"),
        }
        saw_subtype_triplets = False
        saw_populated_subtype_triplets = False

        for record in type42_records:
            subtype = record.subtype
            if subtype not in subtype_triplets:
                continue
            offset_name, length_name, count_name = subtype_triplets[subtype]
            if count_name not in record.fields:
                continue
            saw_subtype_triplets = True
            with self.subTest(offset=record.offset, subtype=subtype):
                offset = assert_non_negative_int_field(self, record, offset_name)
                length = assert_non_negative_int_field(self, record, length_name)
                count = assert_non_negative_int_field(self, record, count_name)
                if count:
                    saw_populated_subtype_triplets = True
                    self.assertGreaterEqual(offset, 0)
                    self.assertGreater(length, 0)
                    self.assertTrue(record.extended_sections)

        if not saw_subtype_triplets:
            self.skipTest(
                "dataset sample did not include SMF type 42 subtype triplet fields"
            )
        if not saw_populated_subtype_triplets:
            self.skipTest(
                "dataset sample did not include populated SMF type 42 subtype "
                "triplets"
            )

    def test_real_type42_above_bar_triplets_are_exposed_when_present(self) -> None:
        type42_records = self.records_of_type(42)
        if not type42_records:
            self.skipTest("dataset sample did not include parsed SMF type 42 records")

        above_bar_triplets = {
            15: ("smf42afc1", "smf42afc2", "smf42afc3"),
            16: ("smf42agd1", "smf42agd2", "smf42agd3"),
            19: ("smf42ajn1", "smf42ajn2", "smf42ajn3"),
        }
        saw_above_bar_fields = False
        saw_populated_above_bar = False

        for record in type42_records:
            subtype = record.subtype
            if subtype not in above_bar_triplets:
                continue
            offset_name, length_name, count_name = above_bar_triplets[subtype]
            if count_name not in record.fields:
                continue
            saw_above_bar_fields = True
            with self.subTest(offset=record.offset, subtype=subtype):
                assert_non_negative_int_field(self, record, offset_name)
                length = assert_non_negative_int_field(self, record, length_name)
                count = assert_non_negative_int_field(self, record, count_name)
                if count:
                    saw_populated_above_bar = True
                    self.assertGreater(length, 0)

        if not saw_above_bar_fields:
            self.skipTest(
                "dataset sample did not include SMF type 42 above-bar triplet fields"
            )
        if not saw_populated_above_bar:
            self.skipTest(
                "dataset sample did not include populated SMF type 42 above-bar "
                "triplets"
            )

    def test_real_type85_extended_triplets_are_consistent_when_present(self) -> None:
        type85_records = self.records_of_type(85)
        if not type85_records:
            self.skipTest("dataset sample did not include parsed SMF type 85 records")

        saw_extended_triplets = False
        saw_populated_extended_triplets = False
        for record in type85_records:
            if "smf85osn" not in record.fields:
                continue
            saw_extended_triplets = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                offset = assert_non_negative_int_field(self, record, "smf85oso")
                length = assert_non_negative_int_field(self, record, "smf85osl")
                count = assert_non_negative_int_field(self, record, "smf85osn")
                if count:
                    saw_populated_extended_triplets = True
                    self.assertGreater(offset, 0)
                    self.assertGreater(length, 0)
                    self.assertTrue(record.extended_sections)

        if not saw_extended_triplets:
            self.skipTest(
                "dataset sample did not include SMF type 85 extended triplet fields"
            )
        if not saw_populated_extended_triplets:
            self.skipTest(
                "dataset sample did not include populated SMF type 85 extended "
                "triplets"
            )

    def test_real_type113_sds_triplets_are_consistent_when_present(self) -> None:
        type113_records = self.records_of_type(113)
        if not type113_records:
            self.skipTest("dataset sample did not include parsed SMF type 113 records")

        saw_sds_fields = False
        saw_populated_sds = False
        for record in type113_records:
            if "smf113son" not in record.fields:
                continue
            saw_sds_fields = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                for field_name in (
                    "smf113sof",
                    "smf113sln",
                    "smf113son",
                    "smf113iof",
                    "smf113iln",
                    "smf113ion",
                    "smf113dof",
                    "smf113dln",
                    "smf113don",
                ):
                    assert_non_negative_int_field(self, record, field_name)
                if "smf113sdl" in record.fields:
                    assert_non_negative_int_field(self, record, "smf113sdl")
                if record.fields["smf113son"]:
                    saw_populated_sds = True
                    self.assertTrue(record.sections)

        if not saw_sds_fields:
            self.skipTest("dataset sample did not include SMF type 113 SDS fields")
        if not saw_populated_sds:
            self.skipTest(
                "dataset sample did not include populated SMF type 113 SDS triplets"
            )

    def test_real_type124_subtype_triplets_are_consistent_when_present(self) -> None:
        type124_records = self.records_of_type(124)
        if not type124_records:
            self.skipTest("dataset sample did not include parsed SMF type 124 records")

        subtype_triplets = {
            1: ("smf124s1_port_offset", "smf124s1_port_len", "smf124s1_port_num"),
            2: (
                "smf124s2_epsecstat_offset",
                "smf124s2_epsecstat_len",
                "smf124s2_epsecstat_num",
            ),
            3: (
                "smf124s3_authkeyupd_offset",
                "smf124s3_authkeyupd_len",
                "smf124s3_authkeyupd_num",
            ),
            4: (
                "smf124s4_encrkeyupd_offset",
                "smf124s4_encrkeyupd_len",
                "smf124s4_encrkeyupd_num",
            ),
            5: (
                "smf124s5_extkeymgrinfo_offset",
                "smf124s5_extkeymgrinfo_len",
                "smf124s5_extkeymgrinfo_num",
            ),
        }
        saw_subtype_triplets = False
        saw_populated_subtype_triplets = False

        for record in type124_records:
            self.assertIn("smf124sty", record.fields)
            subtype = record.subtype
            if subtype not in subtype_triplets:
                continue
            offset_name, length_name, count_name = subtype_triplets[subtype]
            if count_name not in record.fields:
                continue
            saw_subtype_triplets = True
            with self.subTest(offset=record.offset, subtype=subtype):
                offset = assert_non_negative_int_field(self, record, offset_name)
                length = assert_non_negative_int_field(self, record, length_name)
                count = assert_non_negative_int_field(self, record, count_name)
                if count:
                    saw_populated_subtype_triplets = True
                    self.assertGreater(offset, 0)
                    self.assertGreater(length, 0)
                    self.assertTrue(record.sections)

        if not saw_subtype_triplets:
            self.skipTest(
                "dataset sample did not include SMF type 124 subtype triplet fields"
            )
        if not saw_populated_subtype_triplets:
            self.skipTest(
                "dataset sample did not include populated SMF type 124 subtype "
                "triplets"
            )

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

    def test_real_type98_sds_directory_is_consistent_when_present(self) -> None:
        type98_records = self.records_of_type(98)
        if not type98_records:
            self.skipTest("dataset sample did not include parsed SMF type 98 records")

        saw_sds_directory = False
        saw_populated_directory = False
        for record in type98_records:
            if "smf98sdstripletsnum" not in record.fields:
                continue
            saw_sds_directory = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                triplet_count = assert_non_negative_int_field(
                    self, record, "smf98sdstripletsnum"
                )
                if "smf98sdslen" in record.fields:
                    assert_non_negative_int_field(self, record, "smf98sdslen")
                if triplet_count:
                    saw_populated_directory = True
                    self.assertTrue(record.sections)

        if not saw_sds_directory:
            self.skipTest("dataset sample did not include SMF type 98 SDS directories")
        if not saw_populated_directory:
            self.skipTest(
                "dataset sample did not include populated SMF type 98 SDS directories"
            )

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

    def test_real_type1154_common_fields_are_decoded_when_present(self) -> None:
        type1154_records = self.records_of_type(1154)
        if not type1154_records:
            self.skipTest("dataset sample did not include parsed SMF type 1154 records")

        saw_common_section = False
        saw_decoded_common_text = False
        for record in type1154_records:
            if "smf1154_c_offset" not in record.fields:
                continue
            saw_common_section = True
            with self.subTest(offset=record.offset, subtype=record.subtype):
                assert_non_negative_int_field(self, record, "smf1154_c_offset")
                if "smf1154_subspec_offset" in record.fields:
                    assert_non_negative_int_field(
                        self, record, "smf1154_subspec_offset"
                    )
                for field_name in ("smf1154_c_userid", "smf1154_c_jobname"):
                    if assert_decoded_field_is_searchable(self, record, field_name):
                        saw_decoded_common_text = True

        if not saw_common_section:
            self.skipTest(
                "dataset sample did not include SMF type 1154 common sections"
            )
        if not saw_decoded_common_text:
            self.skipTest("dataset sample did not include decoded SMF type 1154 text")

    def test_real_type119_tcpip_sections_are_exposed_when_present(self) -> None:
        type119_records = self.structured_records_of_type(119)
        if not type119_records:
            self.skipTest("dataset sample did not include parsed SMF type 119 records")

        saw_self_defining_sections = False
        saw_identification_section = False
        saw_decoded_tcpip_text = False
        for record in type119_records:
            with self.subTest(offset=record.offset, subtype=record.subtype):
                self.assertEqual(record.fields["SMF119HDType"], 119)
                if record.subtype is not None:
                    self.assertEqual(record.fields["SMF119HDSubType"], record.subtype)
                self.assertEqual(
                    normalized_field_length(record.fields["SMF119HDLength"]),
                    record.header.length if record.header is not None else None,
                )
                for field_name in ("SMF119HDTime", "SMF119HDDate"):
                    self.assertIsInstance(record.fields[field_name], int)
                    self.assertEqual(
                        record.raw_fields[field_name], record.fields[field_name]
                    )

                if "SMF119SD_TRN" in record.fields:
                    saw_self_defining_sections = True
                    triplet_count = assert_non_negative_int_field(
                        self, record, "SMF119SD_TRN"
                    )
                    for field_name in ("SMF119IDOff", "SMF119IDLen", "SMF119IDNum"):
                        assert_non_negative_int_field(self, record, field_name)
                    if triplet_count:
                        self.assertTrue(record.sections)

                if "SMF119TI_Stack" in record.fields:
                    saw_identification_section = True
                    for field_name in (
                        "SMF119TI_SYSName",
                        "SMF119TI_SysplexName",
                        "SMF119TI_Stack",
                        "SMF119TI_ReleaseID",
                        "SMF119TI_Comp",
                        "SMF119TI_ASName",
                        "SMF119TI_UserID",
                    ):
                        if assert_decoded_field_is_searchable(self, record, field_name):
                            saw_decoded_tcpip_text = True
                    for field_name in (
                        "SMF119TI_ASID",
                        "SMF119TI_Reason",
                        "SMF119TI_RecordID",
                    ):
                        assert_non_negative_int_field(self, record, field_name)

        if not saw_self_defining_sections:
            self.skipTest("dataset sample did not include SMF type 119 triplets")
        if not saw_identification_section:
            type119_triplets = [
                {
                    "offset": record.offset,
                    "subtype": record.subtype,
                    "id_offset": record.fields.get("SMF119IDOff"),
                    "id_length": record.fields.get("SMF119IDLen"),
                    "id_count": record.fields.get("SMF119IDNum"),
                    "sections": len(record.sections),
                }
                for record in type119_records[:5]
            ]
            self.fail(
                "SMF type 119 triplets were present but no identification fields "
                f"were decoded: {type119_triplets!r}"
            )
        if not saw_decoded_tcpip_text:
            self.skipTest("dataset sample did not include decoded SMF type 119 text")

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
