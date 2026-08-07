"""Catalog for z/OS C SMF headers compiled into this package."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from os import environ
from pathlib import Path

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

    @classmethod
    def discover(cls, include_dir: str | Path | None = None) -> HeaderCatalog:
        root = Path(include_dir) if include_dir is not None else default_include_dir()
        compiled_include_dir, definitions = _compiled_headers()
        if root != compiled_include_dir:
            raise HeaderCatalogError(
                f"smf_parser was built against z/OS C headers in {compiled_include_dir}, not {root}"
            )
        if not definitions:
            raise HeaderCatalogError(f"no z/OS C headers found in {root}")
        return cls(include_dir=root, headers=definitions)

    def by_name(self, name: str) -> HeaderDefinition | None:
        normalized = _normalized_header_names(name)
        for header in self.headers:
            if normalized & _normalized_header_names(header.name, header.path.name):
                return header
        return None

    def for_record_type(self, record_type: int) -> tuple[HeaderDefinition, ...]:
        return tuple(header for header in self.headers if record_type in header.record_types)

    def structs(self) -> tuple[str, ...]:
        return ()


def default_include_dir() -> Path:
    """Return the default z/OS C header include directory."""

    configured = environ.get("SMF_PARSER_ZOS_INCLUDE")
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
            "smf_parser was not built with compiled z/OS C headers; rebuild it on z/OS "
            "with SMF_PARSER_ZOS_INCLUDE pointing at the header directory"
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
