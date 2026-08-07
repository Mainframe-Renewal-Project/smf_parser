"""Optional ZOAU integration for reading SMF unloads from z/OS datasets."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from importlib import import_module
from typing import cast

from .errors import (
    HeaderCatalogError,
    SMFParseError,
    ZOAUMissingError,
    ZOAUUnsupportedDatasetError,
)
from .headers import HeaderCatalog
from .reader import (
    ExternalRDW,
    RecordFormat,
    SMFHeader,
    SMFRecord,
    decode_ebcdic,
    decode_smf_time_hundredths,
    is_packed_smf_date,
    parse_header,
    read_records,
)

DatasetRecordFormat = RecordFormat
_MIN_SMF_RECORD_LENGTH = 18
_MAX_SMF_RECORD_LENGTH = 32756
_MAX_SMF_TIME_HUNDREDTHS = 24 * 60 * 60 * 100
_MAX_PLAUSIBLE_SUBTYPE = 4096


def read_dataset(
    dataset_name: str,
    *,
    record_format: DatasetRecordFormat = "auto",
    skip_short_records: bool = True,
    header_catalog: HeaderCatalog | None = None,
    system_ids: Collection[str] | None = None,
    records: int = 0,
    offset: int = 0,
    tail: bool = False,
) -> Iterator[SMFRecord]:
    """Yield SMF records from a z/OS dataset using ZOAU when available.

    ZOAU is imported lazily because it is distributed with z/OS tooling rather
    than PyPI. VBS datasets use the native z/OS logical-record reader when it
    is available; other datasets are read with ``zoautil_py.datasets.read_as_bytes``.
    """

    datasets = _zoau_datasets_module()
    vbs_entries = _zoau_vbs_dataset_entries(datasets, dataset_name)
    if vbs_entries:
        dataset_records = _read_native_vbs_dataset_records(
            dataset_name,
            entries=vbs_entries,
            records=records,
            offset=offset,
            tail=tail,
        )
        yield from _read_native_vbs_smf_records(
            dataset_records,
            header_catalog=header_catalog,
            system_ids=system_ids,
        )
        return
    else:
        dataset_records = datasets.read_as_bytes(dataset_name, records=records, offset=offset, tail=tail)
    yield from read_dataset_records(
        dataset_records,
        record_format=record_format,
        skip_short_records=skip_short_records,
        header_catalog=header_catalog,
        system_ids=system_ids,
    )


def read_dataset_records(
    records: Iterable[bytes],
    *,
    record_format: DatasetRecordFormat = "auto",
    skip_short_records: bool = True,
    header_catalog: HeaderCatalog | None = None,
    system_ids: Collection[str] | None = None,
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

    catalog = _require_header_catalog(header_catalog)

    if record_format in ("auto", "smf"):
        yield from _read_smf_dataset_records(
            records,
            record_format=record_format,
            skip_short_records=skip_short_records,
            header_catalog=catalog,
            system_ids=system_ids,
        )
        return

    if record_format != "rdw":
        raise ValueError(f"unsupported dataset record format: {record_format!r}")

    logical_offset = 0
    for data in records:
        if skip_short_records and len(data) < _MIN_SMF_RECORD_LENGTH:
            logical_offset += len(data)
            continue
        yield from _read_one_rdw_dataset_record(data, logical_offset=logical_offset, header_catalog=catalog)
        logical_offset += len(data)


def _zoau_datasets_module():
    try:
        return import_module("zoautil_py.datasets")
    except ImportError as error:
        raise ZOAUMissingError(
            "ZOAU is required to read z/OS datasets. Install/configure ZOAU on z/OS "
            "and ensure zoautil_py is importable; it is not distributed on PyPI."
        ) from error


def _zoau_vbs_dataset_entries(datasets, dataset_name: str):
    list_datasets = getattr(datasets, "list_datasets", None)
    if list_datasets is None:
        return ()

    entries = _list_zoau_dataset_metadata(list_datasets, dataset_name)
    if not entries:
        if not _is_relative_gdg_name(dataset_name):
            return ()
        base = dataset_name[:-1].split("(", maxsplit=1)[0]
        entries = _zoau_gdg_generations(base)
    if not entries:
        return ()

    record_formats = {
        str(record_format).upper()
        for entry in entries
        if (record_format := getattr(entry, "record_format", None)) is not None
    }
    if record_formats == {"VBS"}:
        return entries
    return ()


def _zoau_gdg_generations(base: str):
    try:
        gdgs = import_module("zoautil_py.gdgs")
    except ImportError as error:
        raise ZOAUMissingError(
            "ZOAU gdgs support is required to resolve relative GDG names. Ensure zoautil_py.gdgs is importable."
        ) from error

    generation_data_group_view = gdgs.GenerationDataGroupView
    generation_data_group = generation_data_group_view(base)
    generations = generation_data_group.generations
    if callable(generations):
        generations = generations()
    return tuple(cast(Iterable[object], generations))


def _is_relative_gdg_name(dataset_name: str) -> bool:
    if "(" not in dataset_name or not dataset_name.endswith(")"):
        return False
    relative_text = dataset_name[:-1].split("(", maxsplit=1)[1]
    try:
        return int(relative_text) <= 0
    except ValueError:
        return False


def _read_native_vbs_dataset_records(
    dataset_name: str,
    *,
    entries,
    records: int,
    offset: int,
    tail: bool,
) -> Iterable[bytes]:
    try:
        native = import_module("smf_parser._native")
    except ImportError as error:
        raise _unsupported_vbs_dataset_error(dataset_name, entries) from error

    read_vbs_dataset = getattr(native, "read_vbs_dataset", None)
    if read_vbs_dataset is None:
        raise _unsupported_vbs_dataset_error(dataset_name, entries)
    resolved_dataset_name = _resolve_relative_gdg_name(dataset_name, entries)
    return read_vbs_dataset(resolved_dataset_name, records=records, offset=offset, tail=tail)


def _read_native_vbs_smf_records(
    records: Iterable[bytes],
    *,
    header_catalog: HeaderCatalog | None,
    system_ids: Collection[str] | None,
) -> Iterator[SMFRecord]:
    yield from _read_smf_dataset_records(
        records,
        record_format="smf",
        skip_short_records=False,
        header_catalog=_require_header_catalog(header_catalog),
        system_ids=system_ids,
        split_on_record_start=False,
        skip_invalid_records=True,
        trusted_record_boundaries=True,
    )


def _resolve_relative_gdg_name(dataset_name: str, entries) -> str:
    if "(" not in dataset_name or not dataset_name.endswith(")"):
        return dataset_name

    base, relative_text = dataset_name[:-1].split("(", maxsplit=1)
    try:
        relative_generation = int(relative_text)
    except ValueError:
        return dataset_name
    if relative_generation > 0:
        return dataset_name

    concrete_names = _sorted_gdg_generation_names(base, entries)
    index = len(concrete_names) - 1 + relative_generation
    if 0 <= index < len(concrete_names):
        return concrete_names[index]
    return dataset_name


def _sorted_gdg_generation_names(base: str, entries) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(name)
            for entry in entries
            if (name := getattr(entry, "name", None)) is not None and str(name).startswith(f"{base}.")
        )
    )


def _unsupported_vbs_dataset_error(dataset_name: str, entries) -> ZOAUUnsupportedDatasetError:
    names = ", ".join(str(getattr(entry, "name", "<unknown>")) for entry in entries[-3:])
    return ZOAUUnsupportedDatasetError(
        f"ZOAU reports {dataset_name} as RECFM=VBS ({names}); read_as_bytes() exposes spanned segments, "
        "not complete SMF logical records. A z/OS VBS record reconstruction path is required before parsing."
    )


def _list_zoau_dataset_metadata(list_datasets, pattern: str):
    return tuple(list_datasets(pattern))


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
    record_format: DatasetRecordFormat,
    skip_short_records: bool,
    header_catalog: HeaderCatalog,
    system_ids: Collection[str] | None,
    split_on_record_start: bool = True,
    skip_invalid_records: bool | None = None,
    trusted_record_boundaries: bool = False,
) -> Iterator[SMFRecord]:
    logical_offset = 0
    buffer = bytearray()
    buffer_offset = 0
    skip_invalid = skip_short_records if skip_invalid_records is None else skip_invalid_records

    for data in records:
        if skip_short_records and not buffer and len(data) < _MIN_SMF_RECORD_LENGTH:
            logical_offset += len(data)
            continue

        selected_format = _detect_dataset_record_format(data) if record_format == "auto" else "smf"
        if not buffer and selected_format == "rdw":
            yield from _read_one_rdw_dataset_record(data, logical_offset=logical_offset, header_catalog=header_catalog)
            logical_offset += len(data)
            continue

        if split_on_record_start and buffer and _looks_like_smf_record_start(data, system_ids=system_ids):
            if not skip_short_records:
                parse_header(bytes(buffer), offset=buffer_offset)
            buffer.clear()

        if not buffer:
            buffer_offset = logical_offset
        buffer.extend(data)
        yield from _drain_smf_buffer(
            buffer,
            buffer_offset=buffer_offset,
            skip_invalid_records=skip_invalid,
            header_catalog=header_catalog,
            system_ids=system_ids,
            trusted_record_boundaries=trusted_record_boundaries,
        )
        logical_offset += len(data)

    if buffer and not skip_short_records and not skip_invalid:
        parse_header(bytes(buffer), offset=buffer_offset)


def _drain_smf_buffer(
    buffer: bytearray,
    *,
    buffer_offset: int,
    skip_invalid_records: bool,
    header_catalog: HeaderCatalog,
    system_ids: Collection[str] | None,
    trusted_record_boundaries: bool = False,
) -> Iterator[SMFRecord]:
    consumed = 0
    while len(buffer) >= _MIN_SMF_RECORD_LENGTH:
        record_length = int.from_bytes(buffer[0:2], "big")
        if record_length & 0x8000:
            record_length &= 0x7FFF
        if record_length == 0:
            del buffer[0]
            consumed += 1
            continue
        if not _MIN_SMF_RECORD_LENGTH <= record_length <= _MAX_SMF_RECORD_LENGTH:
            if not skip_invalid_records:
                parse_header(bytes(buffer), offset=buffer_offset + consumed)
            consumed += len(buffer)
            del buffer[:]
            return
        if record_length > len(buffer):
            if not skip_invalid_records and not trusted_record_boundaries:
                parse_header(bytes(buffer), offset=buffer_offset + consumed)
            break

        data = bytes(buffer[:record_length])
        header_offset = buffer_offset + consumed
        try:
            header = parse_header(data, offset=header_offset)
        except SMFParseError:
            if not skip_invalid_records:
                raise
            if not trusted_record_boundaries:
                del buffer[:]
                return
            del buffer[:record_length]
            consumed += record_length
            continue
        header_definitions = header_catalog.for_record_type(header.record_type)
        header_is_plausible = _is_plausible_smf_header(header, system_ids=system_ids)
        if not header_definitions or not header_is_plausible:
            if not skip_invalid_records:
                if not header_definitions:
                    raise HeaderCatalogError(f"no z/OS C header definition found for SMF record type {header.record_type}")
                parse_header(data, offset=header_offset)
            if not header_is_plausible:
                del buffer[:]
                return
            if not trusted_record_boundaries:
                del buffer[:]
                return
            del buffer[:record_length]
            consumed += record_length
            continue
        yield SMFRecord(
            data=data,
            header=header,
            offset=header_offset,
            header_definitions=header_definitions,
        )
        del buffer[:record_length]
        consumed += record_length


def _is_plausible_smf_header(header: SMFHeader, *, system_ids: Collection[str] | None) -> bool:
    if not 0 <= header.time_hundredths <= _MAX_SMF_TIME_HUNDREDTHS:
        return False
    if header.subtype is not None and header.subtype > _MAX_PLAUSIBLE_SUBTYPE:
        return False
    if header.record_type_indicator == 126:
        if not header.has_extended_header or header.extended_record_type is None:
            return False
    elif header.has_extended_header:
        return False
    if not _is_plausible_smf_date(header.date):
        return False
    if not _is_plausible_identifier(header.system_id, allow_blank=False):
        return False
    if system_ids is not None and header.system_id_text not in system_ids:
        return False
    return header.subsystem_id is None or _is_plausible_identifier(header.subsystem_id, allow_blank=True)


def _looks_like_smf_record_start(data: bytes, *, system_ids: Collection[str] | None) -> bool:
    if len(data) < _MIN_SMF_RECORD_LENGTH:
        return False

    record_length = int.from_bytes(data[0:2], "big")
    if record_length & 0x8000:
        record_length &= 0x7FFF
    if not _MIN_SMF_RECORD_LENGTH <= record_length <= _MAX_SMF_RECORD_LENGTH:
        return False

    date_first_header = not is_packed_smf_date(data[10:14]) and is_packed_smf_date(data[6:10])
    time_hundredths = 0 if date_first_header else decode_smf_time_hundredths(data[6:10])
    if not 0 <= time_hundredths <= _MAX_SMF_TIME_HUNDREDTHS:
        return False
    date = data[6:10] if date_first_header else data[10:14]
    system_id = data[10:14] if date_first_header else data[14:18]
    subsystem_id = data[14:18] if date_first_header else data[18:22]
    if data[4] & 0x40:
        subtype_offset = 18 if date_first_header else 22
        if len(data) >= subtype_offset + 2:
            subtype = int.from_bytes(data[subtype_offset : subtype_offset + 2], "big")
            if subtype > _MAX_PLAUSIBLE_SUBTYPE:
                return False
    if not _is_plausible_smf_date(date):
        return False
    if not _is_plausible_identifier(system_id, allow_blank=False):
        return False
    if system_ids is not None and decode_ebcdic(system_id) not in system_ids:
        return False
    minimum_subsystem_length = 18 if date_first_header else 22
    return len(data) < minimum_subsystem_length or _is_plausible_identifier(subsystem_id, allow_blank=True)

def _require_header_catalog(header_catalog: HeaderCatalog | None) -> HeaderCatalog:
    catalog = HeaderCatalog.discover() if header_catalog is None else header_catalog
    if not catalog.headers:
        raise HeaderCatalogError(f"no z/OS C headers found in {catalog.include_dir}")
    return catalog


def _is_plausible_identifier(value: bytes, *, allow_blank: bool) -> bool:
    stripped = value.rstrip(b"\x40\x00")
    if not stripped:
        return allow_blank
    try:
        text = decode_ebcdic(stripped)
    except UnicodeDecodeError:
        return False
    return all(character.isalnum() or character in "#$@_" for character in text)


def _is_plausible_smf_date(value: bytes) -> bool:
    if len(value) != 4:
        return False
    nibbles = tuple(nibble for byte in value for nibble in (byte >> 4, byte & 0x0F))
    if nibbles[-1] != 0x0F or any(nibble > 9 for nibble in nibbles[:-1]):
        return False
    day_of_year = nibbles[4] * 100 + nibbles[5] * 10 + nibbles[6]
    return 1 <= day_of_year <= 366


def _read_one_rdw_dataset_record(data: bytes, *, logical_offset: int, header_catalog: HeaderCatalog) -> Iterator[SMFRecord]:
    for record in read_records(data, record_format="rdw", header_catalog=header_catalog):
        yield SMFRecord(
            data=record.data,
            header=record.header,
            offset=logical_offset + record.offset,
            rdw=ExternalRDW(length=record.rdw.length, segment_descriptor=record.rdw.segment_descriptor)
            if record.rdw is not None
            else None,
            header_definitions=record.header_definitions,
        )
