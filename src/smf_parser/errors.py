"""Exceptions raised while parsing SMF data."""

from __future__ import annotations


class SMFError(Exception):
    """Base exception for smf_parser."""


class SMFParseError(SMFError):
    """Raised when SMF input is malformed or unsupported."""

    def __init__(self, message: str, *, offset: int | None = None) -> None:
        self.offset = offset
        if offset is not None:
            message = f"{message} at byte offset {offset}"
        super().__init__(message)


class TruncatedSMFRecord(SMFParseError):
    """Raised when a record or record prefix ends before its declared length."""


class HeaderCatalogError(SMFError):
    """Raised when required z/OS C headers are unavailable or incomplete."""


class ZOAUMissingError(SMFError):
    """Raised when a ZOAU-only API is used without ZOAU installed."""
