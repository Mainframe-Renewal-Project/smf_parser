"""Python tools for reading and interpreting z/OS SMF unloads."""

from __future__ import annotations

from .datasets import read_dataset, read_dataset_records
from .errors import (
    HeaderCatalogError,
    SMFError,
    SMFParseError,
    TruncatedSMFRecordError,
    ZOAUMissingError,
    ZOAUUnsupportedDatasetError,
)
from .headers import HeaderCatalog, HeaderDefinition, default_include_dir
from .reader import (
    ExternalRDW,
    SMFHeader,
    SMFRecord,
    decode_ebcdic,
    parse_header,
    read_file,
    read_records,
)

__all__ = [
    "ExternalRDW",
    "HeaderCatalog",
    "HeaderCatalogError",
    "HeaderDefinition",
    "SMFError",
    "SMFHeader",
    "SMFParseError",
    "SMFRecord",
    "TruncatedSMFRecordError",
    "ZOAUMissingError",
    "ZOAUUnsupportedDatasetError",
    "decode_ebcdic",
    "default_include_dir",
    "parse_header",
    "read_dataset",
    "read_dataset_records",
    "read_file",
    "read_records",
]
