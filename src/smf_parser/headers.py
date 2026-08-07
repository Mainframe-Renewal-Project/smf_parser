"""Lightweight catalog for the retained z/OS C SMF headers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from os import environ
from pathlib import Path

from .errors import HeaderCatalogError

_STRUCT_PATTERN = re.compile(r"\bstruct\s+([A-Za-z_]\w*)\s*\{")
_RECORD_TYPE_PATTERNS = (
    re.compile(r"\bSMF\s+record\s+type\s+(\d+)", re.IGNORECASE),
    re.compile(r"\bRECORD\s+TYPE\s+(\d+)", re.IGNORECASE),
    re.compile(r"\bSMF(\d{1,4})\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class HeaderDefinition:
    """Summary of one retained C header."""

    name: str
    path: Path
    structs: tuple[str, ...]
    record_types: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class HeaderCatalog:
    """Index of C headers that can back generated Python record wrappers."""

    include_dir: Path
    headers: tuple[HeaderDefinition, ...]

    @classmethod
    def discover(cls, include_dir: str | Path | None = None) -> HeaderCatalog:
        root = Path(include_dir) if include_dir is not None else default_include_dir()
        definitions = tuple(_read_header(path) for path in sorted(root.glob("*.h")))
        if not definitions:
            raise HeaderCatalogError(f"no z/OS C headers found in {root}")
        return cls(include_dir=root, headers=definitions)

    def by_name(self, name: str) -> HeaderDefinition | None:
        normalized = name if name.endswith(".h") else f"{name}.h"
        for header in self.headers:
            if header.name == normalized:
                return header
        return None

    def for_record_type(self, record_type: int) -> tuple[HeaderDefinition, ...]:
        return tuple(header for header in self.headers if record_type in header.record_types)

    def structs(self) -> tuple[str, ...]:
        return tuple(struct for header in self.headers for struct in header.structs)


def default_include_dir() -> Path:
    """Return the default z/OS C header include directory."""

    configured = environ.get("SMF_PARSER_ZOS_INCLUDE")
    if configured:
        return Path(configured)
    return Path("/usr/include/zos")


def _read_header(path: Path) -> HeaderDefinition:
    text = path.read_text(encoding="utf-8", errors="replace")
    structs = tuple(dict.fromkeys(_STRUCT_PATTERN.findall(text)))
    record_types = tuple(sorted(_record_types(text, path.stem)))
    return HeaderDefinition(name=path.name, path=path, structs=structs, record_types=record_types)


def _record_types(text: str, stem: str) -> set[int]:
    values: set[int] = set()
    for pattern in _RECORD_TYPE_PATTERNS:
        for match in pattern.finditer(text):
            values.add(int(match.group(1)))
    for match in re.finditer(r"smf(\d{1,4})", stem, flags=re.IGNORECASE):
        values.add(int(match.group(1)))
    return values
