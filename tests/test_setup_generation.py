from __future__ import annotations

import unittest
from pathlib import Path


class SetupGenerationTests(unittest.TestCase):
    def test_smf80_sections_use_self_defining_directory_parser(self) -> None:
        setup_path = Path(__file__).parents[1] / "setup.py"
        generated = setup_path.read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
