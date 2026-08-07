"""Optional ZOAU integration for reading SMF unloads from z/OS datasets."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from importlib import import_module
from typing import Literal

from .errors import SMFParseError, ZOAUMissingError
from .reader import (
    ExternalRDW,
    RecordFormat,
    SMFHeader,
    SMFRecord,
    parse_header,
    read_records,
)

DatasetRecordFormat = Literal["auto", "smf", "rdw"]
_MIN_SMF_RECORD_LENGTH = 18
_MAX_SMF_RECORD_LENGTH = 32756
_MAX_SMF_TIME_HUNDREDTHS = 24 * 60 * 60 * 100
_SMF_TYPE_0_LENGTHS = frozenset((74, 82, 87))


def read_dataset(
    dataset_name: str,
    *,
    record_format: DatasetRecordFormat = "auto",
    skip_short_records: bool = True,
    records: int = 0,
    offset: int = 0,
    tail: bool = False,
) -> Iterator[SMFRecord]:
    """Yield SMF records from a z/OS dataset using ZOAU when available.

    ZOAU is imported lazily because it is distributed with z/OS tooling rather
    than PyPI. The dataset is read with ``zoautil_py.datasets.read_as_bytes``.
    """

    datasets = _zoau_datasets_module()
    dataset_records = datasets.read_as_bytes(dataset_name, records=records, offset=offset, tail=tail)
    yield from read_dataset_records(
        dataset_records,
        record_format=record_format,
        skip_short_records=skip_short_records,
    )


def read_dataset_records(
    records: Iterable[bytes],
    *,
    record_format: DatasetRecordFormat = "auto",
    skip_short_records: bool = True,
) -> Iterator[SMFRecord]:
    """Yield SMF records from dataset records returned by ZOAU.

    ``zoautil_py.datasets.read_as_bytes`` returns one ``bytes`` value per dataset
    record. Depending on how the unload was produced, those bytes may already be
    the SMF record or may still include an external RDW.

    Short records cannot contain the minimum SMF header. They are skipped by
    default because some dataset reads can expose non-SMF physical/control
    records before the logical SMF payload. Set ``skip_short_records=False`` to
    fail on them instead.
    """

    if record_format in ("auto", "smf"):
        yield from _read_smf_dataset_records(
            records,
            record_format=record_format,
            skip_short_records=skip_short_records,
        )
        return

    if record_format != "rdw":
        raise ValueError(f"unsupported dataset record format: {record_format!r}")

    logical_offset = 0
    for data in records:
        if skip_short_records and len(data) < _MIN_SMF_RECORD_LENGTH:
            logical_offset += len(data)
            continue
        yield from _read_one_rdw_dataset_record(data, logical_offset=logical_offset)
        logical_offset += len(data)


def _zoau_datasets_module():
    try:
        return import_module("zoautil_py.datasets")
    except ImportError as error:
        raise ZOAUMissingError(
            "ZOAU is required to read z/OS datasets. Install/configure ZOAU on z/OS "
            "and ensure zoautil_py is importable; it is not distributed on PyPI."
        ) from error


def _detect_dataset_record_format(data: bytes) -> RecordFormat:
    if len(data) >= 6:
        external_length = int.from_bytes(data[0:2], "big")
        payload_length = int.from_bytes(data[4:6], "big")
        if external_length == len(data) and payload_length == len(data) - 4:
            return "rdw"
    return "smf"


def _read_smf_dataset_records(
    records: Iterable[bytes],
    *,
    record_format: Literal["auto", "smf"],
    skip_short_records: bool,
) -> Iterator[SMFRecord]:
    buffer = bytearray()
    buffer_offset = 0
    logical_offset = 0

    for data in records:
        if not buffer and skip_short_records and len(data) < _MIN_SMF_RECORD_LENGTH:
            logical_offset += len(data)
            continue

        selected_format = _detect_dataset_record_format(data) if record_format == "auto" and not buffer else "smf"
        if selected_format == "rdw":
            yield from _read_one_rdw_dataset_record(data, logical_offset=logical_offset)
            logical_offset += len(data)
            continue

        if not buffer:
            buffer_offset = logical_offset
        buffer.extend(data)
        yield from _drain_smf_buffer(
            buffer,
            buffer_offset=buffer_offset,
            skip_invalid_records=skip_short_records,
        )
        buffer_offset = logical_offset + len(data) - len(buffer)
        logical_offset += len(data)

    if not buffer:
        return
    if skip_short_records:
        return
    parse_header(bytes(buffer), offset=buffer_offset)


def _drain_smf_buffer(
    buffer: bytearray,
    *,
    buffer_offset: int,
    skip_invalid_records: bool,
) -> Iterator[SMFRecord]:
    consumed = 0
    while len(buffer) >= _MIN_SMF_RECORD_LENGTH:
        record_length = int.from_bytes(buffer[0:2], "big")
        if record_length & 0x8000:
            record_length &= 0x7FFF
        if not _MIN_SMF_RECORD_LENGTH <= record_length <= _MAX_SMF_RECORD_LENGTH:
            if not skip_invalid_records:
                parse_header(bytes(buffer), offset=buffer_offset + consumed)
            del buffer[0]
            consumed += 1
            continue
        if record_length > len(buffer):
            if skip_invalid_records and _has_complete_candidate_after_first_byte(buffer):
                del buffer[0]
                consumed += 1
                continue
            break

        data = bytes(buffer[:record_length])
        header_offset = buffer_offset + consumed
        try:
            header = parse_header(data, offset=header_offset)
        except SMFParseError:
            if not skip_invalid_records:
                raise
            del buffer[0]
            consumed += 1
            continue
        if not _is_plausible_smf_header(header):
            if not skip_invalid_records:
                parse_header(data, offset=header_offset)
            del buffer[0]
            consumed += 1
            continue
        yield SMFRecord(data=data, header=header, offset=header_offset)
        del buffer[:record_length]
        consumed += record_length


def _is_plausible_smf_header(header: SMFHeader) -> bool:
    if not 0 <= header.time_hundredths <= _MAX_SMF_TIME_HUNDREDTHS:
        return False
    if header.record_type == 0 and header.length not in _SMF_TYPE_0_LENGTHS:
        return False
    if header.record_type_indicator == 126:
        if not header.has_extended_header or header.extended_record_type is None:
            return False
    elif header.has_extended_header:
        return False
    if not _is_plausible_identifier(header.system_id, allow_blank=False):
        return False
    return header.subsystem_id is None or _is_plausible_identifier(header.subsystem_id, allow_blank=True)


def _has_complete_candidate_after_first_byte(buffer: bytearray) -> bool:
    for index in range(1, len(buffer) - _MIN_SMF_RECORD_LENGTH + 1):
        record_length = int.from_bytes(buffer[index : index + 2], "big")
        if record_length & 0x8000:
            record_length &= 0x7FFF
        if not _MIN_SMF_RECORD_LENGTH <= record_length <= _MAX_SMF_RECORD_LENGTH:
            continue
        if index + record_length > len(buffer):
            continue
        try:
            header = parse_header(bytes(buffer[index : index + record_length]))
        except SMFParseError:
            continue
        if _is_plausible_smf_header(header):
            return True
    return False


def _is_plausible_identifier(value: bytes, *, allow_blank: bool) -> bool:
    stripped = value.rstrip(b"\x40\x00")
    if not stripped:
        return allow_blank
    try:
        text = stripped.decode("cp037")
    except UnicodeDecodeError:
        return False
    return all(character.isalnum() or character in "#$@_" for character in text)


def _read_one_rdw_dataset_record(data: bytes, *, logical_offset: int) -> Iterator[SMFRecord]:
    for record in read_records(data, record_format="rdw"):
        yield SMFRecord(
            data=record.data,
            header=record.header,
            offset=logical_offset + record.offset,
            rdw=ExternalRDW(length=record.rdw.length, segment_descriptor=record.rdw.segment_descriptor)
            if record.rdw is not None
            else None,
        )
