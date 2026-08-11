"""Python tools for reading and interpreting z/OS SMF unloads."""

from __future__ import annotations

from .datasets import read_dataset, read_dataset_records
from .errors import (
    HeaderCatalogError,
    SMFError,
    SMFParseError,
    SMFRecordTypeSupportError,
    TruncatedSMFRecordError,
    ZOAUMissingError,
    ZOAUUnsupportedDatasetError,
)
from .headers import (
    HeaderCatalog,
    HeaderDefinition,
    SMFRecordTypeDefinition,
    SMFRecordTypeRegistry,
    default_include_dir,
)
from .reader import (
    ExternalRDW,
    SMFHeader,
    SMFRecord,
    decode_ebcdic,
    parse_header,
    read_file,
    read_records,
)
from .records import (
    SMFFieldSection,
    StructuredSMFRecord,
    parse_record,
    parse_records,
    read_structured_dataset,
    read_structured_file,
    read_structured_records,
)

__all__ = [
    "ExternalRDW",
    "SMFError",
    "SMFFieldSection",
    "SMFHeader",
    "SMFParseError",
    "SMFRecord",
    "SMFRecordTypeDefinition",
    "SMFRecordTypeRegistry",
    "SMFRecordTypeSupportError",
    "StructuredSMFRecord",
    "TruncatedSMFRecordError",
    "ZOAUMissingError",
    "ZOAUUnsupportedDatasetError",
    "decode_ebcdic",
    "default_include_dir",
    "parse_header",
    "parse_record",
    "parse_records",
    "read_dataset",
    "read_dataset_records",
    "read_file",
    "read_records",
    "read_structured_dataset",
    "read_structured_file",
    "read_structured_records",
]
