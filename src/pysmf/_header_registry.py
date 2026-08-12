"""z/OS SMF C headers that setup.py is expected to compile."""

from __future__ import annotations

from typing import Iterable


def _target(
    name: str,
    record_types: Iterable[int],
    *,
    generic: bool,
    alternate_names: tuple[str, ...] = (),
) -> dict[str, object]:
    target = {
        "name": name,
        "record_types": tuple(record_types),
        "generic": generic,
    }
    if alternate_names:
        target["alternate_names"] = alternate_names
    return target

# ``generic=True`` means the compiled header backs generic SMF record boundary
# and common-header parsing. Type-specific wrappers can be added from the same
# registry without changing the runtime discovery contract.
HEADER_TARGETS = (
    _target("ifasmfh.h", (), generic=True),
    _target("ifasmfr.h", range(7), generic=True),
    _target(
        "csfsm82c.h",
        (82,),
        generic=False,
        alternate_names=("CSFSM82C",),
    ),
    *(
        _target(name, range(start, stop), generic=False)
        for name, start, stop in (
            ("ifasmfr1.h", 7, 20),
            ("ifasmfr2.h", 20, 28),
            ("ifasmfr3.h", 28, 37),
            ("ifasmfr4.h", 37, 47),
            ("ifasmfr5.h", 47, 55),
            ("ifasmfr9.h", 80, 85),
            ("ifasmfra.h", 85, 104),
        )
    ),
    *(
        _target(name, record_types, generic=False)
        for name, record_types in (
            ("ifgsmf14.h", (14,)),
            ("iggsmf17.h", (17,)),
            ("iggsmf18.h", (18,)),
            ("iggsmf19.h", (19,)),
            ("igesmf21.h", (21,)),
            ("iosdsmfr.h", (22,)),
            ("iazsmf24.h", (24,)),
            ("iazsmf25.h", (25,)),
            ("iazsmf26.h", (26,)),
            ("itvsmf41.h", (41,)),
            ("igwsmf.h", (42,)),
            ("iazsmf43.h", (43,)),
            ("iazsmf45.h", (45,)),
            ("iazsmf47.h", (47,)),
            ("iazsmf48.h", (48,)),
            ("iazsmf49.h", (49,)),
            ("iazsmf52.h", (52,)),
            ("iazsmf53.h", (53,)),
            ("iazsmf54.h", (54,)),
            ("iazsmf55.h", (55,)),
            ("iazsmf56.h", (56,)),
            ("iazsmf57.h", (57,)),
            ("iazsmf58.h", (58,)),
            ("idasmf62.h", (60, 61, 62)),
            ("idasmf64.h", (64,)),
            ("iazsmf84.h", (84,)),
            ("cbrsmf.h", (85,)),
            ("isgysmfr.h", (87,)),
            ("ixgsmf88.h", (88,)),
        )
    ),
    *(
        _target(name, (90,), generic=False)
        for name in (
            "ifbsmf90.h",
            "cnzmysmf.h",
            "cnzmysm2.h",
            "csvdlsmf.h",
            "csvapsmf.h",
            "csvlpsmf.h",
            "ihavbsmf.h",
            "ixcysm90.h",
        )
    ),
    _target(
        "iefopsmf.h",
        (90,),
        generic=False,
        alternate_names=("IEFOPSMF",),
    ),
    *(
        _target(name, record_types, generic=False)
        for name, record_types in (
            ("bpxysmfr.h", (92,)),
            ("iecsmf94.h", (94,)),
            ("iwmsmf90.h", (97,)),
            ("iwmsmf97.h", (97,)),
            ("ihahr098.h", (98,)),
            ("ihahr981.h", (98,)),
            ("iggindvx.h", (98,)),
            ("iggindvs.h", (98,)),
            ("iggindbs.h", (98,)),
            ("iggindbx.h", (98,)),
            ("hwismf6a.h", (106,)),
            ("hisysmfr.h", (113,)),
            ("ezasmf.h", (119,)),
            ("iosds124.h", (124,)),
            ("gtzzsmf1.h", (125,)),
            ("ifasmfcn.h", (30, 1154)),
            ("iazs1153.h", (1153,)),
            ("ifar1154.h", (1154,)),
            ("iazs1154.h", (1154,)),
            ("ifas4128.h", (1154,)),
            ("csvs1156.h", (1156,)),
            ("iosds983.h", (98, 983)),
            ("iosds984.h", (98, 984)),
        )
    ),
)

# Extra record-specific parser metadata consumed by tools/smf_build.py.
# Only keep explicit names that cannot be inferred from action payload fields.
_EXPLICIT_SPECIAL_RECORD_STRUCT_NAMES: dict[int, tuple[str, ...]] = {}

SPECIAL_RECORD_ACTIONS = {
    80: (
        {
            "kind": "compact_section_directory_fallback",
            "key": "relocate_sections",
            "anchor_field": "smf80des",
            "relocate_field": "smf80evq",
            "relocate_shift": 1,
            "count_delta": 2,
        },
    ),
    83: (
        {
            "kind": "racf83_subtype1_security",
            "security_struct": "smf83ds1",
            "variable_section_struct": "smf83var",
            "subtype_value": 1,
            "sds_type_value": 3,
            "security_minimum_length": 96,
            "header_integer_fields": (
                ("smf83typ", "read_unsigned_be(data + smf83_subtype_offset, 2)"),
                ("smf83trp", "read_unsigned_be(data + smf83_sds_offset, 2)"),
                ("smf83opd", "read_unsigned_be(data + smf83_sds_offset + 4, 4)"),
                ("smf83lpd", "read_unsigned_be(data + smf83_sds_offset + 8, 2)"),
                ("smf83npd", "read_unsigned_be(data + smf83_sds_offset + 10, 2)"),
                ("smf83od1", "read_unsigned_be(data + smf83_sds_offset + 12, 4)"),
                ("smf83ld1", "read_unsigned_be(data + smf83_sds_offset + 16, 2)"),
                ("smf83nd1", "read_unsigned_be(data + smf83_sds_offset + 18, 2)"),
                ("smf83od2", "read_unsigned_be(data + smf83_sds_offset + 20, 4)"),
                ("smf83ld2", "read_unsigned_be(data + smf83_sds_offset + 24, 2)"),
                ("smf83nd2", "read_unsigned_be(data + smf83_sds_offset + 26, 2)"),
            ),
        },
    ),
    98: (
        {
            "kind": "long_triplet_directory",
            "key": "relocate_sections",
            "directory": "fixed_end",
            "count_field": "smf98sdstripletsnum",
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 1,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_1_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_1_datatripletsnum",
                "smf98_1_datatripletslen",
                "smf98_1_prioritybucketof",
            ),
            "triplet_count_name": "smf98_1_datatripletsnum",
            "triplet_length_name": "smf98_1_datatripletslen",
            "triplet_directory_name": "smf98_1_prioritybucketof",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 3,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_3_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_3_datatripletsnum",
                "smf98_3_datatripletslen",
                "smf98_3_dta_aggbkt1of",
            ),
            "triplet_count_name": "smf98_3_datatripletsnum",
            "triplet_length_name": "smf98_3_datatripletslen",
            "triplet_directory_name": "smf98_3_dta_aggbkt1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 4,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_4_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_4_datatripletsnum",
                "smf98_4_datatripletslen",
                "smf98_4_dta_aggbkt1of",
            ),
            "triplet_count_name": "smf98_4_datatripletsnum",
            "triplet_length_name": "smf98_4_datatripletslen",
            "triplet_directory_name": "smf98_4_dta_aggbkt1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 7,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_7_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_7_datatripletsnum",
                "smf98_7_datatripletslen",
                "smf98_7_bucket1of",
            ),
            "triplet_count_name": "smf98_7_datatripletsnum",
            "triplet_length_name": "smf98_7_datatripletslen",
            "triplet_directory_name": "smf98_7_bucket1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 5,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_5_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_5_datatripletsnum",
                "smf98_5_datatripletslen",
                "smf98_5_bucket1of",
            ),
            "triplet_count_name": "smf98_5_datatripletsnum",
            "triplet_length_name": "smf98_5_datatripletslen",
            "triplet_directory_name": "smf98_5_bucket1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 6,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_6_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_6_datatripletsnum",
                "smf98_6_datatripletslen",
                "smf98_6_bucket1of",
            ),
            "triplet_count_name": "smf98_6_datatripletsnum",
            "triplet_length_name": "smf98_6_datatripletslen",
            "triplet_directory_name": "smf98_6_bucket1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
        {
            "kind": "smf98_subtype_overlay",
            "subtype_value": 8,
            "subtype_field_name": "smf98sty",
            "data_offset_field_name": "smf98dof",
            "subtype_struct": "smf98_8_data",
            "required_record_names": (
                "smf98sty",
                "smf98dof",
            ),
            "required_subtype_names": (
                "smf98_8_datatripletsnum",
                "smf98_8_datatripletslen",
                "smf98_8_bucket1of",
            ),
            "triplet_count_name": "smf98_8_datatripletsnum",
            "triplet_length_name": "smf98_8_datatripletslen",
            "triplet_directory_name": "smf98_8_bucket1of",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 40,
        },
    ),
    119: (
        {
            "kind": "smf119_ident_overlay",
            "triplet_struct": "SMF119SDefSect",
            "ident_struct": "SMF119Ident",
            "triplet_count_field": "SMF119SD_TRN",
            "ident_offset_field": "SMF119IDOff",
            "ident_length_field": "SMF119IDLen",
            "ident_count_field": "SMF119IDNum",
            "triplet_directory_anchor_field": "SMF119S3Off",
            "directory_key": "relocate_sections",
            "skip_ident_fields": ("SMF119TI_rsvd1", "SMF119TI_rsvd2"),
        },
    ),
    1154: (
        {
            "kind": "smf1154_common_overlay",
            "ctrp_struct": "smf1154_ctrp",
            "common_struct": "smf1154_c_hdr",
            "required_ctrp_names": (
                "smf1154_ctrp_trn",
                "smf1154_c_offset",
                "smf1154_c_length",
                "smf1154_c_number",
                "smf1154_subspec_offset",
                "smf1154_subspec_length",
                "smf1154_subspec_number",
            ),
            "common_directory_key": "relocate_sections",
            "subspec_directory_key": "extended_relocate_sections",
        },
        {
            "kind": "smf1154_subtype_overlay",
            "subtype_value": 128,
            "subtype_struct": "smf1154_128",
            "required_names": (
                "smf1154_128_trn",
                "smf1154_128_sds_length",
                "smf1154_128_crypctrs_offset",
                "smf1154_128_crypctrs_length",
                "smf1154_128_crypctrs_number",
            ),
            "triplet_offset_name": "smf1154_128_crypctrs_offset",
            "triplet_length_name": "smf1154_128_crypctrs_length",
            "triplet_number_name": "smf1154_128_crypctrs_number",
            "section_length_name": "smf1154_128_sds_length",
            "directory_key": "extended_relocate_sections",
            "minimum_section_length": 12,
        },
    ),
}


def _derive_special_record_struct_names(
    explicit_names: dict[int, tuple[str, ...]],
    actions: dict[int, tuple[dict[str, object], ...]],
) -> dict[int, tuple[str, ...]]:
    derived: dict[int, set[str]] = {
        record_type: set(names) for record_type, names in explicit_names.items()
    }
    for record_type, action_specs in actions.items():
        names = derived.setdefault(record_type, set())
        for action_spec in action_specs:
            for key in (
                "security_struct",
                "ctrp_struct",
                "common_struct",
                "triplet_struct",
                "ident_struct",
                "subtype_struct",
            ):
                value = action_spec.get(key)
                if isinstance(value, str) and value:
                    names.add(value)
    return {
        record_type: tuple(sorted(names))
        for record_type, names in derived.items()
        if names
    }


SPECIAL_RECORD_STRUCT_NAMES = _derive_special_record_struct_names(
    _EXPLICIT_SPECIAL_RECORD_STRUCT_NAMES,
    SPECIAL_RECORD_ACTIONS,
)

# Optional per-record parser generation behavior toggles.
RECORD_TYPE_OPTIONS = {
    1154: {"allow_empty_fields": True},
}
