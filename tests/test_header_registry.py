from __future__ import annotations

import unittest

from smf_parser._header_registry import HEADER_TARGETS

IBM_SMF_HEADER_NAMES = {
    "BPXYSMFR",
    "CBRSMF",
    "CNZMYSMF",
    "CSVAPSMF",
    "CSVDLSMF",
    "CSVLPSMF",
    "GTZZSMF1",
    "HISYSMFR",
    "HWISMF6A",
    "IAZSMF24",
    "IAZSMF25",
    "IAZSMF26",
    "IAZSMF43",
    "IAZSMF45",
    "IAZSMF47",
    "IAZSMF48",
    "IAZSMF49",
    "IAZSMF52",
    "IAZSMF53",
    "IAZSMF54",
    "IAZSMF55",
    "IAZSMF56",
    "IAZSMF57",
    "IAZSMF58",
    "IAZSMF84",
    "IDASMF62",
    "IDASMF64",
    "IECSMF94",
    "IEFOPSMF",
    "IFACSMFR",
    "IFASMFCN",
    "IFASMFH",
    "IFASMFR",
    "IFASMFR1",
    "IFASMFR2",
    "IFASMFR3",
    "IFASMFR4",
    "IFASMFR5",
    "IFASMFR9",
    "IFASMFRA",
    "IFBSMF90",
    "IFGSMF14",
    "IGESMF21",
    "IGGSMF17",
    "IGGSMF18",
    "IGGSMF19",
    "IGWSMF",
    "IHAVBSMF",
    "IOSDSMFR",
    "ISGYSMFR",
    "ITVSMF41",
    "IWMSMF90",
    "IWMSMF97",
    "IXGSMF88",
}

AGGREGATE_ONLY_HEADER_NAMES = {
    "IFACSMFR",
}


def record_types_for(header_name: str) -> tuple[int, ...]:
    for target in HEADER_TARGETS:
        if target["name"] == header_name:
            return tuple(target["record_types"])
    raise AssertionError(f"missing header target {header_name!r}")


def resolved_ibm_names() -> set[str]:
    names: set[str] = set()
    for target in HEADER_TARGETS:
        header_name = str(target["name"])
        names.add(header_name.removesuffix(".h").upper())
        names.update(str(name).removesuffix(".h").upper() for name in target.get("alternate_names", ()))
    return names


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

    def test_ibm_smf_headers_are_represented_by_registry_names(self) -> None:
        expected_registry_names = IBM_SMF_HEADER_NAMES - AGGREGATE_ONLY_HEADER_NAMES

        self.assertEqual(expected_registry_names - resolved_ibm_names(), set())
        self.assertEqual(AGGREGATE_ONLY_HEADER_NAMES & resolved_ibm_names(), set())


if __name__ == "__main__":
    unittest.main()