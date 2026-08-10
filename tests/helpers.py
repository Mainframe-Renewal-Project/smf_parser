from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

from smf_parser import HeaderCatalog, HeaderDefinition

try:
    "".encode("cp1047")
except LookupError:
    EBCDIC_TEST_ENCODING = "cp037"
else:
    EBCDIC_TEST_ENCODING = "cp1047"


def ebcdic(value: str) -> bytes:
    return value.encode(EBCDIC_TEST_ENCODING)


def standard_record(
    record_type: int,
    *,
    subtype: int = 0,
    system_id: str = "SYS1",
    date: bytes = b"\x00\x20\x23\x1f",
    body: bytes = b"",
) -> bytes:
    length = 24 + len(body)
    return (
        struct.pack(
            ">HHBBi4s4s4sH",
            length,
            0,
            0x40,
            record_type,
            12_345,
            date,
            ebcdic(system_id),
            ebcdic("SMF "),
            subtype,
        )
        + body
    )


def vbs_block(*segments: tuple[int, bytes], trailing: bytes = b"") -> bytes:
    encoded_segments = b"".join(
        struct.pack(">HBB", len(data) + 4, control, 0) + data
        for control, data in segments
    )
    block = struct.pack(">HH", len(encoded_segments) + 4, 0) + encoded_segments
    return block + trailing


def vbs_segment(control: int, data: bytes) -> bytes:
    return struct.pack(">HBB", len(data) + 4, control, 0) + data


def header_catalog(*record_types: int) -> HeaderCatalog:
    include_dir = Path("/compiled/zos")
    return HeaderCatalog(
        include_dir=include_dir,
        headers=(
            HeaderDefinition(
                name="ifasmfr.h",
                path=include_dir / "ifasmfr.h",
                record_types=record_types,
                generic=False,
            ),
        ),
    )


def fail_read_as_bytes(*_args, **_kwargs) -> None:
    raise AssertionError("read_as_bytes should not be called for VBS datasets")


def native_reader(records: list[bytes]) -> SimpleNamespace:
    def read_vbs_dataset(_dataset_name: str, **_kwargs) -> list[bytes]:
        return records

    return SimpleNamespace(read_vbs_dataset=read_vbs_dataset)


def vbs_import_module_side_effect(
    native: SimpleNamespace | None = None,
    *,
    generation_count: int = 1,
):
    fake_datasets = SimpleNamespace(
        list_datasets=lambda _pattern: [],
        read_as_bytes=fail_read_as_bytes,
    )
    fake_gdgs = SimpleNamespace(
        GenerationDataGroupView=lambda base: SimpleNamespace(
            generations=[
                SimpleNamespace(name=f"{base}.G{index:04d}V00", record_format="VBS")
                for index in range(1, generation_count + 1)
            ]
        )
    )

    def import_module_side_effect(name: str):
        if name == "zoautil_py.datasets":
            return fake_datasets
        if name == "zoautil_py.gdgs":
            return fake_gdgs
        if name == "smf_parser._native" and native is not None:
            return native
        raise ImportError(name)

    return import_module_side_effect
