"""Catalog for z/OS C SMF headers compiled into this package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import import_module
from os import environ
from pathlib import Path
from types import MappingProxyType

from .errors import HeaderCatalogError


@dataclass(frozen=True, slots=True)
class HeaderDefinition:
    """Summary of one retained C header."""

    name: str
    path: Path
    record_types: tuple[int, ...]
    generic: bool = False


@dataclass(frozen=True, slots=True)
class HeaderCatalog:
    """Index of C headers that can back generated Python record wrappers."""

    include_dir: Path
    headers: tuple[HeaderDefinition, ...]
    _headers_by_name: Mapping[str, HeaderDefinition] = field(
        init=False, repr=False, compare=False
    )
    _headers_by_record_type: Mapping[int, tuple[HeaderDefinition, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        headers_by_name: dict[str, HeaderDefinition] = {}
        headers_by_record_type: dict[int, list[HeaderDefinition]] = {}
        for header in self.headers:
            for name in _normalized_header_names(header.name, header.path.name):
                headers_by_name.setdefault(name, header)
            for record_type in header.record_types:
                headers_by_record_type.setdefault(record_type, []).append(header)
        object.__setattr__(self, "_headers_by_name", MappingProxyType(headers_by_name))
        object.__setattr__(
            self,
            "_headers_by_record_type",
            MappingProxyType(
                {
                    record_type: tuple(headers)
                    for record_type, headers in headers_by_record_type.items()
                }
            ),
        )

    @classmethod
    def discover(cls, include_dir: str | Path | None = None) -> HeaderCatalog:
        root = Path(include_dir) if include_dir is not None else default_include_dir()
        compiled_include_dir, definitions = _compiled_headers()
        if root != compiled_include_dir:
            raise HeaderCatalogError(
                "pysmf was built against z/OS C headers in "
                f"{compiled_include_dir}, not {root}"
            )
        if not definitions:
            raise HeaderCatalogError(f"no z/OS C headers found in {root}")
        return cls(include_dir=root, headers=definitions)

    def by_name(self, name: str) -> HeaderDefinition | None:
        for normalized in _normalized_header_names(name):
            if header := self._headers_by_name.get(normalized):
                return header
        return None

    def for_record_type(self, record_type: int) -> tuple[HeaderDefinition, ...]:
        return self._headers_by_record_type.get(record_type, ())


def default_include_dir() -> Path:
    """Return the default z/OS C header include directory."""

    configured = environ.get("PYSMF_ZOS_INCLUDE")
    if configured:
        return Path(configured)
    return Path("/usr/include/zos")


def _normalized_header_names(*names: str) -> frozenset[str]:
    normalized: set[str] = set()
    for name in names:
        path = Path(name)
        stem = path.stem if path.suffix else name
        normalized.update((name, stem, stem.upper(), f"{stem}.h", f"{stem.lower()}.h"))
    return frozenset(normalized)


def _compiled_headers() -> tuple[Path, tuple[HeaderDefinition, ...]]:
    try:
        manifest = import_module("._compiled_headers", package=__package__)
    except ImportError as error:
        raise HeaderCatalogError(
            "pysmf was not built with compiled z/OS C headers; rebuild it on z/OS "
            "with PYSMF_ZOS_INCLUDE pointing at the header directory"
        ) from error

    include_dir = Path(manifest.INCLUDE_DIR)
    definitions = tuple(
        HeaderDefinition(
            name=entry["name"],
            path=Path(entry.get("path", include_dir / entry["name"])),
            record_types=tuple(entry.get("record_types", ())),
            generic=bool(entry.get("generic", False)),
        )
        for entry in manifest.HEADERS
    )
    return include_dir, definitions
