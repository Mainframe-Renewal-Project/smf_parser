from __future__ import annotations

import importlib.util
import types
import unittest
from pathlib import Path


def generated_setup_source() -> str:
    setup_path = Path(__file__).parents[1] / "setup.py"
    return setup_path.read_text(encoding="utf-8")


def native_source() -> str:
    native_path = Path(__file__).parents[1] / "src" / "pysmf" / "_native.c"
    return native_path.read_text(encoding="utf-8")


def setup_module():
    setup_path = Path(__file__).parents[1] / "setup.py"
    source = setup_path.read_text(encoding="utf-8")
    source = "\n".join(
        line
        for line in source.splitlines()
        if not line.startswith(("from setuptools", "from wheel"))
    )
    module = types.SimpleNamespace(__file__=str(setup_path))
    namespace = module.__dict__
    namespace.update(
        {
            "Extension": lambda *args, **kwargs: (args, kwargs),
            "setup": lambda *args, **kwargs: None,
            "CompileError": Exception,
            "new_compiler": lambda: None,
            "customize_compiler": lambda _compiler: None,
            "get_platform": lambda: "test-platform",
            "build_ext_base": object,
            "build_py_base": object,
            "bdist_wheel_base": object,
        }
    )
    exec(compile(source, str(setup_path), "exec"), namespace)
    return module


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

    def test_variable_sections_report_invalid_header_metadata(self) -> None:
        native = native_source()
        variable_parser = generated_function_source(
            native, "append_self_defining_variable_sections"
        )

        self.assertIn("if (section_count == 0)", variable_parser)
        self.assertIn("PyErr_SetString(PyExc_ValueError", variable_parser)
        self.assertIn("SMF variable section offset is outside the record", variable_parser)
        self.assertIn("SMF variable section length is outside the record", variable_parser)

    def test_native_section_directory_can_use_header_anchor_without_count(
        self,
    ) -> None:
        native = native_source()
        directory_parser = generated_function_source(
            native, "append_self_defining_section_directory"
        )

        self.assertIn("count = ((unsigned long long)record_length - directory) / 6", directory_parser)
        self.assertIn("directory + (index * 6)", directory_parser)
        self.assertIn("section_offset = read_unsigned_be(data + entry_offset, 2)", directory_parser)
        self.assertIn("section_length = read_unsigned_be(data + entry_offset + 2, 2)", directory_parser)
        self.assertIn("section_count = read_unsigned_be(data + entry_offset + 4, 2)", directory_parser)
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

        self.assertEqual(
            [field["name"] for field in fields], ["smf21len", "smf21rty"]
        )
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

        self.assertEqual(
            [field["name"] for field in fields], ["smf21hdr", "trailing"]
        )
        self.assertEqual([field["offset"] for field in fields], [0, 104])

    def test_record_struct_names_include_common_ibm_variants(self) -> None:
        module = setup_module()
        structs = {
            "smf83rcd": "",
            "smf124rec": "",
            "smfr98": "",
            "smfrcd6a": "",
            "smfrcd10": "",
        }

        self.assertEqual(module._record_struct_name(83, structs), "smf83rcd")
        self.assertEqual(module._record_struct_name(124, structs), "smf124rec")
        self.assertEqual(module._record_struct_name(98, structs), "smfr98")
        self.assertEqual(module._record_struct_name(106, structs), "smfrcd6a")
        self.assertIsNone(module._record_struct_name(16, structs))


if __name__ == "__main__":
    unittest.main()
