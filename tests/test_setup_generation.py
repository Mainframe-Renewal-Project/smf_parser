from __future__ import annotations

import unittest
from pathlib import Path


def generated_setup_source() -> str:
    setup_path = Path(__file__).parents[1] / "setup.py"
    return setup_path.read_text(encoding="utf-8")


def generated_function_source(source: str, name: str) -> str:
    marker = f"static int {name}"
    start = source.index(marker)
    next_function = source.find("static int ", start + len(marker))
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


class SetupGenerationTests(unittest.TestCase):
    def test_smf80_sections_use_self_defining_directory_parser(self) -> None:
        generated = generated_setup_source()

        self.assertIn("set_smf80_self_defining_sections", generated)
        self.assertIn("discover_smf80_self_defining_sections", generated)
        self.assertIn("section_list_has_entries", generated)
        self.assertIn('\\"relocate_sections\\"', generated)
        self.assertIn('\\"extended_relocate_sections\\"', generated)
        self.assertIn("section_offset = ", generated)
        self.assertIn("read_unsigned_be(data + entry_offset, 4);", generated)
        self.assertIn("directory = 24", generated)
        self.assertIn("PyList_Size(list) > 0", generated)
        self.assertIn("list, directory, data + offset", generated)
        self.assertNotIn("static int set_smf80_relocate_sections", generated)
        self.assertNotIn("static int set_smf80_extended_relocate_sections", generated)

    def test_smf80_discovery_collects_multiple_directory_entries(self) -> None:
        generated = generated_setup_source()
        discovery = generated_function_source(
            generated, "discover_smf80_self_defining_sections"
        )

        self.assertIn("for (directory = 24", discovery)
        self.assertIn("for (occurrence = 0; occurrence < section_count", discovery)
        self.assertIn("append_section(", discovery)
        self.assertNotIn("return set_smf80_self_defining_sections", discovery)
        self.assertNotIn("dict, key, data, record_length, directory, 1", discovery)


if __name__ == "__main__":
    unittest.main()
