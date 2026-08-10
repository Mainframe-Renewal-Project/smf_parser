from __future__ import annotations

import unittest
from pathlib import Path


def generated_setup_source() -> str:
    setup_path = Path(__file__).parents[1] / "setup.py"
    return setup_path.read_text(encoding="utf-8")


def native_source() -> str:
    native_path = Path(__file__).parents[1] / "src" / "pysmf" / "_native.c"
    return native_path.read_text(encoding="utf-8")


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
        self.assertIn("append_self_defining_section_directory", generated)
        self.assertIn("_self_defining_triplet_parser_lines", generated)
        self.assertIn("_self_defining_triplets", generated)
        self.assertIn('\\"relocate_sections\\"', generated)
        self.assertIn('\\"extended_relocate_sections\\"', generated)
        self.assertIn("read_unsigned_be(data +", generated)
        self.assertIn("int append_self_defining_triplet_sections", native)
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


if __name__ == "__main__":
    unittest.main()
