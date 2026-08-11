"""Structured record APIs backed by compiled IBM SMF headers."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from os import PathLike
from typing import Any, BinaryIO, Literal

from .datasets import DatasetRecordFormat
from .errors import SMFParseError, SMFRecordTypeSupportError
from .headers import SMFRecordTypeRegistry
from .reader import RecordFormat, SMFHeader, SMFRecord, decode_ebcdic, parse_header

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
StructuredErrorMode = Literal["raise", "skip"]


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
class StructuredSMFRecord:
    """Header-backed fields and variable sections for one SMF record."""

    record_type: int
    fields: dict[str, int | bytes | str]
    sections: tuple[SMFFieldSection, ...] = ()
    extended_sections: tuple[SMFFieldSection, ...] = ()
    raw_fields: dict[str, int | bytes] = field(default_factory=dict)
    source: SMFRecord | None = None

    def __getitem__(self, key: str) -> int | bytes | str:
        return self.fields[key]

    @property
    def header(self) -> SMFHeader | None:
        return self.source.header if self.source is not None else None

    @property
    def offset(self) -> int | None:
        return self.source.offset if self.source is not None else None

    @property
    def subtype(self) -> int | None:
        return self.source.subtype if self.source is not None else None

    @property
    def system_id_text(self) -> str:
        return self.source.header.system_id_text if self.source is not None else ""

    @property
    def subsystem_id_text(self) -> str:
        if self.source is None:
            return ""
        return self.source.header.subsystem_id_text or ""

    def field_text(self, key: str) -> str:
        value = self.fields[key]
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            return decode_ebcdic(value)
        raw_value = self.raw_fields.get(key)
        if isinstance(raw_value, bytes):
            return decode_ebcdic(raw_value)
        raise TypeError(f"SMF field {key!r} is not a text field")

    def clean_field_text(self, key: str) -> str:
        return _clean_decoded_text(self.field_text(key))

    def decoded_fields(self) -> dict[str, str]:
        """Return printable decoded text for all bytes fields in the record."""

        decoded: dict[str, str] = {}
        for key, value in self.fields.items():
            if isinstance(value, str):
                text = value
            elif isinstance(value, bytes):
                text = _clean_decoded_text(decode_ebcdic(value))
                if not _is_plausible_fixed_text(text):
                    continue
            else:
                continue
            if text:
                decoded[key] = text
        return decoded

    def decoded_texts(self) -> tuple[str, ...]:
        """Return decoded printable text from fixed fields and sections."""

        values: list[str] = []
        values.extend(self.decoded_fields().values())
        for section in self.sections:
            text = section.clean_text
            if text:
                values.append(text)
        for section in self.extended_sections:
            text = section.clean_text
            if text:
                values.append(text)
        return tuple(values)

    def find_text(
        self, value: str, *, ignore_case: bool = True, token: bool = False
    ) -> tuple[str, ...]:
        """Find decoded field/section text containing a value or token."""

        if not value:
            return ()
        return tuple(
            text
            for text in self.decoded_texts()
            if _text_matches(text, value, ignore_case=ignore_case, token=token)
        )

    def decoded_tokens(
        self, *, min_length: int = 2, max_length: int = 64
    ) -> tuple[str, ...]:
        """Return alphanumeric/@#$ tokens from decoded fields and sections."""

        values: list[str] = []
        for text in self.decoded_texts():
            for token in _decoded_tokens(
                text, min_length=min_length, max_length=max_length
            ):
                values.append(token)
        return tuple(values)


def parse_record(
    record: SMFRecord | bytes | bytearray | memoryview,
) -> StructuredSMFRecord:
    """Parse a supported SMF record body using its compiled IBM C header."""

    if isinstance(record, SMFRecord):
        data = record.data
        record_type = record.record_type
        source = record
    else:
        data = bytes(record)
        header = parse_header(data)
        record_type = header.record_type
        source = None
    try:
        fields = _native_fields(record_type, data)
    except NotImplementedError as error:
        raise SMFRecordTypeSupportError(
            f"SMF type {record_type} structured parsing requires its IBM C header"
        ) from error
    except ValueError as error:
        raise SMFParseError(str(error)) from error

    structured = _structured_record(record_type, fields, source=source)
    _validate_structured_record(record_type, structured)
    return structured


def parse_records(
    records: Iterable[SMFRecord | bytes | bytearray | memoryview],
    *,
    errors: StructuredErrorMode = "raise",
) -> Iterator[StructuredSMFRecord]:
    """Yield structured records from already-read SMF records or bytes."""

    if errors not in {"raise", "skip"}:
        raise ValueError(f"unsupported structured error mode: {errors!r}")
    for record in records:
        try:
            yield parse_record(record)
        except (SMFRecordTypeSupportError, SMFParseError):
            if errors == "skip":
                continue
            raise


def read_structured_records(
    source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO,
    *,
    record_format: RecordFormat = "auto",
    header_catalog: SMFRecordTypeRegistry | None = None,
    errors: StructuredErrorMode = "raise",
) -> Iterator[StructuredSMFRecord]:
    """Read and parse structured SMF records from bytes, a path, or a stream."""

    from .reader import read_records

    yield from parse_records(
        read_records(
            source,
            record_format=record_format,
            header_catalog=header_catalog,
        ),
        errors=errors,
    )


def read_structured_file(
    path: str | PathLike[str],
    *,
    record_format: RecordFormat = "auto",
    header_catalog: SMFRecordTypeRegistry | None = None,
    errors: StructuredErrorMode = "raise",
) -> Iterator[StructuredSMFRecord]:
    """Read and parse structured SMF records from an unload file path."""

    yield from read_structured_records(
        path,
        record_format=record_format,
        header_catalog=header_catalog,
        errors=errors,
    )


def read_structured_dataset(
    dataset_name: str,
    *,
    record_format: DatasetRecordFormat = "auto",
    skip_short_records: bool = True,
    header_catalog: SMFRecordTypeRegistry | None = None,
    system_ids: Collection[str] | None = None,
    record_types: Collection[int] | None = None,
    records: int = 0,
    offset: int = 0,
    tail: bool = False,
    errors: StructuredErrorMode = "raise",
) -> Iterator[StructuredSMFRecord]:
    """Read and parse structured SMF records directly from a z/OS dataset."""

    from .datasets import read_dataset

    yield from parse_records(
        read_dataset(
            dataset_name,
            record_format=record_format,
            skip_short_records=skip_short_records,
            header_catalog=header_catalog,
            system_ids=system_ids,
            record_types=record_types,
            records=records,
            offset=offset,
            tail=tail,
        ),
        errors=errors,
    )


def _native_fields(record_type: int, data: bytes | bytearray | memoryview):
    native = _native
    parse_native_record = _native_parse_record
    if native is not _loaded_native and native is not None:
        parse_native_record = getattr(native, "parse_record", None)
    if parse_native_record is not None:
        return parse_native_record(record_type, data)
    raise SMFRecordTypeSupportError(
        "structured SMF parsing requires pysmf._native built with generated "
        "IBM header mappings"
    )


def _structured_record(
    record_type: int, fields: dict[str, object], *, source: SMFRecord | None = None
) -> StructuredSMFRecord:
    regular_sections = _sections(fields, "relocate_sections")
    extended_sections = _sections(fields, "extended_relocate_sections")
    scalar_fields: dict[str, int | bytes | str] = {}
    raw_fields: dict[str, int | bytes] = {}
    for key, value in fields.items():
        if key in {"relocate_sections", "extended_relocate_sections"}:
            continue
        if isinstance(value, bytes):
            raw_fields[key] = value
            text = _clean_decoded_text(decode_ebcdic(value))
            scalar_fields[key] = text if _is_plausible_fixed_text(text) else value
        elif isinstance(value, int):
            scalar_fields[key] = value
            raw_fields[key] = value
        else:
            raise TypeError(f"SMF field {key!r} has unsupported value {value!r}")
    return StructuredSMFRecord(
        record_type=record_type,
        fields=scalar_fields,
        sections=regular_sections,
        extended_sections=extended_sections,
        raw_fields=raw_fields,
        source=source,
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
    if len(text) < 2:
        return ""
    return text


def _is_plausible_fixed_text(text: str) -> bool:
    if not text:
        return False
    tokens = _decoded_tokens(text, min_length=1, max_length=64)
    if not tokens:
        return False
    one_character_tokens = sum(1 for token in tokens if len(token) == 1)
    return one_character_tokens * 3 <= len(tokens)


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


def _decoded_tokens(text: str, *, min_length: int, max_length: int) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    for character in text.upper():
        if character in _TOKEN_CHARACTERS:
            current.append(character)
            continue
        _append_decoded_token(tokens, current, min_length, max_length)
    _append_decoded_token(tokens, current, min_length, max_length)
    return tuple(tokens)


def _append_decoded_token(
    tokens: list[str], current: list[str], min_length: int, max_length: int
) -> None:
    if not current:
        return
    token = "".join(current)
    current.clear()
    if min_length <= len(token) <= max_length:
        tokens.append(token)


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
