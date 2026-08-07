"""Read SMF unload streams and parse standard SMF headers."""

from __future__ import annotations

import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import BinaryIO, Literal

from .errors import HeaderCatalogError, SMFParseError, TruncatedSMFRecord
from .headers import HeaderCatalog, HeaderDefinition

try:
    from . import _native
except ImportError:
    _native = None

RecordFormat = Literal["auto", "smf", "rdw"]

_MIN_RECORD_LENGTH = 18
_MAX_RECORD_LENGTH = 32756
_STANDARD_HEADER_LENGTH = 24
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
    header_definitions: tuple[HeaderDefinition, ...] = ()

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
    def c_headers(self) -> tuple[HeaderDefinition, ...]:
        """C header definitions that appear to map this record type."""

        return self.header_definitions


def decode_ebcdic(value: bytes, *, encoding: str = "cp037") -> str:
    """Decode a fixed-width EBCDIC field and strip EBCDIC spaces and NULs."""

    return value.rstrip(b"\x40\x00").decode(encoding, errors="replace")


def parse_header(data: bytes | bytearray | memoryview, *, offset: int = 0) -> SMFHeader:
    """Parse the standard SMF header from a record byte string."""

    if _native is not None:
        return _parse_header_native(data, offset=offset)

    return _parse_header_python(data, offset=offset)


def _parse_header_native(data: bytes | bytearray | memoryview, *, offset: int) -> SMFHeader:
    try:
        fields = _native.parse_header(data)
    except EOFError as error:
        raise TruncatedSMFRecord(str(error), offset=offset) from error
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


def _parse_header_python(data: bytes | bytearray | memoryview, *, offset: int = 0) -> SMFHeader:
    """Source-tree fallback for environments where the native extension is not built."""

    view = memoryview(data)
    if len(view) < _MIN_RECORD_LENGTH:
        raise TruncatedSMFRecord(
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
        raise TruncatedSMFRecord(
            f"SMF record declares {length} bytes but only {len(view)} are available",
            offset=offset,
        )

    segment_descriptor = struct.unpack_from(">H", view, 2)[0]
    flags = view[4]
    record_type_indicator = view[5]
    time_hundredths = struct.unpack_from(">i", view, 6)[0]
    date = bytes(view[10:14])
    system_id = bytes(view[14:18])
    subsystem_id: bytes | None = None
    subtype: int | None = None
    header_length = _MIN_RECORD_LENGTH

    if length >= _STANDARD_HEADER_LENGTH and len(view) >= _STANDARD_HEADER_LENGTH:
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
            if len(view) >= candidate_header_length and length >= candidate_header_length:
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
    header_catalog: HeaderCatalog | None = None,
) -> Iterator[SMFRecord]:
    """Yield SMF records from bytes, a path, or a binary file object.

    ``record_format="smf"`` reads records whose first two bytes are the SMF
    record length. ``record_format="rdw"`` reads an external four-byte RDW first
    and then parses the SMF record in the payload. ``auto`` chooses between those
    two forms from the first bytes of the stream.
    """

    catalog = _require_header_catalog(header_catalog)
    with _open_binary(source) as stream:
        selected_format = _detect_format(stream) if record_format == "auto" else record_format
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
    header_catalog: HeaderCatalog | None = None,
) -> Iterator[SMFRecord]:
    """Yield SMF records from an unload file path."""

    yield from read_records(path, record_format=record_format, header_catalog=header_catalog)


@contextmanager
def _open_binary(source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO) -> Iterator[BinaryIO]:
    if isinstance(source, bytes | bytearray | memoryview):
        yield BytesIO(bytes(source))
    elif isinstance(source, str | PathLike):
        with Path(source).open("rb") as stream:
            yield stream
    else:
        yield source


def _detect_format(stream: BinaryIO) -> Literal["smf", "rdw"]:
    if not stream.seekable():
        raise ValueError("record_format='auto' requires a seekable stream; pass 'smf' or 'rdw' for streaming input")

    position = stream.tell()
    peek = stream.read(8)
    stream.seek(position)

    if len(peek) < 4:
        return "smf"

    first_length = struct.unpack_from(">H", peek, 0)[0]
    if len(peek) >= 6:
        payload_length = struct.unpack_from(">H", peek, 4)[0]
        if first_length >= 4 and _MIN_RECORD_LENGTH <= payload_length <= first_length - 4:
            return "rdw"
    return "smf"


def _read_smf_records(stream: BinaryIO, *, header_catalog: HeaderCatalog) -> Iterator[SMFRecord]:
    offset = stream.tell() if stream.seekable() else 0
    while True:
        prefix = stream.read(4)
        if not prefix:
            return
        if len(prefix) != 4:
            raise TruncatedSMFRecord("incomplete SMF record prefix", offset=offset)
        length = struct.unpack_from(">H", prefix, 0)[0]
        length = length & 0x7FFF if length & 0x8000 else length
        if not _MIN_RECORD_LENGTH <= length <= _MAX_RECORD_LENGTH:
            raise SMFParseError(f"SMF record declares invalid length {length}", offset=offset)
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


def _read_external_rdw_records(stream: BinaryIO, *, header_catalog: HeaderCatalog) -> Iterator[SMFRecord]:
    offset = stream.tell() if stream.seekable() else 0
    while True:
        rdw_bytes = stream.read(4)
        if not rdw_bytes:
            return
        if len(rdw_bytes) != 4:
            raise TruncatedSMFRecord("incomplete external RDW", offset=offset)
        rdw_length, rdw_segment = struct.unpack(">HH", rdw_bytes)
        if rdw_length < 4:
            raise SMFParseError(f"external RDW declares invalid length {rdw_length}", offset=offset)
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


def _require_header_catalog(header_catalog: HeaderCatalog | None) -> HeaderCatalog:
    catalog = HeaderCatalog.discover() if header_catalog is None else header_catalog
    if not catalog.headers:
        raise HeaderCatalogError(f"no z/OS C headers found in {catalog.include_dir}")
    return catalog


def _definitions_for_record(catalog: HeaderCatalog, header: SMFHeader) -> tuple[HeaderDefinition, ...]:
    definitions = catalog.for_record_type(header.record_type)
    if not definitions:
        raise HeaderCatalogError(f"no z/OS C header definition found for SMF record type {header.record_type}")
    return definitions


def _read_exact(stream: BinaryIO, length: int, *, offset: int) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise TruncatedSMFRecord(f"expected {length} bytes but only read {len(data)}", offset=offset)
    return data
