"""Structured record APIs backed by compiled IBM SMF headers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from .errors import HeaderCatalogError, SMFParseError
from .reader import SMFRecord, decode_ebcdic, parse_header

try:
    _native: Any | None = import_module("pysmf._native")
except ImportError:
    _native = None
_loaded_native = _native
_native_parse_record = getattr(_native, "parse_record", None) if _native else None


@dataclass(frozen=True, slots=True)
class SMFFieldSection:
    """A variable-length section mapped by an IBM SMF C header."""

    data_type: int
    data: bytes
    offset: int

    @property
    def text(self) -> str:
        return decode_ebcdic(self.data)


@dataclass(frozen=True, slots=True)
class StructuredSMFRecord:
    """Header-backed fields and variable sections for one SMF record."""

    record_type: int
    fields: dict[str, int | bytes]
    sections: tuple[SMFFieldSection, ...] = ()
    extended_sections: tuple[SMFFieldSection, ...] = ()

    def __getitem__(self, key: str) -> int | bytes:
        return self.fields[key]

    def field_text(self, key: str) -> str:
        return decode_ebcdic(_bytes_field(self.fields, key))


def parse_record(
    record: SMFRecord | bytes | bytearray | memoryview,
) -> StructuredSMFRecord:
    """Parse a supported SMF record body using its compiled IBM C header."""

    data = record.data if isinstance(record, SMFRecord) else bytes(record)
    record_type = (
        record.record_type
        if isinstance(record, SMFRecord)
        else parse_header(data).record_type
    )
    try:
        fields = _native_fields(record_type, data)
    except NotImplementedError as error:
        raise HeaderCatalogError(
            f"SMF type {record_type} structured parsing requires its IBM C header"
        ) from error
    except ValueError as error:
        raise SMFParseError(str(error)) from error

    return _structured_record(record_type, fields)


def _native_fields(record_type: int, data: bytes | bytearray | memoryview):
    native = _native
    parse_native_record = _native_parse_record
    if native is not _loaded_native and native is not None:
        parse_native_record = getattr(native, "parse_record", None)
    if parse_native_record is not None:
        return parse_native_record(record_type, data)
    raise HeaderCatalogError(
        "structured SMF parsing requires pysmf._native built with generated "
        "IBM header mappings"
    )


def _structured_record(
    record_type: int, fields: dict[str, object]
) -> StructuredSMFRecord:
    regular_sections = _sections(fields, "relocate_sections")
    extended_sections = _sections(fields, "extended_relocate_sections")
    scalar_fields: dict[str, int | bytes] = {}
    for key, value in fields.items():
        if key in {"relocate_sections", "extended_relocate_sections"}:
            continue
        if isinstance(value, bytes):
            scalar_fields[key] = value
        else:
            scalar_fields[key] = int(value)
    return StructuredSMFRecord(
        record_type=record_type,
        fields=scalar_fields,
        sections=regular_sections,
        extended_sections=extended_sections,
    )


def _bytes_field(fields: dict[str, int | bytes], key: str) -> bytes:
    value = fields[key]
    if isinstance(value, bytes):
        return value
    raise TypeError(f"SMF field {key!r} is not a bytes field")


def _sections(
    fields: dict[str, object], key: str
) -> tuple[SMFFieldSection, ...]:
    return tuple(
        SMFFieldSection(
            data_type=int(section["data_type"]),
            data=bytes(section["data"]),
            offset=int(section["offset"]),
        )
        for section in fields.get(key, ())
    )
