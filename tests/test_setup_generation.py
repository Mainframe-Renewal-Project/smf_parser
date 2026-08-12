from __future__ import annotations
import importlib
import unittest
from pathlib import Path


def generated_setup_source() -> str:
    build_path = Path(__file__).parents[1] / "tools" / "smf_build.py"
    return build_path.read_text(encoding="utf-8")


def native_source() -> str:
    native_path = Path(__file__).parents[1] / "src" / "pysmf" / "_native.c"
    return native_path.read_text(encoding="utf-8")


def setup_module():
    return importlib.import_module("tools.smf_build")


def generated_function_source(source: str, name: str) -> str:
    marker = f"static int {name}"
    if marker not in source:
        marker = f"int {name}"
    start = source.index(marker)
    next_function = source.find("\nint ", start + len(marker))
    next_static_function = source.find("\nstatic int ", start + len(marker))
    if next_function == -1 or (
        next_static_function != -1 and next_static_function < next_function
    ):
        next_function = next_static_function
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


class SetupGenerationTests(unittest.TestCase):
    def test_sections_use_header_derived_self_defining_parsers(self) -> None:
        generated = generated_setup_source()
        native = native_source()

        self.assertIn("append_self_defining_triplet_sections", generated)
        self.assertIn("append_self_defining_variable_sections", generated)
        self.assertIn("append_self_defining_section_directory", generated)
        self.assertIn("_self_defining_triplet_parser_lines", generated)
        self.assertIn("_self_defining_triplets", generated)
        self.assertIn('\\"relocate_sections\\"', generated)
        self.assertIn("extended_relocate_sections", generated)
        self.assertIn("read_unsigned_be(data +", generated)
        self.assertIn("int append_self_defining_triplet_sections", native)
        self.assertIn("int append_self_defining_variable_sections", native)
        self.assertIn("int append_self_defining_section_directory", native)
        self.assertIn("section_offset = read_unsigned_be", native)
        self.assertNotIn("discover_self_defining_sections", generated)
        self.assertNotIn("for (directory = 24", generated)
        self.assertNotIn("if 80 <= record_type <= 84:", generated)
        self.assertNotIn("static int set_smf80_relocate_sections", generated)
        self.assertNotIn("static int set_smf80_extended_relocate_sections", generated)

    def test_header_derived_triplets_append_all_occurrences(self) -> None:
        generated = generated_setup_source()
        native = native_source()
        triplet_parser = generated_function_source(
            native, "append_self_defining_triplet_sections"
        )

        self.assertIn("section_list(dict, key)", triplet_parser)
        self.assertIn("for (occurrence = 0; occurrence < section_count", triplet_parser)
        self.assertIn("append_section(", triplet_parser)
        self.assertNotIn("PyList_New(0);", triplet_parser)
        self.assertIn("int append_self_defining_triplet_sections", generated)

    def test_racf_relocate_sections_use_header_variable_blocks(self) -> None:
        module = setup_module()
        fields_by_name = {
            "smf81rel": {"name": "smf81rel", "offset": 128, "size": 2},
            "smf81cnt": {"name": "smf81cnt", "offset": 130, "size": 2},
            "smf80rl2": {"name": "smf80rl2", "offset": 92, "size": 2},
            "smf80ct2": {"name": "smf80ct2", "offset": 94, "size": 2},
        }
        section_structs = {
            "smf81var": (
                {"name": "smf81dtp", "offset": 0, "size": 1},
                {"name": "smf81dln", "offset": 1, "size": 1},
                {"name": "smf81dta", "offset": 2, "size": 255},
            ),
            "smf80vr2": (
                {"name": "smf80tp2", "offset": 0, "size": 2},
                {"name": "smf80dl2", "offset": 2, "size": 2},
            ),
        }

        lines = "\n".join(
            module._variable_section_parser_lines(fields_by_name, section_structs)
        )

        self.assertIn("append_self_defining_variable_sections", lines)
        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn('result, "extended_relocate_sections", data, view->len', lines)
        self.assertIn("read_unsigned_be(data + 128, 2)", lines)
        self.assertIn("read_unsigned_be(data + 130, 2)", lines)
        self.assertIn("1, 1, 2", lines)
        self.assertIn("2, 2, 4", lines)

        directory_lines = "\n".join(
            module._section_directory_parser_lines(fields_by_name, section_structs)
        )

        self.assertNotIn("append_self_defining_section_directory", directory_lines)

    def test_racf_type80_event_offsets_are_header_derived(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "IBM" / "IFASMFR9"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        fields = module._record_struct_fields(structs["smfrcd80"])
        fields_by_name = {field["name"]: field for field in fields}

        self.assertEqual(fields_by_name["smf80des"]["offset"], 18)
        self.assertEqual(fields_by_name["smf80des"]["size"], 2)
        self.assertEqual(fields_by_name["smf80evt"]["offset"], 20)
        self.assertEqual(fields_by_name["smf80evt"]["size"], 1)
        self.assertEqual(fields_by_name["smf80evq"]["offset"], 21)
        self.assertEqual(fields_by_name["smf80usr"]["offset"], 22)

    def test_racf_type80_compact_section_directory_is_generated(self) -> None:
        module = setup_module()
        fields_by_name = {
            "smf80des": {"name": "smf80des", "offset": 18, "size": 2},
            "smf80evq": {"name": "smf80evq", "offset": 21, "size": 1},
        }

        lines = "\n".join(
            module._compact_racf_type80_section_parser_lines(80, fields_by_name)
        )

        self.assertIn('PyDict_GetItemString(result, "relocate_sections")', lines)
        self.assertIn("read_unsigned_be(data + 22, 2)", lines)
        self.assertIn("read_unsigned_be(data + 24, 2)", lines)
        self.assertIn("18 + read_unsigned_be(\n                data + 22, 2)", lines)

        self.assertEqual(
            module._compact_racf_type80_section_parser_lines(81, fields_by_name), []
        )

    def test_racf_type83_subtype1_security_fields_are_generated(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "IBM" / "IFASMFR9"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)

        lines = "\n".join(
            module._racf_type83_subtype1_parser_lines(
                83,
                module._record_section_structs(83, structs),
                module._record_special_structs(83, structs),
            )
        )

        self.assertIn("smf83_subtype_offset", lines)
        self.assertIn("smf83_sds_offset", lines)
        self.assertIn("is_packed_smf_date(data + 6)", lines)
        self.assertIn("is_packed_smf_date(data + 10)", lines)
        self.assertIn("read_unsigned_be(data + 18, 2) == 1", lines)
        self.assertIn("read_unsigned_be(data + 22, 2) == 1", lines)
        self.assertIn("read_unsigned_be(data + smf83_sds_offset, 2) != 3", lines)
        self.assertIn('set_long(result, "smf83typ"', lines)
        self.assertIn('set_long(result, "smf83evt"', lines)
        self.assertIn('set_long(result, "smf83evq"', lines)
        self.assertIn('set_bytes(result, "smf83usr"', lines)
        self.assertIn('set_bytes(result, "smf83jbn"', lines)
        self.assertIn(
            'security_offset = read_unsigned_be(data + smf83_sds_offset + 12, 4);',
            lines,
        )
        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn("1, 1, 2) < 0", lines)
        self.assertIn("PyErr_Clear();", lines)
        self.assertNotIn("type83_security_sections", lines)

        self.assertEqual(module._racf_type83_subtype1_parser_lines(80, {}, {}), [])

    def test_racf_type83_fixed_header_fields_are_preserved(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "IBM" / "IFASMFR9"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        fields = module._record_struct_fields(structs["smf83rcd"])
        fields_by_name = {field["name"]: field for field in fields}

        self.assertIn("smf83len", fields_by_name)
        self.assertIn("smf83rty", fields_by_name)
        self.assertIn("smf83sid", fields_by_name)
        self.assertIn("smf83df1", fields_by_name)
        self.assertNotIn("smf83trp", fields_by_name)
        self.assertEqual(fields_by_name["smf83len"]["offset"], 0)
        self.assertEqual(fields_by_name["smf83df1"]["offset"], 18)

    def test_adjacent_self_defining_section_structs_are_generated(self) -> None:
        module = setup_module()
        fields = (
            {
                "name": "smf90pof",
                "type": "int32_t",
                "array": 0,
                "bits": 0,
                "offset": 0,
                "size": 4,
                "signed": True,
            },
            {
                "name": "smf90pln",
                "type": "int16_t",
                "array": 0,
                "bits": 0,
                "offset": 4,
                "size": 2,
                "signed": True,
            },
            {
                "name": "smf90pon",
                "type": "int16_t",
                "array": 0,
                "bits": 0,
                "offset": 6,
                "size": 2,
                "signed": True,
            },
        )

        lines = "\n".join(module._adjacent_section_parser_lines(fields, base_offset=20))

        self.assertIn("view->len >= (Py_ssize_t)28", lines)
        self.assertIn('set_long(result, "smf90pof"', lines)
        self.assertIn('set_long(result, "smf90pln"', lines)
        self.assertIn('set_long(result, "smf90pon"', lines)
        self.assertIn("append_self_defining_triplet_sections", lines)
        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn("read_unsigned_be(data + 20, 4)", lines)
        self.assertIn("read_unsigned_be(data + 24, 2)", lines)
        self.assertIn("read_unsigned_be(data + 26, 2)", lines)

    def test_smf98_top_level_union_header_fields_are_extracted(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "IBM" / "IHAHR098"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        fields = module._record_struct_fields(structs["smfr98"])
        fields_by_name = {field["name"]: field for field in fields}

        self.assertIn("smf98len", fields_by_name)
        self.assertIn("smf98sty", fields_by_name)
        self.assertIn("smf98sdslen", fields_by_name)
        self.assertIn("smf98sdstripletsnum", fields_by_name)
        self.assertEqual(fields_by_name["smf98sty"]["offset"], 22)
        self.assertEqual(fields_by_name["smf98sdstripletsnum"]["offset"], 28)

    def test_smf98_sds_long_triplet_directory_is_generated(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "IBM" / "IHAHR098"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        fields = module._record_struct_fields(structs["smfr98"])

        lines = "\n".join(module._smf98_sds_parser_lines(98, fields))

        self.assertIn("append_self_defining_long_triplet_directory", lines)
        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn("48,", lines)
        self.assertIn("read_unsigned_be(data + 28, 2)", lines)

        self.assertEqual(module._smf98_sds_parser_lines(90, fields), [])

    def test_smf1154_common_directory_is_generated(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "zos" / "ifar1154.h"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)

        lines = "\n".join(
            module._smf1154_common_parser_lines(
                1154,
                module._record_special_structs(1154, structs),
            )
        )

        self.assertIn("smf1154_ctrp = 24 + read_unsigned_be(data + 24, 2)", lines)
        self.assertIn('set_long(result, "smf1154_c_offset"', lines)
        self.assertIn('set_long(result, "smf1154_subspec_offset"', lines)
        self.assertIn("append_self_defining_long_triplet_directory", lines)
        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn('result, "extended_relocate_sections", data, view->len', lines)
        self.assertIn('set_bytes(result, "smf1154_c_userid"', lines)
        self.assertIn('set_bytes(result, "smf1154_c_jobname"', lines)

        self.assertEqual(module._smf1154_common_parser_lines(98, {}), [])

    def test_variable_sections_report_invalid_header_metadata(self) -> None:
        native = native_source()
        variable_parser = generated_function_source(
            native, "append_self_defining_variable_sections"
        )

        self.assertIn("if (section_count == 0)", variable_parser)
        self.assertIn("PyErr_SetString(PyExc_ValueError", variable_parser)
        self.assertIn("if (data_type == 0 && section_length == 0)", variable_parser)
        self.assertIn("base_offset += data_offset", variable_parser)
        self.assertIn("int appended = 0", variable_parser)
        self.assertIn("return appended", variable_parser)
        self.assertIn("section_count > 4096", variable_parser)
        self.assertIn("return 0", variable_parser)
        self.assertIn(
            "SMF variable section length is outside the record", variable_parser
        )

    def test_native_long_triplet_directory_uses_four_byte_offsets(self) -> None:
        native = native_source()
        directory_parser = generated_function_source(
            native, "append_self_defining_long_triplet_directory"
        )

        self.assertIn("directory + (index * 8)", directory_parser)
        self.assertIn(
            "section_offset = read_unsigned_be(data + entry_offset, 4)",
            directory_parser,
        )
        self.assertIn(
            "section_length = read_unsigned_be(data + entry_offset + 4, 2)",
            directory_parser,
        )
        self.assertIn(
            "section_count = read_unsigned_be(data + entry_offset + 6, 2)",
            directory_parser,
        )

    def test_native_record_type_validation_accepts_extended_records(self) -> None:
        native = native_source()
        validator = generated_function_source(native, "validate_record_type")

        self.assertIn("data[5] == EXTENDED_RECORD_INDICATOR", validator)
        self.assertIn("data[4] & EXTENDED_HEADER_FLAG", validator)
        self.assertIn("read_unsigned_be(data + 52, 2)", validator)

    def test_native_section_directory_can_use_header_anchor_without_count(
        self,
    ) -> None:
        native = native_source()
        directory_parser = generated_function_source(
            native, "append_self_defining_section_directory"
        )

        self.assertIn(
            "count = ((unsigned long long)record_length - directory) / 6",
            directory_parser,
        )
        self.assertIn("directory + (index * 6)", directory_parser)
        self.assertIn(
            "section_offset = read_unsigned_be(data + entry_offset, 2)",
            directory_parser,
        )
        self.assertIn(
            "section_length = read_unsigned_be(data + entry_offset + 2, 2)",
            directory_parser,
        )
        self.assertIn(
            "section_count = read_unsigned_be(data + entry_offset + 4, 2)",
            directory_parser,
        )
        self.assertIn("inferred_count = 1", directory_parser)
        self.assertIn(
            "if (triplet_sections == 0 && (inferred_count || appended > 0))",
            directory_parser,
        )

    def test_section_directories_are_detected_from_rel_count_field_pairs(
        self,
    ) -> None:
        module = setup_module()
        fields_by_name = {
            "smf80rel": {"name": "smf80rel", "offset": 44, "size": 2},
            "smf80cnt": {"name": "smf80cnt", "offset": 46, "size": 2},
            "smf80rl2": {"name": "smf80rl2", "offset": 104, "size": 2},
            "smf80ct2": {"name": "smf80ct2", "offset": 106, "size": 2},
            "smf81rel": {"name": "smf81rel", "offset": 32, "size": 2},
            "smf81cnt": {"name": "smf81cnt", "offset": 34, "size": 2},
        }

        lines = "\n".join(module._section_directory_parser_lines(fields_by_name))

        self.assertIn('result, "relocate_sections", data, view->len', lines)
        self.assertIn('result, "extended_relocate_sections", data, view->len', lines)
        self.assertIn("read_unsigned_be(data + 32, 2)", lines)
        self.assertIn("read_unsigned_be(data + 34, 2)", lines)

    def test_record_fields_are_extracted_by_brace_depth_not_indent(self) -> None:
        module = setup_module()
        fields = module._record_struct_fields(
            """
    uint16_t smf21len;
    union {
      struct {
        uint16_t nested_field;
      } nested;
    } view;
    uint8_t smf21rty;
"""
        )

        self.assertEqual([field["name"] for field in fields], ["smf21len", "smf21rty"])
        self.assertEqual([field["offset"] for field in fields], [0, 2])

    def test_record_fields_use_first_top_level_union_member(self) -> None:
        module = setup_module()
        fields = module._record_struct_fields(
            """
  union {
    unsigned char smf21hdr[104];
    struct {
      uint16_t smf21len;
      uint8_t smf21rty;
    } decoded;
  } header;
  uint16_t trailing;
"""
        )

        self.assertEqual([field["name"] for field in fields], ["smf21hdr", "trailing"])
        self.assertEqual([field["offset"] for field in fields], [0, 104])

    def test_smf119_header_uses_ibm_c_primitive_fields(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "zos" / "ezasmf.h"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        fields = module._record_struct_fields(structs["Smf119Header"])
        fields_by_name = {field["name"]: field for field in fields}

        self.assertEqual(module._record_struct_name(119, structs), "Smf119Header")
        self.assertEqual(fields_by_name["SMF119HDLength"]["offset"], 0)
        self.assertEqual(fields_by_name["SMF119HDLength"]["size"], 2)
        self.assertEqual(fields_by_name["SMF119HDType"]["offset"], 5)
        self.assertEqual(fields_by_name["SMF119HDTime"]["size"], 4)
        self.assertEqual(fields_by_name["SMF119HDSID"]["offset"], 14)
        self.assertEqual(fields_by_name["SMF119HDSubType"]["offset"], 22)

    def test_smf119_self_defining_sections_are_generated(self) -> None:
        module = setup_module()
        header = (
            Path(__file__).parents[1] / "local_headers" / "zos" / "ezasmf.h"
        ).read_text(encoding="utf-8")
        structs = module._header_structs(header)
        header_fields = module._record_struct_fields(structs["Smf119Header"])
        fields_by_name = {field["name"]: field for field in header_fields}

        lines = "\n".join(
            module._smf119_parser_lines(
                119,
                fields_by_name,
                module._record_special_structs(119, structs),
            )
        )

        self.assertIn("SMF119SD_TRN", lines)
        self.assertIn("SMF119IDOff", lines)
        self.assertIn("SMF119IDLen", lines)
        self.assertIn("SMF119IDNum", lines)
        self.assertIn("append_self_defining_long_triplet_directory", lines)
        self.assertIn('result, "relocate_sections", data, view->len, 28', lines)
        self.assertIn('set_bytes(result, "SMF119TI_SYSName"', lines)
        self.assertIn('set_bytes(result, "SMF119TI_Stack"', lines)
        self.assertIn('set_bytes(result, "SMF119TI_UserID"', lines)
        self.assertIn('set_long(result, "SMF119TI_ASID"', lines)
        self.assertIn('set_long(result, "SMF119TI_RecordID"', lines)

        self.assertEqual(module._smf119_parser_lines(118, {}, {}), [])

    def test_record_struct_names_include_common_ibm_variants(self) -> None:
        module = setup_module()
        structs = {
            "smf83rcd": "",
            "smf124rec": "",
            "smfr98": "",
            "smfrcd6a": "",
            "smfrcd10": "",
            "Smf119Header": "",
        }

        self.assertEqual(module._record_struct_name(83, structs), "smf83rcd")
        self.assertEqual(module._record_struct_name(124, structs), "smf124rec")
        self.assertEqual(module._record_struct_name(98, structs), "smfr98")
        self.assertEqual(module._record_struct_name(106, structs), "smfrcd6a")
        self.assertEqual(module._record_struct_name(119, structs), "Smf119Header")
        self.assertIsNone(module._record_struct_name(16, structs))


if __name__ == "__main__":
    unittest.main()
