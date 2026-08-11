"""Exceptions raised while parsing SMF data."""

from __future__ import annotations


class SMFError(Exception):
    """Base exception for pysmf."""


class SMFParseError(SMFError):
    """Raised when SMF input is malformed or unsupported."""

    def __init__(self, message: str, *, offset: int | None = None) -> None:
        self.offset = offset
        if offset is not None:
            message = f"{message} at byte offset {offset}"
        super().__init__(message)


class TruncatedSMFRecordError(SMFParseError):
    """Raised when a record or record prefix ends before its declared length."""


class SMFRecordTypeSupportError(SMFError):
    """Raised when SMF record type support is unavailable or incomplete."""


class ZOAUMissingError(SMFError):
    """Raised when a ZOAU-only API is used without ZOAU installed."""


class ZOAUUnsupportedDatasetError(SMFError):
    """Raised when ZOAU exposes dataset bytes in an unsupported record format."""
