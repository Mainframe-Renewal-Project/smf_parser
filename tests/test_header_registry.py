from __future__ import annotations

import unittest

from pysmf._header_registry import HEADER_TARGETS, SPECIAL_RECORD_ACTIONS

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
    "IXCYSM90",
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
        names.update(
            str(name).removesuffix(".h").upper()
            for name in target.get("alternate_names", ())
        )
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

    def test_type98_subtype_overlays_cover_known_wic_subtypes(self) -> None:
        actions = SPECIAL_RECORD_ACTIONS[98]
        subtype_values = {
            int(action["subtype_value"])
            for action in actions
            if action.get("kind") == "smf98_subtype_overlay"
        }
        self.assertTrue({1, 3, 4, 5, 6, 7, 8}.issubset(subtype_values))

    def test_additional_record_types_have_dynamic_special_actions() -> None:
        expected_kinds = {
            41: "inline_long_triplet_directory",
            42: "inline_long_triplet_directory",
            85: "offset_long_triplet_directory",
            113: "smf113_sds_overlay",
            124: "conditional_offset_long_triplet_directory",
        }

        for record_type, action_kind in expected_kinds.items():
            actions = SPECIAL_RECORD_ACTIONS.get(record_type)
            assert actions is not None
            assert any(action.get("kind") == action_kind for action in actions)

    def test_type42_subtype_overlay_actions_cover_known_subtypes(self) -> None:
        actions = SPECIAL_RECORD_ACTIONS[42]
        subtype_values = {
            int(action["subtype_value"])
            for action in actions
            if action.get("kind") == "subtype_struct_overlay_directory"
        }
        self.assertTrue(
            {
                1,
                2,
                3,
                4,
                5,
                6,
                9,
                10,
                11,
                15,
                16,
                17,
                18,
                19,
                20,
                21,
                22,
                23,
                24,
                25,
                27,
            }.issubset(subtype_values)
        )


if __name__ == "__main__":
    unittest.main()
