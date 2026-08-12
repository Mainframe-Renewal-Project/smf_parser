# pyright: reportMissingImports=false

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Literal, TypeVar, cast

from setuptools import Extension
from setuptools._distutils.ccompiler import CompileError, new_compiler
from setuptools._distutils.sysconfig import customize_compiler
from setuptools._distutils.util import get_platform
from setuptools.command.build_ext import build_ext as build_ext_base
from setuptools.command.build_py import build_py as build_py_base
from wheel.bdist_wheel import bdist_wheel as bdist_wheel_base

DEFAULT_INCLUDE_DIR = Path("/usr/include/zos")
ROOT = Path(__file__).parents[1]
HEADER_COMPILE_FLAGS = ("-Wno-trigraphs",)


@dataclass(frozen=True)
class LongTripletDirectoryAction:
    kind: Literal["long_triplet_directory"]
    key: str
    directory: Literal["fixed_end"]
    count_field: str


@dataclass(frozen=True)
class CompactSectionDirectoryFallbackAction:
    kind: Literal["compact_section_directory_fallback"]
    key: str
    anchor_field: str
    relocate_field: str
    relocate_shift: int
    count_delta: int


@dataclass(frozen=True)
class Smf1154CommonOverlayAction:
    kind: Literal["smf1154_common_overlay"]
    ctrp_struct: str
    common_struct: str
    required_ctrp_names: tuple[str, ...]
    common_directory_key: str
    subspec_directory_key: str


@dataclass(frozen=True)
class Racf83Subtype1SecurityAction:
    kind: Literal["racf83_subtype1_security"]
    security_struct: str
    variable_section_struct: str
    subtype_primary_offset: int | None
    subtype_secondary_offset: int | None
    subtype_value: int
    sds_type_value: int
    security_minimum_length: int
    header_integer_fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Smf119IdentOverlayAction:
    kind: Literal["smf119_ident_overlay"]
    triplet_struct: str
    ident_struct: str
    triplet_count_field: str
    ident_offset_field: str
    ident_length_field: str
    ident_count_field: str
    triplet_directory_anchor_field: str
    triplet_max_count: int | None
    directory_key: str
    skip_ident_fields: tuple[str, ...]


SpecialRecordAction = (
    LongTripletDirectoryAction
    | CompactSectionDirectoryFallbackAction
    | Smf1154CommonOverlayAction
    | Racf83Subtype1SecurityAction
    | Smf119IdentOverlayAction
)

ActionT = TypeVar("ActionT", bound=SpecialRecordAction)


def _validate_special_record_actions(
    actions: dict[int, tuple[SpecialRecordAction, ...]],
) -> dict[int, tuple[SpecialRecordAction, ...]]:
    for record_type, record_actions in actions.items():
        if record_type <= 0:
            raise RuntimeError(
                f"special record action type must be positive: {record_type}"
            )
        if not record_actions:
            raise RuntimeError(
                f"special record type {record_type} has an empty action list"
            )
        for action in record_actions:
            if isinstance(action, LongTripletDirectoryAction):
                if not action.count_field:
                    raise RuntimeError(
                        f"special record type {record_type} has empty count field"
                    )
                continue
            if isinstance(action, CompactSectionDirectoryFallbackAction):
                if not action.anchor_field or not action.relocate_field:
                    raise RuntimeError(
                        f"special record type {record_type} has missing compact fields"
                    )
                continue
            if isinstance(action, Smf1154CommonOverlayAction):
                if record_type != 1154:
                    raise RuntimeError(
                        "smf1154_common_overlay action can only be registered "
                        f"for type 1154, found {record_type}"
                    )
                continue
            if isinstance(action, Racf83Subtype1SecurityAction):
                if record_type != 83:
                    raise RuntimeError(
                        "racf83_subtype1_security action can only be registered "
                        f"for type 83, found {record_type}"
                    )
                continue
            if isinstance(action, Smf119IdentOverlayAction):
                if record_type != 119:
                    raise RuntimeError(
                        "smf119_ident_overlay action can only be registered "
                        f"for type 119, found {record_type}"
                    )
                continue
            raise RuntimeError(
                f"unsupported special action class for type {record_type}: "
                f"{type(action).__name__}"
            )
    return actions


def _build_special_record_actions(
    action_specs: dict[int, tuple[dict[str, object], ...]],
) -> dict[int, tuple[SpecialRecordAction, ...]]:
    actions: dict[int, tuple[SpecialRecordAction, ...]] = {}
    for record_type, record_specs in action_specs.items():
        typed_actions: list[SpecialRecordAction] = []
        for spec in record_specs:
            kind = str(spec.get("kind", ""))
            if kind == "long_triplet_directory":
                typed_actions.append(
                    LongTripletDirectoryAction(
                        kind="long_triplet_directory",
                        key=str(spec["key"]),
                        directory=cast(Literal["fixed_end"], str(spec["directory"])),
                        count_field=str(spec["count_field"]),
                    )
                )
                continue
            if kind == "compact_section_directory_fallback":
                typed_actions.append(
                    CompactSectionDirectoryFallbackAction(
                        kind="compact_section_directory_fallback",
                        key=str(spec["key"]),
                        anchor_field=str(spec["anchor_field"]),
                        relocate_field=str(spec["relocate_field"]),
                        relocate_shift=int(cast(int, spec["relocate_shift"])),
                        count_delta=int(cast(int, spec["count_delta"])),
                    )
                )
                continue
            if kind == "smf1154_common_overlay":
                typed_actions.append(
                    Smf1154CommonOverlayAction(
                        kind="smf1154_common_overlay",
                        ctrp_struct=str(spec["ctrp_struct"]),
                        common_struct=str(spec["common_struct"]),
                        required_ctrp_names=tuple(
                            str(name)
                            for name in cast(
                                tuple[object, ...],
                                spec["required_ctrp_names"],
                            )
                        ),
                        common_directory_key=str(spec["common_directory_key"]),
                        subspec_directory_key=str(spec["subspec_directory_key"]),
                    )
                )
                continue
            if kind == "racf83_subtype1_security":
                typed_actions.append(
                    Racf83Subtype1SecurityAction(
                        kind="racf83_subtype1_security",
                        security_struct=str(spec["security_struct"]),
                        variable_section_struct=str(spec["variable_section_struct"]),
                        subtype_primary_offset=(
                            int(cast(int, spec["subtype_primary_offset"]))
                            if "subtype_primary_offset" in spec
                            else None
                        ),
                        subtype_secondary_offset=(
                            int(cast(int, spec["subtype_secondary_offset"]))
                            if "subtype_secondary_offset" in spec
                            else None
                        ),
                        subtype_value=int(cast(int, spec["subtype_value"])),
                        sds_type_value=int(cast(int, spec["sds_type_value"])),
                        security_minimum_length=int(
                            cast(int, spec["security_minimum_length"])
                        ),
                        header_integer_fields=tuple(
                            (str(name), str(expression))
                            for name, expression in cast(
                                tuple[tuple[object, object], ...],
                                spec["header_integer_fields"],
                            )
                        ),
                    )
                )
                continue
            if kind == "smf119_ident_overlay":
                typed_actions.append(
                    Smf119IdentOverlayAction(
                        kind="smf119_ident_overlay",
                        triplet_struct=str(spec["triplet_struct"]),
                        ident_struct=str(spec["ident_struct"]),
                        triplet_count_field=str(spec["triplet_count_field"]),
                        ident_offset_field=str(spec["ident_offset_field"]),
                        ident_length_field=str(spec["ident_length_field"]),
                        ident_count_field=str(spec["ident_count_field"]),
                        triplet_directory_anchor_field=str(
                            spec["triplet_directory_anchor_field"]
                        ),
                        triplet_max_count=(
                            int(cast(int, spec["triplet_max_count"]))
                            if "triplet_max_count" in spec
                            else None
                        ),
                        directory_key=str(spec["directory_key"]),
                        skip_ident_fields=tuple(
                            str(name)
                            for name in cast(
                                tuple[object, ...], spec["skip_ident_fields"]
                            )
                        ),
                    )
                )
                continue
            raise RuntimeError(f"unsupported special record action kind: {kind!r}")
        actions[int(record_type)] = tuple(typed_actions)
    return actions


@lru_cache(maxsize=1)
def _header_registry_module() -> Any:
    registry_path = ROOT / "src" / "pysmf" / "_header_registry.py"
    spec = spec_from_file_location("_pysmf_header_registry", registry_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load header registry from {registry_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _special_record_struct_names() -> dict[int, tuple[str, ...]]:
    module = _header_registry_module()
    raw_names = getattr(module, "SPECIAL_RECORD_STRUCT_NAMES", {})
    names: dict[int, tuple[str, ...]] = {}
    for record_type, struct_names in cast(dict[object, object], raw_names).items():
        typed_record_type = int(cast(int | str, record_type))
        names[typed_record_type] = tuple(
            str(name) for name in cast(tuple[object, ...], struct_names)
        )
    return names


def _special_record_action_specs() -> dict[int, tuple[dict[str, object], ...]]:
    module = _header_registry_module()
    raw_actions = getattr(module, "SPECIAL_RECORD_ACTIONS", {})
    specs: dict[int, tuple[dict[str, object], ...]] = {}
    for record_type, action_specs in cast(dict[object, object], raw_actions).items():
        typed_record_type = int(cast(int | str, record_type))
        specs[typed_record_type] = tuple(
            cast(dict[str, object], action)
            for action in cast(tuple[object, ...], action_specs)
        )
    return specs


def _record_type_options() -> dict[int, dict[str, object]]:
    module = _header_registry_module()
    raw_options = getattr(module, "RECORD_TYPE_OPTIONS", {})
    options: dict[int, dict[str, object]] = {}
    for record_type, values in cast(dict[object, object], raw_options).items():
        typed_record_type = int(cast(int | str, record_type))
        options[typed_record_type] = cast(dict[str, object], values)
    return options


SPECIAL_RECORD_STRUCT_NAMES: dict[int, tuple[str, ...]] = _special_record_struct_names()
SPECIAL_RECORD_ACTIONS: dict[int, tuple[SpecialRecordAction, ...]] = (
    _validate_special_record_actions(
        _build_special_record_actions(_special_record_action_specs())
    )
)
RECORD_TYPE_OPTIONS: dict[int, dict[str, object]] = _record_type_options()
FIELD_RE = re.compile(
    r"^\s*(?P<type>unsigned\s+char|char|unsigned\s+short|short|"
    r"unsigned\s+int|int|unsigned\s+long\s+long|long\s+long|"
    r"u?int(?:8|16|32|64)_t|int(?:8|16|32|64)_t)"
    r"\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\[(?P<array>\d+)\])?"
    r"(?:\s*:\s*(?P<bits>\d+))?\s*;"
)


class BuildPy(build_py_base):
    def run(self) -> None:
        compiled_headers = _compile_headers(_include_dir())
        super().run()
        self._write_compiled_header_manifest(compiled_headers)

    def _write_compiled_header_manifest(
        self, compiled_headers: list[dict[str, object]]
    ) -> None:
        package_dir = Path(self.build_lib, "pysmf")
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest = package_dir / "_compiled_headers.py"
        manifest.write_text(
            "# Generated by setup.py during package build.\n"
            "from __future__ import annotations\n\n"
            f"INCLUDE_DIR = {str(_include_dir())!r}\n"
            f"HEADERS = {compiled_headers!r}\n",
            encoding="utf-8",
        )


class BdistWheel(bdist_wheel_base):
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        python_tag, abi_tag, platform_tag = super().get_tag()
        if platform_tag == "any":
            platform_tag = get_platform().replace("-", "_").replace(".", "_")
        return python_tag, abi_tag, platform_tag


class BuildExt(build_ext_base):
    def build_extensions(self) -> None:
        generated_source = _generate_record_parser_source(
            Path(self.build_temp), _include_dirs()
        )
        for extension in self.extensions:
            if extension.name == "pysmf._native":
                extension.sources.append(str(generated_source))
        super().build_extensions()


def _include_dir() -> Path:
    from os import environ

    configured = environ.get("PYSMF_ZOS_INCLUDE")
    if configured:
        return Path(configured)
    return DEFAULT_INCLUDE_DIR


def _include_dirs() -> tuple[Path, ...]:
    from os import environ

    include_dir = _include_dir()
    include_dirs = [include_dir]

    include_root = (
        include_dir.parent if include_dir.name.lower() == "zos" else include_dir
    )
    if include_root not in include_dirs:
        include_dirs.append(include_root)

    for subdir in ("zos", "IBM"):
        candidate = include_root / subdir
        if candidate not in include_dirs:
            include_dirs.append(candidate)

    configured_ibm_include = environ.get("PYSMF_IBM_INCLUDE")
    ibm_include_dir = (
        Path(configured_ibm_include)
        if configured_ibm_include
        else include_root / "IBM"
    )
    if ibm_include_dir != include_dir:
        include_dirs.append(ibm_include_dir)

    return tuple(include_dirs)


def _compile_headers(include_dir: Path) -> list[dict[str, object]]:
    if not include_dir.is_dir():
        raise RuntimeError(f"z/OS C header directory does not exist: {include_dir}")

    include_dirs = _include_dirs()
    compiler = new_compiler()
    customize_compiler(compiler)
    compiled: list[dict[str, object]] = []
    failures: list[str] = []

    with TemporaryDirectory() as source_dir_name:
        source_dir = Path(source_dir_name)
        for target in _header_targets():
            header_name = str(target["name"])
            resolved = _resolve_header(target, include_dirs)
            if resolved is None:
                continue
            include_name, header_path = resolved
            source = source_dir / f"compile_{header_path.stem.lower()}.c"
            source.write_text(
                f"#include <{include_name}>\nint main(void) {{ return 0; }}\n",
                encoding="utf-8",
            )
            try:
                compiler.compile(
                    [str(source)],
                    include_dirs=[str(path) for path in include_dirs],
                    extra_postargs=list(HEADER_COMPILE_FLAGS),
                )
            except CompileError as error:
                failures.append(f"{header_name} ({include_name}): {error}")
                continue
            compiled.append(
                {
                    "name": header_name,
                    "path": str(header_path),
                    "record_types": tuple(target["record_types"]),
                    "generic": bool(target["generic"]),
                }
            )

    if not any(header["generic"] for header in compiled):
        detail = "\n".join(failures)
        message = f"no generic SMF C header compiled from {include_dir}"
        if detail:
            message = f"{message}:\n{detail}"
        raise RuntimeError(message)
    return compiled


def _resolve_header(
    target: dict[str, Any], include_dirs: tuple[Path, ...]
) -> tuple[str, Path] | None:
    for header_name in _header_name_candidates(target):
        for include_dir in include_dirs:
            header_path = include_dir / header_name
            if header_path.is_file():
                return header_name, header_path
    return None


def _header_name_candidates(target: dict[str, Any]) -> tuple[str, ...]:
    header_names = (
        str(target["name"]),
        *(str(name) for name in target.get("alternate_names", ())),
    )
    candidates: list[str] = []
    for header_name in header_names:
        path = Path(header_name)
        stem = path.stem if path.suffix else header_name
        candidates.extend((header_name, stem, stem.upper()))
    return tuple(dict.fromkeys(candidates))


def _header_targets() -> tuple[dict[str, Any], ...]:
    module = _header_registry_module()
    return tuple(module.HEADER_TARGETS)


def native_extension() -> Extension:
    return Extension(
        "pysmf._native",
        sources=["src/pysmf/_native.c"],
        include_dirs=[str(path) for path in _include_dirs()],
        extra_compile_args=list(HEADER_COMPILE_FLAGS),
    )


def _generate_record_parser_source(
    build_temp: Path, include_dirs: tuple[Path, ...]
) -> Path:
    build_temp.mkdir(parents=True, exist_ok=True)
    source = build_temp / "_generated_records.c"
    records = _record_structs(include_dirs)

    includes = tuple(dict.fromkeys(record["include"] for record in records))
    lines = [
        "#define PY_SSIZE_T_CLEAN",
        "#include <Python.h>",
        "#include <stdint.h>",
        *(f"#include <{include}>" for include in includes),
        "",
        "int set_long(PyObject *dict, const char *key, long long value);",
        "int set_bytes(PyObject *dict, const char *key, ",
        "const unsigned char *data, Py_ssize_t length);",
        "unsigned long long read_unsigned_be(const unsigned char *data, ",
        "Py_ssize_t length);",
        "long long read_signed_be(const unsigned char *data, Py_ssize_t length);",
        "int is_packed_smf_date(const unsigned char *data);",
        "int validate_record_type(const unsigned char *data, int expected);",
        "int append_self_defining_triplet_sections(PyObject *dict, ",
        "const char *key, const unsigned char *data, Py_ssize_t record_length, ",
        "unsigned long long data_type, unsigned long long section_offset, ",
        "unsigned long long section_length, unsigned long long section_count);",
        "int append_self_defining_variable_sections(PyObject *dict, ",
        "const char *key, const unsigned char *data, Py_ssize_t record_length, ",
        "unsigned long long section_offset, unsigned long long section_count, ",
        "unsigned long long type_size, unsigned long long length_size, ",
        "unsigned long long data_offset);",
        "int append_self_defining_section_directory(PyObject *dict, ",
        "const char *key, const unsigned char *data, Py_ssize_t record_length, ",
        "unsigned long long directory, unsigned long long count);",
        "int append_self_defining_long_triplet_directory(PyObject *dict, ",
        "const char *key, const unsigned char *data, Py_ssize_t record_length, ",
        "unsigned long long directory, unsigned long long count);",
        "",
    ]

    for record in records:
        lines.extend(_record_parser_function(record))

    lines.extend(
        [
            "PyObject *generated_parse_record(PyObject *self, PyObject *args) {",
            "    int record_type;",
            "    Py_buffer view;",
            "    PyObject *result;",
            "    if (!PyArg_ParseTuple(args, \"iy*\", &record_type, &view)) { "
            "return NULL; }",
            "    switch (record_type) {",
            *(
                f"    case {record['record_type']}: result = "
                f"parse_{record['struct_name']}(&view); break;"
                for record in records
            ),
            "    default:",
            "        PyBuffer_Release(&view);",
            "        PyErr_Format(PyExc_NotImplementedError, \"SMF type %d "
            "does not yet have a generated structured parser\", record_type);",
            "        return NULL;",
            "    }",
            "    PyBuffer_Release(&view);",
            "    return result;",
            "}",
            "",
        ]
    )
    source.write_text("\n".join(lines), encoding="utf-8")
    return source


def _record_structs(include_dirs: tuple[Path, ...]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    seen_record_types: set[int] = set()
    for target in _header_targets():
        resolved = _resolve_header(target, include_dirs)
        if resolved is None:
            continue
        include_name, header_path = resolved
        header_text = _read_header_text(header_path)
        structs = _header_structs(header_text)
        for record_type in target["record_types"]:
            if record_type in seen_record_types:
                continue
            struct_name = _record_struct_name(int(record_type), structs)
            if struct_name is None:
                continue
            fields = _record_struct_fields(structs[struct_name])
            record_options = RECORD_TYPE_OPTIONS.get(int(record_type), {})
            allow_empty_fields = bool(record_options.get("allow_empty_fields", False))
            if not fields and not allow_empty_fields:
                continue
            records.append(
                {
                    "record_type": int(record_type),
                    "struct_name": struct_name,
                    "include": include_name,
                    "fields": fields,
                    "adjacent_section_fields": _record_adjacent_section_fields(
                        int(record_type), structs
                    ),
                    "section_structs": _record_section_structs(
                        int(record_type), structs
                    ),
                    "special_structs": _record_special_structs(
                        int(record_type), structs
                    ),
                }
            )
            seen_record_types.add(int(record_type))
    return records


def _read_header_text(header_path: Path) -> str:
    data = header_path.read_bytes()
    for encoding in ("utf-8", "cp1047", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="ignore")


def _header_structs(header_text: str) -> dict[str, str]:
    structs: dict[str, str] = {}
    position = 0
    while True:
        match = re.search(
            r"struct\s+([A-Za-z_]\w*)(?:\s|/\*.*?\*/)*\{",
            header_text[position:],
            flags=re.DOTALL,
        )
        if match is None:
            return structs
        name = match.group(1)
        start = position + match.end()
        depth = 1
        index = start
        while index < len(header_text) and depth:
            if header_text[index] == "{":
                depth += 1
            elif header_text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            structs[name] = header_text[start : index - 1]
        position = index


def _record_struct_name(record_type: int, structs: dict[str, str]) -> str | None:
    candidates = [
        f"smfrcd{record_type:02d}",
        f"smfrcd{record_type}",
        f"smf{record_type}",
        f"smf{record_type}rcd",
        f"smf{record_type}rec",
        f"smfr{record_type}",
        f"Smf{record_type}Header",
        f"SMF{record_type}Header",
    ]
    if record_type >= 100:
        candidates.append(f"smfrcd{record_type:x}")
    for candidate in candidates:
        if candidate in structs:
            return candidate
    return None


def _record_struct_fields(body: str) -> tuple[dict[str, object], ...]:
    top_level_union_body = _top_level_union_struct_body(body)
    if top_level_union_body is not None:
        union_fields = _record_struct_fields(top_level_union_body)
        if len(union_fields) > 1:
            return union_fields

    fields: list[dict[str, object]] = []
    seen: set[str] = set()
    bit_offset = 0
    brace_depth = 0
    top_level_union_depth = 0
    top_level_union_start = 0
    top_level_union_size = 0
    top_level_union_has_field = False
    for raw_line in body.splitlines():
        line_without_comment = raw_line.split("/*", maxsplit=1)[0]
        line = line_without_comment.strip()
        depth_before_line = brace_depth
        starts_top_level_union = depth_before_line == 0 and line.startswith("union ")
        brace_depth += line.count("{") - line.count("}")
        if starts_top_level_union and top_level_union_depth == 0:
            top_level_union_depth = brace_depth
            top_level_union_start = bit_offset
            top_level_union_size = 0
            top_level_union_has_field = False
            continue
        if top_level_union_depth and brace_depth < top_level_union_depth:
            bit_offset = max(bit_offset, top_level_union_start + top_level_union_size)
            top_level_union_depth = 0
            top_level_union_start = 0
            top_level_union_size = 0
            top_level_union_has_field = False
            continue
        if depth_before_line != 0:
            if (
                depth_before_line != top_level_union_depth
                or top_level_union_has_field
                or line.startswith(("struct ", "union "))
            ):
                continue
        elif line.startswith(("struct ", "union ")):
            continue
        match = FIELD_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        c_type = " ".join(match.group("type").split())
        array_length = int(match.group("array")) if match.group("array") else 0
        field_bits = int(match.group("bits")) if match.group("bits") else 0
        if match.group("array") and array_length == 0:
            continue
        if name in seen or name.endswith(("_end_v1", "_end_v2", "_end_v3")):
            continue
        if field_bits:
            offset = (
                top_level_union_start if top_level_union_depth else bit_offset
            ) // 8
            bit_offset += field_bits
            if offset * 8 != bit_offset - field_bits or field_bits % 8:
                continue
            size = field_bits // 8
        else:
            field_bit_offset = (
                top_level_union_start if top_level_union_depth else bit_offset
            )
            if field_bit_offset % 8:
                field_bit_offset += 8 - (field_bit_offset % 8)
            offset = field_bit_offset // 8
            size = _c_field_size(c_type) * (array_length or 1)
            if top_level_union_depth:
                top_level_union_size = max(top_level_union_size, size * 8)
                top_level_union_has_field = True
            else:
                bit_offset = field_bit_offset + size * 8
        fields.append(
            {
                "name": name,
                "type": c_type,
                "array": array_length,
                "bits": field_bits,
                "offset": offset,
                "size": size,
                "signed": _c_field_is_signed(c_type),
            }
        )
        seen.add(name)
    return tuple(fields)


def _top_level_union_struct_body(body: str) -> str | None:
    position = 0
    while True:
        match = re.search(r"(?:^|\n)\s*union\s*\{", body[position:])
        if match is None:
            return None
        prefix_end = position + match.start()
        prefix = re.sub(r"/\*.*?\*/", "", body[:prefix_end], flags=re.DOTALL)
        if prefix.strip():
            return None
        union_open = position + match.end() - 1
        if body[:union_open].count("{") == body[:union_open].count("}"):
            break
        position = union_open + 1

    depth = 1
    index = union_open + 1
    while index < len(body) and depth:
        if body[index] == "{":
            depth += 1
        elif body[index] == "}":
            depth -= 1
        index += 1
    semicolon = body.find(";", index)
    if semicolon < 0 or body[index:semicolon].strip():
        return None
    union_body = body[union_open + 1 : index - 1]
    struct_match = re.search(r"(?:^|\n)\s*struct\s*\{", union_body)
    if struct_match is None:
        return None
    struct_open = struct_match.end() - 1
    depth = 1
    index = struct_open + 1
    while index < len(union_body) and depth:
        if union_body[index] == "{":
            depth += 1
        elif union_body[index] == "}":
            depth -= 1
        index += 1
    if depth != 0:
        return None
    return union_body[struct_open + 1 : index - 1]


def _c_field_size(c_type: str) -> int:
    return {
        "char": 1,
        "unsigned char": 1,
        "short": 2,
        "unsigned short": 2,
        "int": 4,
        "unsigned int": 4,
        "long long": 8,
        "unsigned long long": 8,
        "uint8_t": 1,
        "int8_t": 1,
        "uint16_t": 2,
        "int16_t": 2,
        "uint32_t": 4,
        "int32_t": 4,
        "uint64_t": 8,
        "int64_t": 8,
    }[c_type]


def _c_field_is_signed(c_type: str) -> bool:
    return c_type.startswith("int") or c_type in {"char", "short", "int", "long long"}


def _record_parser_function(record: dict[str, object]) -> list[str]:
    struct_name = str(record["struct_name"])
    record_type = int(cast(int, record["record_type"]))
    fields = cast(tuple[dict[str, object], ...], record["fields"])
    fields_by_name = {str(field["name"]): field for field in fields}
    minimum_size = (
        max(
            int(cast(int, field["offset"])) + int(cast(int, field["size"]))
            for field in fields
        )
        if fields
        else 56
    )
    lines = [
        f"static PyObject *parse_{struct_name}(Py_buffer *view) {{",
        "    const unsigned char *data;",
        "    PyObject *result;",
        f"    if (view->len < (Py_ssize_t){minimum_size}) {{",
        f"        PyErr_SetString(PyExc_ValueError, \"SMF type {record_type} "
        "record is shorter than its fixed C header structure\");",
        "        return NULL;",
        "    }",
        "    data = (const unsigned char *)view->buf;",
        f"    if (!validate_record_type(data, {record_type})) {{",
        f"        PyErr_SetString(PyExc_ValueError, \"SMF type {record_type} "
        "structured parser received bytes with the wrong record type\");",
        "        return NULL;",
        "    }",
        "    result = PyDict_New();",
        "    if (result == NULL) { return NULL; }",
    ]
    lines.extend(
        _field_assignment_lines(
            fields,
            base_expression="data",
            indent="    ",
        )
    )
    adjacent_section_fields = cast(
        tuple[dict[str, object], ...], record["adjacent_section_fields"]
    )
    if adjacent_section_fields:
        lines.extend(
            _adjacent_section_parser_lines(
                adjacent_section_fields,
                base_offset=minimum_size,
            )
        )
    lines.extend(_self_defining_triplet_parser_lines(fields))
    section_structs = cast(
        dict[str, tuple[dict[str, object], ...]], record["section_structs"]
    )
    special_structs = cast(
        dict[str, tuple[dict[str, object], ...]], record["special_structs"]
    )
    lines.extend(
        _variable_section_parser_lines(
            fields_by_name,
            section_structs,
        )
    )
    lines.extend(_section_directory_parser_lines(fields_by_name, section_structs))
    lines.extend(
        _special_record_action_lines(
            record_type,
            fields,
            fields_by_name,
            minimum_size=minimum_size,
        )
    )
    lines.extend(
        _special_overlay_parser_lines(
            record_type,
            fields_by_name,
            section_structs,
            special_structs,
        )
    )
    lines.extend(["    return result;", "}", ""])
    return lines


def _special_overlay_parser_lines(
    record_type: int,
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
) -> list[str]:
    lines: list[str] = []
    for action in SPECIAL_RECORD_ACTIONS.get(record_type, ()):
        emitter = _SPECIAL_OVERLAY_ACTION_EMITTERS.get(action.kind)
        if emitter is None:
            continue
        lines.extend(
            emitter(
                action=action,
                record_type=record_type,
                fields_by_name=fields_by_name,
                section_structs=section_structs,
                special_structs=special_structs,
            )
        )
    return lines


def _action_for_record_type(
    record_type: int,
    action_type: type[ActionT],
) -> ActionT | None:
    for action in SPECIAL_RECORD_ACTIONS.get(record_type, ()):
        if isinstance(action, action_type):
            return action
    return None


def _emit_smf119_ident_overlay(
    *,
    action: SpecialRecordAction,
    record_type: int,
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
) -> list[str]:
    del section_structs
    if not isinstance(action, Smf119IdentOverlayAction):
        return []
    return _smf119_parser_lines(
        record_type,
        fields_by_name,
        special_structs,
        action=action,
    )


def _emit_smf1154_common_overlay(
    *,
    action: SpecialRecordAction,
    record_type: int,
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
) -> list[str]:
    del section_structs
    if not isinstance(action, Smf1154CommonOverlayAction):
        return []
    return _smf1154_common_parser_lines(
        record_type,
        special_structs,
        fields_by_name=fields_by_name,
        action=action,
    )


def _emit_racf83_subtype1_security(
    *,
    action: SpecialRecordAction,
    record_type: int,
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
) -> list[str]:
    if not isinstance(action, Racf83Subtype1SecurityAction):
        return []
    return _racf_type83_subtype1_parser_lines(
        record_type,
        section_structs,
        special_structs,
        fields_by_name=fields_by_name,
        action=action,
    )


_SPECIAL_OVERLAY_ACTION_EMITTERS: dict[str, Callable[..., list[str]]] = {
    "smf1154_common_overlay": _emit_smf1154_common_overlay,
    "racf83_subtype1_security": _emit_racf83_subtype1_security,
    "smf119_ident_overlay": _emit_smf119_ident_overlay,
}


def _smf119_parser_lines(
    record_type: int,
    fields_by_name: dict[str, dict[str, object]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
    *,
    action: Smf119IdentOverlayAction | None = None,
) -> list[str]:
    typed_action = action
    if typed_action is None:
        typed_action = _action_for_record_type(record_type, Smf119IdentOverlayAction)
    if typed_action is None:
        return []
    triplet_fields = special_structs.get(typed_action.triplet_struct)
    ident_fields = special_structs.get(typed_action.ident_struct)
    if not triplet_fields or not ident_fields:
        return []
    triplet_field_map = _field_map(triplet_fields)
    triplet_directory_anchor_field = triplet_field_map.get(
        typed_action.triplet_directory_anchor_field
    )
    if triplet_directory_anchor_field is None:
        return []
    triplet_count_field = fields_by_name.get(typed_action.triplet_count_field)
    if triplet_count_field is None:
        triplet_count_field = triplet_field_map.get(typed_action.triplet_count_field)
    ident_offset_field = triplet_field_map.get(typed_action.ident_offset_field)
    ident_length_field = triplet_field_map.get(typed_action.ident_length_field)
    ident_count_field = triplet_field_map.get(typed_action.ident_count_field)
    if (
        triplet_count_field is None
        or ident_offset_field is None
        or ident_length_field is None
        or ident_count_field is None
    ):
        return []
    triplet_directory_offset = int(
        cast(int, triplet_directory_anchor_field["offset"])
    )
    triplet_max_count = _smf119_triplet_max_count(
        triplet_fields,
        fallback=typed_action.triplet_max_count,
    )
    minimum_triplet_bytes = max(
        _field_end_offset(field)
        for field in (
            triplet_count_field,
            ident_offset_field,
            ident_length_field,
            ident_count_field,
        )
    )
    lines = [
        f"    if (view->len >= (Py_ssize_t){minimum_triplet_bytes}) {{",
        "        unsigned long long smf119_triplet_count = "
        f"{_field_read_expression(triplet_count_field, base_expression='data')};",
        "        if (smf119_triplet_count > 0 && smf119_triplet_count <= "
        f"{triplet_max_count} && ",
        "            view->len >= (Py_ssize_t)("
        f"{triplet_directory_offset} + (smf119_triplet_count * 8))) {{",
        "            unsigned long long smf119_ident_offset = "
        f"{_field_read_expression(ident_offset_field, base_expression='data')};",
        "            unsigned long long smf119_ident_length = "
        f"{_field_read_expression(ident_length_field, base_expression='data')};",
        "            unsigned long long smf119_ident_count = "
        f"{_field_read_expression(ident_count_field, base_expression='data')};",
        "            if (set_long(result, \"SMF119SD_TRN\", "
        "smf119_triplet_count) < 0 ||",
        "                set_long(result, \"SMF119IDOff\", smf119_ident_offset) < 0 ||",
        "                set_long(result, \"SMF119IDLen\", smf119_ident_length) < 0 ||",
        "                set_long(result, \"SMF119IDNum\", smf119_ident_count) < 0) {",
        "                Py_DECREF(result);",
        "                return NULL;",
        "            }",
    ]
    lines.extend(
        _append_long_triplet_directory_lines(
            indent="            ",
            key=typed_action.directory_key,
            directory_expression=str(triplet_directory_offset),
            count_expression="smf119_triplet_count",
            inline_directory=True,
        )
    )
    lines.extend(
        [
        "            if (smf119_ident_count > 0 && smf119_ident_length > 0 &&",
        "                smf119_ident_offset <= (unsigned long long)view->len) {",
        "                unsigned long long smf119_ident_available = ",
        "                    (unsigned long long)view->len - smf119_ident_offset;",
        "                const unsigned char *smf119_ident = "
        "data + smf119_ident_offset;",
        "                if (smf119_ident_available > smf119_ident_length) {",
        "                    smf119_ident_available = smf119_ident_length;",
        "                }",
        ]
    )
    lines.extend(
        _field_assignment_lines(
            ident_fields,
            base_expression="smf119_ident",
            indent="                ",
            available_expression="smf119_ident_available",
            skip_names=typed_action.skip_ident_fields,
        )
    )
    lines.extend(
        [
            "            }",
            "        }",
            "    }",
        ]
    )
    return lines


def _smf119_triplet_max_count(
    triplet_fields: tuple[dict[str, object], ...],
    *,
    fallback: int | None,
) -> int:
    section_indexes = [
        int(match.group(1))
        for field in triplet_fields
        for match in [re.fullmatch(r"SMF119S(\d+)Off", str(field["name"]))]
        if match is not None
    ]
    if section_indexes:
        return max(section_indexes)
    if fallback is not None:
        return fallback
    return 1


def _smf1154_ctrp_anchor_offset(
    fields_by_name: dict[str, dict[str, object]] | None,
    *,
    fallback: int,
) -> int:
    if fields_by_name is None:
        return fallback
    for field_name in (
        "smf1154df1",
        "smf1154_df1",
        "SMFHDR1_Ext_Len",
    ):
        field = fields_by_name.get(field_name)
        if field is not None:
            return int(cast(int, field["offset"]))
    return fallback


def _smf1154_common_triplet_count(
    ctrp_field_map: dict[str, dict[str, object]],
) -> int:
    count = 0
    for field_name in ctrp_field_map:
        if not field_name.endswith("_offset"):
            continue
        prefix = field_name[: -len("_offset")]
        if (
            f"{prefix}_length" in ctrp_field_map
            and f"{prefix}_number" in ctrp_field_map
        ):
            count += 1
    return count if count > 0 else 1


def _smf1154_common_parser_lines(
    record_type: int,
    special_structs: dict[str, tuple[dict[str, object], ...]],
    *,
    fields_by_name: dict[str, dict[str, object]] | None = None,
    action: Smf1154CommonOverlayAction | None = None,
) -> list[str]:
    typed_action = action
    if typed_action is None:
        typed_action = _action_for_record_type(record_type, Smf1154CommonOverlayAction)
    if typed_action is None:
        return []
    ctrp_fields = special_structs.get(typed_action.ctrp_struct)
    common_fields = special_structs.get(typed_action.common_struct)
    if not ctrp_fields or not common_fields:
        return []
    ctrp_field_map = _field_map(ctrp_fields)
    if not all(name in ctrp_field_map for name in typed_action.required_ctrp_names):
        return []
    ctrp_anchor_offset = _smf1154_ctrp_anchor_offset(
        fields_by_name,
        fallback=24,
    )
    ctrp_anchor_length = int(cast(int, ctrp_field_map["smf1154_ctrp_trn"]["size"]))
    common_directory_count_expression = str(
        _smf1154_common_triplet_count(ctrp_field_map)
    )
    ctrp_length = _struct_size(ctrp_fields)
    common_length = _struct_size(common_fields)
    ctrp_offset_expression = _field_data_expression(
        ctrp_field_map["smf1154_c_offset"],
        base_expression="data + smf1154_ctrp",
    )
    ctrp_length_expression = _field_data_expression(
        ctrp_field_map["smf1154_c_length"],
        base_expression="data + smf1154_ctrp",
    )
    ctrp_subspec_offset_expression = _field_data_expression(
        ctrp_field_map["smf1154_subspec_offset"],
        base_expression="data + smf1154_ctrp",
    )
    ctrp_directory_offset = int(cast(int, ctrp_field_map["smf1154_c_offset"]["offset"]))
    lines = [
        "    {",
        "        unsigned long long smf1154_ctrp;",
        "        unsigned long long smf1154_common_offset;",
        "        unsigned long long smf1154_common_length;",
        "        unsigned long long smf1154_subspec_offset;",
        "        unsigned long long smf1154_subspec_count;",
        "        smf1154_ctrp = "
        f"{ctrp_anchor_offset} + read_unsigned_be(data + "
        f"{ctrp_anchor_offset}, {ctrp_anchor_length});",
        "        if (smf1154_ctrp + "
        f"{ctrp_length} <= (unsigned long long)view->len) {{",
        "            smf1154_common_offset = read_unsigned_be(",
        f"                {ctrp_offset_expression}, 4);",
        "            smf1154_common_length = read_unsigned_be(",
        f"                {ctrp_length_expression}, 2);",
        "            smf1154_subspec_offset = read_unsigned_be(",
        f"                {ctrp_subspec_offset_expression}, 4);",
        "            if (",
    ]
    ctrp_conditions = (
        (
            "smf1154_ctrp_trn",
            _field_read_expression(
                ctrp_field_map["smf1154_ctrp_trn"],
                base_expression="data + smf1154_ctrp",
            ),
        ),
        ("smf1154_c_offset", "smf1154_common_offset"),
        ("smf1154_c_length", "smf1154_common_length"),
        (
            "smf1154_c_number",
            _field_read_expression(
                ctrp_field_map["smf1154_c_number"],
                base_expression="data + smf1154_ctrp",
            ),
        ),
        ("smf1154_subspec_offset", "smf1154_subspec_offset"),
        (
            "smf1154_subspec_length",
            _field_read_expression(
                ctrp_field_map["smf1154_subspec_length"],
                base_expression="data + smf1154_ctrp",
            ),
        ),
        (
            "smf1154_subspec_number",
            _field_read_expression(
                ctrp_field_map["smf1154_subspec_number"],
                base_expression="data + smf1154_ctrp",
            ),
        ),
    )
    for index, (field_name, expression) in enumerate(ctrp_conditions):
        suffix = " ||" if index < len(ctrp_conditions) - 1 else ") {"
        lines.append(
            f"                set_long(result, \"{field_name}\", "
            f"{expression}) < 0{suffix}"
        )
    lines.extend(
        [
            "                Py_DECREF(result);",
            "                return NULL;",
            "            }",
        ]
    )
    lines.extend(
        _append_long_triplet_directory_lines(
            indent="            ",
            key=typed_action.common_directory_key,
            directory_expression=f"smf1154_ctrp + {ctrp_directory_offset}",
            count_expression=common_directory_count_expression,
        )
    )
    lines.extend(
        [
            f"            if (smf1154_common_offset + {common_length} <= ",
            "                (unsigned long long)view->len &&",
            f"                smf1154_common_length >= {common_length}) {{",
            "                if (",
        ]
    )
    common_conditions = list(
        _field_assignment_conditions(
            common_fields,
            base_expression="data + smf1154_common_offset",
        )
    )
    for index, condition in enumerate(common_conditions):
        suffix = " ||" if index < len(common_conditions) - 1 else ") {"
        lines.append(f"                    {condition}{suffix}")
    lines.extend(
        [
            "                    Py_DECREF(result);",
            "                    return NULL;",
            "                }",
            "            }",
            "            if (smf1154_subspec_offset + 4 <= ",
            "                (unsigned long long)view->len) {",
            "                smf1154_subspec_count = read_unsigned_be(",
            "                    data + smf1154_subspec_offset, 2);",
        ]
    )
    lines.extend(
        _append_long_triplet_directory_lines(
            indent="                ",
            key=typed_action.subspec_directory_key,
            directory_expression="smf1154_subspec_offset + 4",
            count_expression="smf1154_subspec_count",
        )
    )
    lines.extend(
        [
            "            }",
            "        }",
            "    }",
        ]
    )
    return lines


def _special_record_action_lines(
    record_type: int,
    fields: tuple[dict[str, object], ...],
    fields_by_name: dict[str, dict[str, object]],
    *,
    minimum_size: int,
) -> list[str]:
    lines: list[str] = []
    for action in SPECIAL_RECORD_ACTIONS.get(record_type, ()):
        if isinstance(action, LongTripletDirectoryAction):
            count_field = fields_by_name.get(action.count_field)
            if count_field is None:
                continue
            if action.directory == "fixed_end":
                directory_expression = str(minimum_size)
            else:
                continue
            count_data_expression = _field_data_expression(
                count_field,
                base_expression="data",
            )
            lines.extend(
                _long_triplet_directory_action_lines(
                    key=action.key,
                    directory_expression=directory_expression,
                    count_expression=(
                        "read_unsigned_be("
                        f"{count_data_expression}, "
                        f"{int(cast(int, count_field['size']))})"
                    ),
                )
            )
            continue
        if isinstance(action, CompactSectionDirectoryFallbackAction):
            anchor_field = fields_by_name.get(action.anchor_field)
            relocate_field = fields_by_name.get(action.relocate_field)
            if anchor_field is None or relocate_field is None:
                continue
            relocate_offset = int(cast(int, relocate_field["offset"])) + (
                action.relocate_shift
            )
            count_offset = relocate_offset + action.count_delta
            lines.extend(
                _compact_section_directory_fallback_action_lines(
                    key=action.key,
                    anchor_expression=str(int(cast(int, anchor_field["offset"]))),
                    relocate_offset=relocate_offset,
                    count_offset=count_offset,
                )
            )
            continue
        continue
    return lines


def _long_triplet_directory_action_lines(
    *,
    key: str,
    directory_expression: str,
    count_expression: str,
) -> list[str]:
    return _append_long_triplet_directory_lines(
        indent="    ",
        key=key,
        directory_expression=directory_expression,
        count_expression=count_expression,
    )


def _append_long_triplet_directory_lines(
    *,
    indent: str,
    key: str,
    directory_expression: str,
    count_expression: str,
    inline_directory: bool = False,
) -> list[str]:
    inner_indent = f"{indent}    "
    if inline_directory:
        return [
            f"{indent}if (append_self_defining_long_triplet_directory(",
            f"{inner_indent}result, \"{key}\", data, view->len, "
            f"{directory_expression},",
            f"{inner_indent}{count_expression}) < 0) {{",
            f"{inner_indent}Py_DECREF(result);",
            f"{inner_indent}return NULL;",
            f"{indent}}}",
        ]
    return [
        f"{indent}if (append_self_defining_long_triplet_directory(",
        f"{inner_indent}result, \"{key}\", data, view->len,",
        f"{inner_indent}{directory_expression},",
        f"{inner_indent}{count_expression}) < 0) {{",
        f"{inner_indent}Py_DECREF(result);",
        f"{inner_indent}return NULL;",
        f"{indent}}}",
    ]


def _compact_section_directory_fallback_action_lines(
    *,
    key: str,
    anchor_expression: str,
    relocate_offset: int,
    count_offset: int,
) -> list[str]:
    offset_expression = f"read_unsigned_be(data + {relocate_offset}, 2)"
    count_expression = f"read_unsigned_be(data + {count_offset}, 2)"
    return [
        f"    if (PyDict_GetItemString(result, \"{key}\") == NULL && ",
        f"        {offset_expression} != 0 &&",
        f"        {count_expression} != 0) {{",
        "        if (append_self_defining_section_directory(",
        f"            result, \"{key}\", data, view->len,",
        f"            {anchor_expression} + read_unsigned_be(",
        f"                data + {relocate_offset}, 2),",
        f"            {count_expression}) < 0) {{",
        "            Py_DECREF(result);",
        "            return NULL;",
        "        }",
        "    }",
    ]


def _record_adjacent_section_fields(
    record_type: int, structs: dict[str, str]
) -> tuple[dict[str, object], ...]:
    body = structs.get(f"smf{record_type}psg")
    if body is None:
        return ()
    fields = _record_struct_fields(body)
    return fields if _self_defining_triplets(fields) else ()


def _adjacent_section_parser_lines(
    fields: tuple[dict[str, object], ...], *, base_offset: int
) -> list[str]:
    minimum_size = base_offset + max(
        int(cast(int, field["offset"])) + int(cast(int, field["size"]))
        for field in fields
    )
    lines = [f"    if (view->len >= (Py_ssize_t){minimum_size}) {{"]
    lines.extend(
        _field_assignment_lines(
            fields,
            base_expression=f"data + {base_offset}",
            indent="        ",
        )
    )
    for offset_field, length_field, count_field in _self_defining_triplets(fields):
        data_type = base_offset + int(cast(int, offset_field["offset"]))
        section_offset_field_offset = base_offset + int(
            cast(int, offset_field["offset"])
        )
        section_length_field_offset = base_offset + int(
            cast(int, length_field["offset"])
        )
        section_count_field_offset = base_offset + int(cast(int, count_field["offset"]))
        lines.extend(
            [
                "        if (append_self_defining_triplet_sections(",
                "            result, \"relocate_sections\", data, view->len,",
                f"            {data_type},",
                "            read_unsigned_be(data + "
                f"{section_offset_field_offset}, 4),",
                "            read_unsigned_be(data + "
                f"{section_length_field_offset}, 2),",
                "            read_unsigned_be(data + "
                f"{section_count_field_offset}, 2)) < 0) {{",
                "            Py_DECREF(result);",
                "            return NULL;",
                "        }",
            ]
        )
    lines.append("    }")
    return lines


def _racf_type83_subtype1_parser_lines(
    record_type: int,
    section_structs: dict[str, tuple[dict[str, object], ...]],
    special_structs: dict[str, tuple[dict[str, object], ...]],
    *,
    fields_by_name: dict[str, dict[str, object]] | None = None,
    action: Racf83Subtype1SecurityAction | None = None,
) -> list[str]:
    typed_action = action
    if typed_action is None:
        typed_action = _action_for_record_type(
            record_type,
            Racf83Subtype1SecurityAction,
        )
    if typed_action is None:
        return []
    security_fields = special_structs.get(typed_action.security_struct)
    if not security_fields:
        return []
    header_integer_fields = typed_action.header_integer_fields
    header_integer_field_map = dict(header_integer_fields)
    subtype_primary_offset = (
        typed_action.subtype_primary_offset
        if typed_action.subtype_primary_offset is not None
        else 18
    )
    subtype_secondary_offset = (
        typed_action.subtype_secondary_offset
        if typed_action.subtype_secondary_offset is not None
        else 22
    )
    if fields_by_name is not None:
        subtype_anchor_field = fields_by_name.get("smf83df1")
        if subtype_anchor_field is not None:
            subtype_primary_offset = int(cast(int, subtype_anchor_field["offset"]))
            subtype_secondary_offset = subtype_primary_offset + 4
    variable_section_layout = _variable_section_layout(
        section_structs.get(typed_action.variable_section_struct, ())
    )
    lines = [
        f"    if (view->len >= (Py_ssize_t){subtype_primary_offset + 2} &&",
        "        set_long(result, \"smf83typ\",",
        f"        read_unsigned_be(data + {subtype_primary_offset}, 2)) < 0) {{",
        "        Py_DECREF(result);",
        "        return NULL;",
        "    }",
        "    if (view->len >= 48 &&",
        "        ((!is_packed_smf_date(data + 10) &&",
        "        is_packed_smf_date(data + 6) &&",
        "        read_unsigned_be(data + "
        f"{subtype_primary_offset}, 2) == "
        f"{typed_action.subtype_value}) ||",
        "        ((is_packed_smf_date(data + 10) ||",
        "        !is_packed_smf_date(data + 6)) &&",
        "        view->len >= 52 && read_unsigned_be(data + "
        f"{subtype_secondary_offset}, 2) == "
        f"{typed_action.subtype_value}))) {{",
        "        unsigned long long smf83_subtype_offset;",
        "        unsigned long long smf83_sds_offset;",
        "        unsigned long long security_offset;",
        "        smf83_subtype_offset =",
        "            (!is_packed_smf_date(data + 10) &&",
        "            is_packed_smf_date(data + 6)) ? "
        f"{subtype_primary_offset} : "
        f"{subtype_secondary_offset};",
        "        smf83_sds_offset = smf83_subtype_offset + 2;",
        "        if (read_unsigned_be(data + smf83_sds_offset, 2) != "
        f"{typed_action.sds_type_value}) {{",
        "            return result;",
        "        }",
        "        if (smf83_subtype_offset == "
        f"{subtype_secondary_offset} &&",
        "            set_bytes(result, \"smf83ssi\", data + 18, 4) < 0) {",
        "            Py_DECREF(result);",
        "            return NULL;",
        "        }",
        "        if (",
    ]
    for index, (field_name, expression) in enumerate(header_integer_fields):
        suffix = " ||" if index < len(header_integer_fields) - 1 else ") {"
        lines.append(
            f"            set_long(result, \"{field_name}\", {expression}) < 0{suffix}"
        )
    lines.extend(
        [
            "            Py_DECREF(result);",
            "            return NULL;",
            "        }",
        ]
    )
    if variable_section_layout is not None:
        type_size, length_size, data_offset = variable_section_layout
        lines.extend(
            [
                f"        if ({header_integer_field_map['smf83od2']} != 0 &&",
                f"            {header_integer_field_map['smf83nd2']} != 0 &&",
                "            append_self_defining_variable_sections(",
                "            result, \"relocate_sections\", data, view->len,",
                f"            {header_integer_field_map['smf83od2']},",
                f"            {header_integer_field_map['smf83nd2']},",
                f"            {type_size}, {length_size}, {data_offset}) < 0) {{",
                "            PyErr_Clear();",
                "        }",
            ]
        )
    lines.extend(
        [
            f"        security_offset = {header_integer_field_map['smf83od1']};",
            f"        if ({header_integer_field_map['smf83nd1']} != 0 &&",
            f"            {header_integer_field_map['smf83ld1']} >= "
            f"{typed_action.security_minimum_length} &&",
            "            security_offset <= (unsigned long long)view->len &&",
            "            security_offset + "
            f"{typed_action.security_minimum_length} <= "
            "(unsigned long long)view->len) {",
            "            if (",
        ]
    )
    security_conditions = list(
        _field_assignment_conditions(
            security_fields,
            base_expression="data + security_offset",
        )
    )
    for index, condition in enumerate(security_conditions):
        suffix = " ||" if index < len(security_conditions) - 1 else ") {"
        lines.append(f"                {condition}{suffix}")
    lines.extend(
        [
            "                Py_DECREF(result);",
            "                return NULL;",
            "            }",
            "        }",
            "    }",
        ]
    )
    return lines


def _record_section_structs(
    record_type: int, structs: dict[str, str]
) -> dict[str, tuple[dict[str, object], ...]]:
    section_structs: dict[str, tuple[dict[str, object], ...]] = {}
    for name in (f"smf{record_type}var", f"smf{record_type}vr2"):
        body = structs.get(name)
        if body is None:
            continue
        fields = _record_struct_fields(body)
        if _variable_section_layout(fields) is not None:
            section_structs[name] = fields
    return section_structs


def _record_special_structs(
    record_type: int, structs: dict[str, str]
) -> dict[str, tuple[dict[str, object], ...]]:
    special_structs: dict[str, tuple[dict[str, object], ...]] = {}
    for name in SPECIAL_RECORD_STRUCT_NAMES.get(record_type, ()):
        body = structs.get(name)
        if body is None:
            continue
        special_structs[name] = _record_struct_fields(body)
    return special_structs


def _field_map(
    fields: tuple[dict[str, object], ...],
) -> dict[str, dict[str, object]]:
    return {
        str(field["name"]): field
        for field in fields
        if not str(field["name"]).endswith("_end")
    }


def _field_end_offset(field: dict[str, object]) -> int:
    return int(cast(int, field["offset"])) + int(cast(int, field["size"]))


def _struct_size(fields: tuple[dict[str, object], ...]) -> int:
    return max(
        _field_end_offset(field)
        for field in fields
        if not str(field["name"]).endswith("_end")
    )


def _field_data_expression(field: dict[str, object], *, base_expression: str) -> str:
    offset = int(cast(int, field["offset"]))
    if offset == 0:
        return base_expression
    return f"{base_expression} + {offset}"


def _field_read_expression(field: dict[str, object], *, base_expression: str) -> str:
    reader = "read_signed_be" if bool(field["signed"]) else "read_unsigned_be"
    return (
        f"{reader}({_field_data_expression(field, base_expression=base_expression)}, "
        f"{int(cast(int, field['size']))})"
    )


def _guarded_field_assignment_lines(
    field: dict[str, object],
    *,
    base_expression: str,
    available_expression: str,
    indent: str,
) -> list[str]:
    field_name = str(field["name"])
    size = int(cast(int, field["size"]))
    available = _field_end_offset(field)
    if int(cast(int, field["array"])):
        data_expression = _field_data_expression(
            field,
            base_expression=base_expression,
        )
        return [
            f"{indent}if ({available_expression} >= {available} &&",
            f"{indent}    set_bytes(result, \"{field_name}\", ",
            f"{indent}    {data_expression}, {size}) < 0) {{",
            f"{indent}    Py_DECREF(result);",
            f"{indent}    return NULL;",
            f"{indent}}}",
        ]
    read_expression = _field_read_expression(field, base_expression=base_expression)
    return [
        f"{indent}if ({available_expression} >= {available} &&",
        f"{indent}    set_long(result, \"{field_name}\", ",
        f"{indent}    {read_expression}) < 0) {{",
        f"{indent}    Py_DECREF(result);",
        f"{indent}    return NULL;",
        f"{indent}}}",
    ]


def _field_assignment_lines(
    fields: tuple[dict[str, object], ...],
    *,
    base_expression: str,
    indent: str,
    available_expression: str | None = None,
    skip_names: tuple[str, ...] = (),
) -> list[str]:
    lines: list[str] = []
    for field in fields:
        field_name = str(field["name"])
        if field_name in skip_names or field_name.endswith("_end"):
            continue
        if available_expression is not None:
            lines.extend(
                _guarded_field_assignment_lines(
                    field,
                    base_expression=base_expression,
                    available_expression=available_expression,
                    indent=indent,
                )
            )
            continue
        condition = _field_assignment_conditions(
            (field,),
            base_expression=base_expression,
        )[0]
        lines.extend(
            [
                f"{indent}if ({condition}) {{",
                f"{indent}    Py_DECREF(result);",
                f"{indent}    return NULL;",
                f"{indent}}}",
            ]
        )
    return lines


def _field_assignment_conditions(
    fields: tuple[dict[str, object], ...],
    *,
    base_expression: str,
    skip_names: tuple[str, ...] = (),
) -> tuple[str, ...]:
    conditions: list[str] = []
    for field in fields:
        field_name = str(field["name"])
        if field_name in skip_names or field_name.endswith("_end"):
            continue
        offset = int(cast(int, field["offset"]))
        size = int(cast(int, field["size"]))
        data_expression = (
            base_expression if offset == 0 else f"{base_expression} + {offset}"
        )
        if int(cast(int, field["array"])):
            conditions.append(
                f"set_bytes(result, \"{field_name}\", {data_expression}, {size}) < 0"
            )
            continue
        reader = "read_signed_be" if bool(field["signed"]) else "read_unsigned_be"
        conditions.append(
            f"set_long(result, \"{field_name}\", {reader}({data_expression}, "
            f"{size})) < 0"
        )
    return tuple(conditions)


def _variable_section_layout(
    fields: tuple[dict[str, object], ...]
) -> tuple[int, int, int] | None:
    if len(fields) < 2:
        return None
    type_field = fields[0]
    length_field = fields[1]
    type_size = int(cast(int, type_field["size"]))
    length_size = int(cast(int, length_field["size"]))
    if type_size not in (1, 2) or length_size not in (1, 2):
        return None
    if not _field_name_contains(type_field, ("typ", "dtp", "tp")):
        return None
    if not _field_name_contains(length_field, ("len", "lng", "dln", "dl")):
        return None
    data_offset = int(cast(int, length_field["offset"])) + length_size
    return type_size, length_size, data_offset


def _variable_section_parser_lines(
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]],
) -> list[str]:
    lines: list[str] = []
    for offset_field, count_field in _section_directory_pairs(fields_by_name):
        offset_field_name = str(offset_field["name"])
        key = _section_directory_key(offset_field_name)
        struct_name = _variable_section_struct_name(offset_field_name)
        section_fields = section_structs.get(struct_name)
        if section_fields is None:
            continue
        layout = _variable_section_layout(section_fields)
        if layout is None:
            continue
        type_size, length_size, data_offset = layout
        relocate_offset = int(cast(int, offset_field["offset"]))
        relocate_count_offset = int(cast(int, count_field["offset"]))
        lines.extend(
            [
                "    if (append_self_defining_variable_sections(",
                f"        result, \"{key}\", data, view->len,",
                f"        read_unsigned_be(data + {relocate_offset}, 2),",
                "        read_unsigned_be(data + "
                f"{relocate_count_offset}, 2),",
                f"        {type_size}, {length_size}, {data_offset}) < 0) {{",
                "        Py_DECREF(result);",
                "        return NULL;",
                "    }",
            ]
        )
    return lines


def _variable_section_struct_name(offset_field_name: str) -> str:
    if offset_field_name.endswith("rl2"):
        return f"{offset_field_name[:-3]}vr2"
    if offset_field_name.endswith("rel"):
        return f"{offset_field_name[:-3]}var"
    return offset_field_name


def _self_defining_triplet_parser_lines(
    fields: tuple[dict[str, object], ...],
) -> list[str]:
    lines: list[str] = []
    for offset_field, length_field, count_field in _self_defining_triplets(fields):
        data_type = int(cast(int, offset_field["offset"]))
        section_offset_field_offset = int(cast(int, offset_field["offset"]))
        section_length_field_offset = int(cast(int, length_field["offset"]))
        section_count_field_offset = int(cast(int, count_field["offset"]))
        lines.extend(
            [
                "    if (append_self_defining_triplet_sections(",
                "        result, \"relocate_sections\", data, view->len,",
                f"        {data_type},",
                f"        read_unsigned_be(data + {section_offset_field_offset}, 4),",
                f"        read_unsigned_be(data + {section_length_field_offset}, 2),",
                "        read_unsigned_be(data + "
                f"{section_count_field_offset}, 2)) < 0) {{",
                "        Py_DECREF(result);",
                "        return NULL;",
                "    }",
            ]
        )
    return lines


def _self_defining_triplets(
    fields: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], dict[str, object], dict[str, object]], ...]:
    fields_by_offset = {int(cast(int, field["offset"])): field for field in fields}
    triplets: list[tuple[dict[str, object], dict[str, object], dict[str, object]]] = []
    for field in fields:
        offset = int(cast(int, field["offset"]))
        if int(cast(int, field["size"])) != 4:
            continue
        length_field = fields_by_offset.get(offset + 4)
        count_field = fields_by_offset.get(offset + 6)
        if length_field is None or count_field is None:
            continue
        if int(cast(int, length_field["size"])) != 2:
            continue
        if int(cast(int, count_field["size"])) != 2:
            continue
        if not _looks_like_section_triplet(field, length_field, count_field):
            continue
        triplets.append((field, length_field, count_field))
    return tuple(triplets)


def _looks_like_section_triplet(
    offset_field: dict[str, object],
    length_field: dict[str, object],
    count_field: dict[str, object],
) -> bool:
    return (
        _field_name_contains(offset_field, ("off", "ofs", "rel", "rba", "of"))
        and _field_name_contains(length_field, ("len", "lng", "siz", "ln"))
        and _field_name_contains(count_field, ("cnt", "ct", "num", "nbr", "on"))
    )


def _field_name_contains(field: dict[str, object], tokens: tuple[str, ...]) -> bool:
    name = str(field["name"]).lower()
    return any(token in name for token in tokens)


def _section_directory_parser_lines(
    fields_by_name: dict[str, dict[str, object]],
    section_structs: dict[str, tuple[dict[str, object], ...]] | None = None,
) -> list[str]:
    lines: list[str] = []
    for offset_field, count_field in _section_directory_pairs(fields_by_name):
        if section_structs is not None:
            struct_name = _variable_section_struct_name(str(offset_field["name"]))
            if struct_name in section_structs:
                continue
        key = _section_directory_key(str(offset_field["name"]))
        relocate_offset = int(cast(int, offset_field["offset"]))
        relocate_count_offset = int(cast(int, count_field["offset"]))
        lines.extend(
            [
                "    if (append_self_defining_section_directory(",
                f"        result, \"{key}\", data, view->len,",
                f"        read_unsigned_be(data + {relocate_offset}, 2),",
                f"        read_unsigned_be(data + {relocate_count_offset}, 2)) < 0) {{",
                "        Py_DECREF(result);",
                "        return NULL;",
                "    }",
            ]
        )
    return lines


def _section_directory_pairs(
    fields_by_name: dict[str, dict[str, object]],
) -> tuple[tuple[dict[str, object], dict[str, object]], ...]:
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    for field_name, field in fields_by_name.items():
        if not field_name.endswith(("rel", "rl2")):
            continue
        count_name = f"{field_name[:-3]}cnt" if field_name.endswith("rel") else None
        if field_name.endswith("rl2"):
            count_name = f"{field_name[:-3]}ct2"
        if count_name is None or count_name not in fields_by_name:
            continue
        count_field = fields_by_name[count_name]
        if int(cast(int, field["size"])) != 2:
            continue
        if int(cast(int, count_field["size"])) != 2:
            continue
        pairs.append((field, count_field))
    return tuple(pairs)


def _section_directory_key(offset_field_name: str) -> str:
    if offset_field_name.endswith("rl2"):
        return "extended_relocate_sections"
    return "relocate_sections"

