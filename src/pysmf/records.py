"""Structured record APIs backed by compiled IBM SMF headers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from collections.abc import Iterable, Mapping
from typing import Any

from .errors import HeaderCatalogError, SMFParseError
from .reader import SMFRecord, decode_ebcdic, parse_header

try:
    _native: Any | None = import_module("pysmf._native")
except ImportError:
    _native = None
_loaded_native = _native
_native_parse_record = getattr(_native, "parse_record", None) if _native else None
_PRINTABLE_TEXT = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 #$@._-/():,"
)
_TOKEN_CHARACTERS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$@")


@dataclass(frozen=True, slots=True)
class SMFFieldSection:
    """A variable-length section mapped by an IBM SMF C header."""

    data_type: int
    data: bytes
    offset: int

    @property
    def text(self) -> str:
        return decode_ebcdic(self.data)

    @property
    def clean_text(self) -> str:
        return _clean_decoded_text(self.text)


@dataclass(frozen=True, slots=True)
class SMFDecodedText:
    """Decoded text from a header-backed SMF field or variable section."""

    source: str
    name: str
    text: str
    data_type: int | None = None
    offset: int | None = None


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

    def clean_field_text(self, key: str) -> str:
        return _clean_decoded_text(self.field_text(key))

    def decoded_fields(self) -> dict[str, str]:
        """Return printable decoded text for all bytes fields in the record."""

        decoded: dict[str, str] = {}
        for key, value in self.fields.items():
            if not isinstance(value, bytes):
                continue
            text = _clean_decoded_text(decode_ebcdic(value))
            if text:
                decoded[key] = text
        return decoded

    def decoded_texts(self) -> tuple[SMFDecodedText, ...]:
        """Return decoded printable text from fixed fields and sections."""

        values: list[SMFDecodedText] = []
        for key, text in self.decoded_fields().items():
            values.append(SMFDecodedText(source="field", name=key, text=text))
        for section in self.sections:
            text = section.clean_text
            if text:
                values.append(
                    SMFDecodedText(
                        source="section",
                        name="relocate_sections",
                        text=text,
                        data_type=section.data_type,
                        offset=section.offset,
                    )
                )
        for section in self.extended_sections:
            text = section.clean_text
            if text:
                values.append(
                    SMFDecodedText(
                        source="extended_section",
                        name="extended_relocate_sections",
                        text=text,
                        data_type=section.data_type,
                        offset=section.offset,
                    )
                )
        return tuple(values)

    def find_text(
        self, value: str, *, ignore_case: bool = True, token: bool = False
    ) -> tuple[SMFDecodedText, ...]:
        """Find decoded field/section text containing a value or token."""

        if not value:
            return ()
        return tuple(
            decoded
            for decoded in self.decoded_texts()
            if _text_matches(decoded.text, value, ignore_case=ignore_case, token=token)
        )


def parse_record(
    record: SMFRecord | bytes | bytearray | memoryview,
) -> StructuredSMFRecord:
    """Parse a supported SMF record body using its compiled IBM C header."""

    if isinstance(record, SMFRecord):
        data = record.data
        record_type = record.record_type
    else:
        data = bytes(record)
        header = parse_header(data)
        record_type = header.record_type
    try:
        fields = _native_fields(record_type, data)
    except NotImplementedError as error:
        raise HeaderCatalogError(
            f"SMF type {record_type} structured parsing requires its IBM C header"
        ) from error
    except ValueError as error:
        raise SMFParseError(str(error)) from error

    structured = _structured_record(record_type, fields)
    _validate_structured_record(record_type, structured)
    return structured


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
        elif isinstance(value, int):
            scalar_fields[key] = value
        else:
            raise TypeError(f"SMF field {key!r} has unsupported value {value!r}")
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


def _clean_decoded_text(value: str) -> str:
    cleaned = "".join(
        character if character in _PRINTABLE_TEXT else " " for character in value
    )
    text = " ".join(cleaned.strip().split())
    if len(text) < 2 or text.isdigit():
        return ""
    return text


def _text_matches(
    text: str, value: str, *, ignore_case: bool, token: bool
) -> bool:
    haystack = text.upper() if ignore_case else text
    needle = value.upper() if ignore_case else value
    if not token:
        return needle in haystack
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        before_index = index - 1
        after_index = index + len(needle)
        before_ok = (
            before_index < 0 or haystack[before_index].upper() not in _TOKEN_CHARACTERS
        )
        after_ok = (
            after_index >= len(haystack)
            or haystack[after_index].upper() not in _TOKEN_CHARACTERS
        )
        if before_ok and after_ok:
            return True
        start = index + 1


def _validate_structured_record(
    record_type: int, structured: StructuredSMFRecord
) -> None:
    type_field = f"smf{record_type}rty"
    if type_field not in structured.fields:
        return
    parsed_type = structured.fields[type_field]
    if parsed_type != record_type:
        raise SMFParseError(
            f"SMF type {record_type} structured parser returned record type "
            f"{parsed_type}; rebuild pysmf so generated IBM header offsets match"
        )


def _sections(
    fields: dict[str, object], key: str
) -> tuple[SMFFieldSection, ...]:
    sections = fields.get(key, ())
    if not isinstance(sections, Iterable):
        raise TypeError(f"SMF section field {key!r} is not iterable")
    return tuple(
        SMFFieldSection(
            data_type=_section_int(section, "data_type"),
            data=_section_bytes(section, "data"),
            offset=_section_int(section, "offset"),
        )
        for section in sections
    )


def _section_int(section: object, key: str) -> int:
    value = _section_value(section, key)
    if not isinstance(value, int):
        raise TypeError(f"SMF section {key!r} is not an integer: {value!r}")
    return value


def _section_bytes(section: object, key: str) -> bytes:
    value = _section_value(section, key)
    if not isinstance(value, bytes):
        raise TypeError(f"SMF section {key!r} is not bytes: {value!r}")
    return value


def _section_value(section: object, key: str) -> object:
    if not isinstance(section, Mapping):
        raise TypeError(f"SMF section entry is not a mapping: {section!r}")
    return section[key]
