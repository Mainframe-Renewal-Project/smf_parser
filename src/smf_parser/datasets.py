"""Optional ZOAU integration for reading SMF unloads from z/OS datasets."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from importlib import import_module
from typing import Literal

from .errors import ZOAUMissingError
from .reader import ExternalRDW, RecordFormat, SMFRecord, parse_header, read_records

DatasetRecordFormat = Literal["auto", "smf", "rdw"]


def read_dataset(
    dataset_name: str,
    *,
    record_format: DatasetRecordFormat = "auto",
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
    yield from read_dataset_records(dataset_records, record_format=record_format)


def read_dataset_records(records: Iterable[bytes], *, record_format: DatasetRecordFormat = "auto") -> Iterator[SMFRecord]:
    """Yield SMF records from dataset records returned by ZOAU.

    ``zoautil_py.datasets.read_as_bytes`` returns one ``bytes`` value per dataset
    record. Depending on how the unload was produced, those bytes may already be
    the SMF record or may still include an external RDW.
    """

    logical_offset = 0
    for data in records:
        selected_format = _detect_dataset_record_format(data) if record_format == "auto" else record_format
        if selected_format == "smf":
            header = parse_header(data, offset=logical_offset)
            yield SMFRecord(data=data, header=header, offset=logical_offset)
        elif selected_format == "rdw":
            yield from _read_one_rdw_dataset_record(data, logical_offset=logical_offset)
        else:
            raise ValueError(f"unsupported dataset record format: {record_format!r}")
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
