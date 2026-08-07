from __future__ import annotations

import unittest

from smf_parser._header_registry import HEADER_TARGETS


def record_types_for(header_name: str) -> tuple[int, ...]:
    for target in HEADER_TARGETS:
        if target["name"] == header_name:
            return tuple(target["record_types"])
    raise AssertionError(f"missing header target {header_name!r}")


class HeaderRegistryTests(unittest.TestCase):
    def test_ifasmfr_router_ranges_match_ibm_header(self) -> None:
        self.assertEqual(record_types_for("ifasmfr.h"), tuple(range(7)))
        self.assertEqual(record_types_for("ifasmfr1.h"), tuple(range(7, 20)))
        self.assertEqual(record_types_for("ifasmfr2.h"), tuple(range(20, 28)))
        self.assertEqual(record_types_for("ifasmfr3.h"), tuple(range(28, 37)))
        self.assertEqual(record_types_for("ifasmfr4.h"), tuple(range(37, 47)))
        self.assertEqual(record_types_for("ifasmfr5.h"), tuple(range(47, 55)))
        self.assertEqual(record_types_for("ifasmfr9.h"), tuple(range(80, 85)))

    def test_ifasmfcn_is_a_counter_constants_support_header(self) -> None:
        self.assertEqual(record_types_for("ifasmfcn.h"), (30, 1154))


if __name__ == "__main__":
    unittest.main()