# pySMF

pySMF is a Python API for reading and interpreting z/OS SMF unloads.

Real SMF parsing is intended to run on z/OS. The parser relies on IBM-provided
z/OS C SMF headers and a native extension built against those headers; copied
headers on Linux or Windows are useful for source reference, but they do not
provide a meaningful supported parsing runtime on those platforms.

## SMF record coverage

The API accepts SMF records only when the package was built with a matching IBM
C header for that record type. Current registry coverage is:

| SMF record type(s) | Backing IBM header(s) | Notes |
| --- | --- | --- |
| 0-54 | `IFASMFR`, `IFASMFR1`-`IFASMFR5` | IBM common SMF record range headers. |
| 80-103 | `IFASMFR9`, `IFASMFRA` | RACF/security and later common SMF range headers. |
| 14, 17, 18, 19, 21, 22 | `IFGSMF14`, `IGGSMF17`, `IGGSMF18`, `IGGSMF19`, `IGESMF21`, `IOSDSMFR` | Selected data set, catalog, and I/O related records. |
| 24-26, 41-43, 45, 47-49, 52-58 | `IAZSMF*`, `ITVSMF41`, `IGWSMF` | Selected JES, TSO, and system service records. |
| 60-62, 64, 84, 85, 87, 88, 90, 92, 94, 97, 98 | `IDASMF*`, `IAZSMF84`, `CBRSMF`, `ISGYSMFR`, `IXGSMF88`, `IFBSMF90`, `CNZMYSMF`, `BPXYSMFR`, `IECSMF94`, `IWMSMF*`, `IHAHR098` | Selected VSAM, RACF/z/OS Unix, logger, console, and system records. |
| 106, 113, 119, 124, 125, 983, 984, 1153, 1154, 1156 | `HWISMF6A`, `HISYSMFR`, `EZASMF`, `IOSDS124`, `GTZZSMF1`, `IOSDS983`, `IOSDS984`, `IAZS1153`, `IFAR1154`, `IAZS1154`, `CSVS1156` | Selected hardware, TCP/IP, I/O, and high-numbered IBM extension records. |

This table describes record admission and header-backed common parsing. Rich
body-level Python wrappers can be added incrementally on top of these compiled
headers.

## Usage

```python
from pysmf import read_file

for record in read_file("smf.unload"):
    print(record.record_type, record.subtype, record.header.system_id_text, record.c_headers)
```

For most application code, use the structured readers. They read records,
dispatch to the generated native parsers built from matching IBM C headers, and
yield `StructuredSMFRecord` objects directly.

```python
from pysmf import read_structured_dataset

for structured in read_structured_dataset(
    "USER.SMF.UNLOAD(0)", record_types={80}, errors="skip"
):
    print(
        structured.record_type,
        structured["smf80evt"],
        structured.field_text("smf80usr"),
        structured.field_text("smf80jbn"),
    )
```

`StructuredSMFRecord.source` retains the original `SMFRecord` when the record was
created by a reader, and convenience properties expose common metadata:
`offset`, `subtype`, `system_id_text`, and `subsystem_id_text`.

Lower-level code can still call `parse_record()` directly when it already has one
SMF record and wants unsupported or malformed structured records to raise.

If a record type has admission support but no structured parser yet, use
`errors="skip"` to continue past it. Additional parser generation coverage
should plug into the same API rather than adding separate public entry points for
each SMF family.

On z/OS systems with ZOAU installed, SMF unloads can also be read directly from
datasets. ZOAU is optional and is not declared as a package dependency because
`zoautil_py` is not distributed on PyPI.

```python
from pysmf import read_dataset

for record in read_dataset("USER.SMF.UNLOAD(0)", system_ids={"DBRA"}):
    print(record.record_type, record.subtype)
```

For large unloads or GDGs, pass `record_types` to avoid returning records the
caller will discard. On native z/OS VBS dataset reads, pySMF applies this filter
after spanned records are reconstructed.

```python
from pysmf import read_dataset

for record in read_dataset("USER.SMF.UNLOAD(0)", record_types={80}):
    print(record.record_type, record.subtype)
```

For generation data groups, pass the relative or absolute generation data set
name exactly as ZOAU expects it, such as `USER.SMF.UNLOAD(0)`,
`USER.SMF.UNLOAD(-1)`, or `USER.SMF.UNLOAD.G0001V00`.

`read_file()` and `read_records()` support two binary forms:

- `record_format="smf"`: each record starts with the SMF record length and
  segment descriptor from the SMF header.
- `record_format="rdw"`: each record is prefixed by an external four-byte RDW,
  followed by the SMF record bytes.

The default `record_format="auto"` detects those forms for seekable inputs.

`read_dataset()` uses `zoautil_py.datasets.read_as_bytes()` and supports the same
record formats. It detects whether each returned dataset record is already an
SMF record or still contains an external RDW.

## Build

During package build on z/OS, `setup.py` compiles a native parser extension and
the supported SMF headers from the z/OS C include paths. The default search
starts at `/usr/include/zos`, also checks the adjacent IBM header directory
(`/usr/include/IBM`), and includes their common parent for headers that live
outside either subdirectory. Set `PYSMF_ZOS_INCLUDE` or
`PYSMF_IBM_INCLUDE` before building to point at different header locations.
At runtime, generic SMF header parsing uses the native extension and
the compiled support manifest generated by that build. Records are not yielded
unless compiled SMF record type support is available.
