"""Read SMF unload streams and parse standard SMF headers."""

from __future__ import annotations

import struct
from codecs import lookup
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any, BinaryIO, Literal

from .errors import SMFParseError, SMFRecordTypeSupportError, TruncatedSMFRecordError
from .headers import SMFRecordTypeDefinition, SMFRecordTypeRegistry

try:
    _native: Any | None = import_module("pysmf._native")
except ImportError:
    _native = None
_loaded_native = _native
_native_parse_header = getattr(_native, "parse_header", None) if _native else None
_native_decode_smf_time_hundredths = (
    getattr(_native, "decode_smf_time_hundredths", None) if _native else None
)
_native_is_packed_smf_date = (
    getattr(_native, "is_packed_smf_date", None) if _native else None
)

RecordFormat = Literal["auto", "smf", "rdw"]

_MIN_RECORD_LENGTH = 18
_MAX_RECORD_LENGTH = 32756
_STANDARD_HEADER_LENGTH = 24
_DATE_FIRST_HEADER_LENGTH = 20
_EXTENDED_RECORD_INDICATOR = 126
_SUBTYPE_VALID_FLAG = 0x40
_EXTENDED_HEADER_FLAG = 0x20


@dataclass(frozen=True, slots=True)
class ExternalRDW:
    """A record descriptor word that prefixes a downloaded variable record."""

    length: int
    segment_descriptor: int


@dataclass(frozen=True, slots=True)
class SMFHeader:
    """The standard SMF record header, including extended record metadata."""

    length: int
    raw_length: int
    segment_descriptor: int
    flags: int
    record_type_indicator: int
    time_hundredths: int
    date: bytes
    system_id: bytes
    subsystem_id: bytes | None
    subtype: int | None
    header_length: int
    extended_header_length: int | None = None
    extended_version: int | None = None
    extended_flags: int | None = None
    extended_record_type: int | None = None

    @property
    def record_type(self) -> int:
        """The effective SMF record type, resolving extended type 126 headers."""

        return self.extended_record_type or self.record_type_indicator

    @property
    def has_subtype(self) -> bool:
        """Whether the SMF header flag says the subtype field is meaningful."""

        return bool(self.flags & _SUBTYPE_VALID_FLAG)

    @property
    def has_extended_header(self) -> bool:
        """Whether the SMF header flag says an extended header is present."""

        return bool(self.flags & _EXTENDED_HEADER_FLAG)

    @property
    def system_id_text(self) -> str:
        return decode_ebcdic(self.system_id)

    @property
    def subsystem_id_text(self) -> str | None:
        if self.subsystem_id is None:
            return None
        return decode_ebcdic(self.subsystem_id)


@dataclass(frozen=True, slots=True)
class SMFRecord:
    """A single SMF record and its parsed header."""

    data: bytes
    header: SMFHeader
    offset: int
    rdw: ExternalRDW | None = None
    header_definitions: tuple[SMFRecordTypeDefinition, ...] = ()

    @property
    def record_type(self) -> int:
        return self.header.record_type

    @property
    def subtype(self) -> int | None:
        return self.header.subtype

    @property
    def body(self) -> bytes:
        """Record bytes after the parsed SMF header."""

        return self.data[self.header.header_length :]

    @property
    def c_headers(self) -> tuple[SMFRecordTypeDefinition, ...]:
        """C header definitions that appear to map this record type."""

        return self.header_definitions


def decode_ebcdic(value: bytes, *, encoding: str = "cp1047") -> str:
    """Decode a fixed-width EBCDIC field and strip EBCDIC spaces and NULs."""

    return value.rstrip(b"\x40\x00").decode(
        _available_ebcdic_encoding(encoding), errors="replace"
    )


@cache
def _available_ebcdic_encoding(encoding: str) -> str:
    try:
        lookup(encoding)
    except LookupError:
        if encoding.lower().replace("-", "") == "cp1047":
            return "cp037"
        raise
    return encoding


def decode_smf_time_hundredths(value: bytes | bytearray | memoryview) -> int:
    """Decode an SMF time field to hundredths of a second after midnight."""

    data = bytes(value)
    if len(data) == 4:
        native_decode = _native_decode_smf_time_hundredths
        native = _native
        if native is not _loaded_native and native is not None:
            native_decode = getattr(native, "decode_smf_time_hundredths", None)
        if native_decode is not None:
            return native_decode(data)
        first = data[0]
        second = data[1]
        third = data[2]
        fourth = data[3]
        sign = fourth & 0x0F
        if sign in (0x0C, 0x0D, 0x0F):
            hours_tens = first >> 4
            hours_ones = first & 0x0F
            minutes_tens = second >> 4
            minutes_ones = second & 0x0F
            seconds_tens = third >> 4
            seconds_ones = third & 0x0F
            tenths = fourth >> 4
            if (
                hours_tens <= 9
                and hours_ones <= 9
                and minutes_tens <= 9
                and minutes_ones <= 9
                and seconds_tens <= 9
                and seconds_ones <= 9
                and tenths <= 9
            ):
                hours = hours_tens * 10 + hours_ones
                minutes = minutes_tens * 10 + minutes_ones
                seconds = seconds_tens * 10 + seconds_ones
                if hours <= 23 and minutes <= 59 and seconds <= 59:
                    return ((hours * 60 + minutes) * 60 + seconds) * 100 + tenths * 10
    return struct.unpack(">i", data)[0]


def is_packed_smf_date(value: bytes | bytearray | memoryview) -> bool:
    """Return whether bytes look like an SMF packed date, 0cyydddF."""

    data = bytes(value)
    if len(data) != 4:
        return False
    native_check = _native_is_packed_smf_date
    native = _native
    if native is not _loaded_native and native is not None:
        native_check = getattr(native, "is_packed_smf_date", None)
    if native_check is not None:
        return native_check(data)
    first = data[0]
    second = data[1]
    third = data[2]
    fourth = data[3]
    if fourth & 0x0F != 0x0F:
        return False
    year_high = second >> 4
    year_low = second & 0x0F
    day_hundreds = third >> 4
    day_tens = third & 0x0F
    day_ones = fourth >> 4
    if (
        first >> 4 > 9
        or first & 0x0F > 9
        or year_high > 9
        or year_low > 9
        or day_hundreds > 9
        or day_tens > 9
        or day_ones > 9
    ):
        return False
    day_of_year = day_hundreds * 100 + day_tens * 10 + day_ones
    return 1 <= day_of_year <= 366


def parse_header(data: bytes | bytearray | memoryview, *, offset: int = 0) -> SMFHeader:
    """Parse the standard SMF header from a record byte string."""

    native_parse_header = _native_parse_header
    native = _native
    if native is not _loaded_native and native is not None:
        native_parse_header = getattr(native, "parse_header")
    if native_parse_header is not None:
        return _parse_header_native(native_parse_header, data, offset=offset)

    return _parse_header_python(data, offset=offset)


def _parse_header_native(
    native_parse_header: Any, data: bytes | bytearray | memoryview, *, offset: int
) -> SMFHeader:
    try:
        fields = native_parse_header(data)
    except EOFError as error:
        raise TruncatedSMFRecordError(str(error), offset=offset) from error
    except ValueError as error:
        raise SMFParseError(str(error), offset=offset) from error

    return SMFHeader(
        length=fields[0],
        raw_length=fields[1],
        segment_descriptor=fields[2],
        flags=fields[3],
        record_type_indicator=fields[4],
        time_hundredths=fields[5],
        date=fields[6],
        system_id=fields[7],
        subsystem_id=fields[8],
        subtype=fields[9],
        header_length=fields[10],
        extended_header_length=fields[11],
        extended_version=fields[12],
        extended_flags=fields[13],
        extended_record_type=fields[14],
    )


def _parse_header_python(
    data: bytes | bytearray | memoryview, *, offset: int = 0
) -> SMFHeader:
    """Source-tree fallback for environments where the native extension is not built."""

    view = memoryview(data)
    if len(view) < _MIN_RECORD_LENGTH:
        raise TruncatedSMFRecordError(
            f"SMF record is shorter than the minimum {_MIN_RECORD_LENGTH}-byte header",
            offset=offset,
        )

    raw_length = struct.unpack_from(">H", view, 0)[0]
    length = raw_length & 0x7FFF if raw_length & 0x8000 else raw_length
    if not _MIN_RECORD_LENGTH <= length <= _MAX_RECORD_LENGTH:
        raise SMFParseError(
            f"SMF record declares invalid length {length}",
            offset=offset,
        )
    if len(view) < length:
        raise TruncatedSMFRecordError(
            f"SMF record declares {length} bytes but only {len(view)} are available",
            offset=offset,
        )

    segment_descriptor = struct.unpack_from(">H", view, 2)[0]
    flags = view[4]
    record_type_indicator = view[5]
    date_first_header = not is_packed_smf_date(view[10:14]) and is_packed_smf_date(
        view[6:10]
    )
    if date_first_header:
        time_hundredths = 0
        date = bytes(view[6:10])
        system_id = bytes(view[10:14])
    else:
        time_hundredths = decode_smf_time_hundredths(view[6:10])
        date = bytes(view[10:14])
        system_id = bytes(view[14:18])
    subsystem_id: bytes | None = None
    subtype: int | None = None
    header_length = _MIN_RECORD_LENGTH

    if (
        date_first_header
        and length >= _DATE_FIRST_HEADER_LENGTH
        and len(view) >= _DATE_FIRST_HEADER_LENGTH
    ):
        subsystem_id = bytes(view[14:18])
        if flags & _SUBTYPE_VALID_FLAG:
            subtype = struct.unpack_from(">H", view, 18)[0]
        header_length = _DATE_FIRST_HEADER_LENGTH
    elif length >= _STANDARD_HEADER_LENGTH and len(view) >= _STANDARD_HEADER_LENGTH:
        subsystem_id = bytes(view[18:22])
        if flags & _SUBTYPE_VALID_FLAG:
            subtype = struct.unpack_from(">H", view, 22)[0]
        header_length = _STANDARD_HEADER_LENGTH

    extended_header_length: int | None = None
    extended_version: int | None = None
    extended_flags: int | None = None
    extended_record_type: int | None = None
    if (
        record_type_indicator == _EXTENDED_RECORD_INDICATOR
        and flags & _EXTENDED_HEADER_FLAG
        and length >= 56
        and len(view) >= 56
    ):
        candidate_ext_length = struct.unpack_from(">H", view, 24)[0]
        candidate_version = view[26]
        if candidate_version in (1, 2) and candidate_ext_length in (32, 68):
            candidate_header_length = _STANDARD_HEADER_LENGTH + candidate_ext_length
            if (
                len(view) >= candidate_header_length
                and length >= candidate_header_length
            ):
                extended_header_length = candidate_ext_length
                extended_version = candidate_version
                extended_flags = view[27]
                extended_record_type = struct.unpack_from(">H", view, 52)[0]
                header_length = candidate_header_length

    return SMFHeader(
        length=length,
        raw_length=raw_length,
        segment_descriptor=segment_descriptor,
        flags=flags,
        record_type_indicator=record_type_indicator,
        time_hundredths=time_hundredths,
        date=date,
        system_id=system_id,
        subsystem_id=subsystem_id,
        subtype=subtype,
        header_length=header_length,
        extended_header_length=extended_header_length,
        extended_version=extended_version,
        extended_flags=extended_flags,
        extended_record_type=extended_record_type,
    )


def read_records(
    source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO,
    *,
    record_format: RecordFormat = "auto",
    header_catalog: SMFRecordTypeRegistry | None = None,
) -> Iterator[SMFRecord]:
    """Yield SMF records from bytes, a path, or a binary file object.

    ``record_format="smf"`` reads records whose first two bytes are the SMF
    record length. ``record_format="rdw"`` reads an external four-byte RDW first
    and then parses the SMF record in the payload. ``auto`` chooses between those
    two forms from the first bytes of the stream.
    """

    catalog = _require_header_catalog(header_catalog)
    with _open_binary(source) as stream:
        selected_format = (
            _detect_format(stream) if record_format == "auto" else record_format
        )
        if selected_format == "smf":
            yield from _read_smf_records(stream, header_catalog=catalog)
        elif selected_format == "rdw":
            yield from _read_external_rdw_records(stream, header_catalog=catalog)
        else:
            raise ValueError(f"unsupported SMF record format: {record_format!r}")


def read_file(
    path: str | PathLike[str],
    *,
    record_format: RecordFormat = "auto",
    header_catalog: SMFRecordTypeRegistry | None = None,
) -> Iterator[SMFRecord]:
    """Yield SMF records from an unload file path."""

    yield from read_records(
        path, record_format=record_format, header_catalog=header_catalog
    )


@contextmanager
def _open_binary(
    source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO,
) -> Iterator[BinaryIO]:
    if isinstance(source, bytes | bytearray | memoryview):
        yield BytesIO(bytes(source))
    elif isinstance(source, str | PathLike):
        with Path(source).open("rb") as stream:
            yield stream
    else:
        yield source


def _detect_format(stream: BinaryIO) -> Literal["smf", "rdw"]:
    if not stream.seekable():
        raise ValueError(
            "record_format='auto' requires a seekable stream; pass 'smf' "
            "or 'rdw' for streaming input"
        )

    position = stream.tell()
    peek = stream.read(8)
    stream.seek(position)

    if len(peek) < 4:
        return "smf"

    first_length = struct.unpack_from(">H", peek, 0)[0]
    if len(peek) >= 6:
        payload_length = struct.unpack_from(">H", peek, 4)[0]
        if (
            first_length >= 4
            and _MIN_RECORD_LENGTH <= payload_length <= first_length - 4
        ):
            return "rdw"
    return "smf"


def _read_smf_records(
    stream: BinaryIO, *, header_catalog: SMFRecordTypeRegistry
) -> Iterator[SMFRecord]:
    offset = stream.tell() if stream.seekable() else 0
    while True:
        prefix = stream.read(4)
        if not prefix:
            return
        if len(prefix) != 4:
            raise TruncatedSMFRecordError("incomplete SMF record prefix", offset=offset)
        length = struct.unpack_from(">H", prefix, 0)[0]
        length = length & 0x7FFF if length & 0x8000 else length
        if not _MIN_RECORD_LENGTH <= length <= _MAX_RECORD_LENGTH:
            raise SMFParseError(
                f"SMF record declares invalid length {length}", offset=offset
            )
        payload = _read_exact(stream, length - 4, offset=offset)
        data = prefix + payload
        header = parse_header(data, offset=offset)
        header_definitions = _definitions_for_record(header_catalog, header)
        yield SMFRecord(
            data=data,
            header=header,
            offset=offset,
            header_definitions=header_definitions,
        )
        offset += length


def _read_external_rdw_records(
    stream: BinaryIO, *, header_catalog: SMFRecordTypeRegistry
) -> Iterator[SMFRecord]:
    offset = stream.tell() if stream.seekable() else 0
    while True:
        rdw_bytes = stream.read(4)
        if not rdw_bytes:
            return
        if len(rdw_bytes) != 4:
            raise TruncatedSMFRecordError("incomplete external RDW", offset=offset)
        rdw_length, rdw_segment = struct.unpack(">HH", rdw_bytes)
        if rdw_length < 4:
            raise SMFParseError(
                f"external RDW declares invalid length {rdw_length}", offset=offset
            )
        data = _read_exact(stream, rdw_length - 4, offset=offset + 4)
        header = parse_header(data, offset=offset + 4)
        header_definitions = _definitions_for_record(header_catalog, header)
        yield SMFRecord(
            data=data,
            header=header,
            offset=offset + 4,
            rdw=ExternalRDW(length=rdw_length, segment_descriptor=rdw_segment),
            header_definitions=header_definitions,
        )
        offset += rdw_length


def _require_header_catalog(
    header_catalog: SMFRecordTypeRegistry | None,
) -> SMFRecordTypeRegistry:
    catalog = (
        SMFRecordTypeRegistry.discover() if header_catalog is None else header_catalog
    )
    if not catalog.headers:
        raise SMFRecordTypeSupportError(
            f"no SMF record type support found in {catalog.include_dir}"
        )
    return catalog


def _definitions_for_record(
    catalog: SMFRecordTypeRegistry, header: SMFHeader
) -> tuple[SMFRecordTypeDefinition, ...]:
    definitions = catalog.for_record_type(header.record_type)
    if not definitions:
        raise SMFRecordTypeSupportError(
            "no structured support found for SMF record type "
            f"{header.record_type}"
        )
    return definitions


def _read_exact(stream: BinaryIO, length: int, *, offset: int) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise TruncatedSMFRecordError(
            f"expected {length} bytes but only read {len(data)}", offset=offset
        )
    return data
