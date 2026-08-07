# smf_parser

Python tools for reading and interpreting z/OS SMF unloads.

The first API layer handles SMF record boundaries, standard and extended SMF
headers, EBCDIC fixed-width text fields, and discovery of the retained z/OS C
headers that can back generated record-specific wrappers.

```python
from smf_parser import HeaderCatalog, read_file

for record in read_file("smf.unload"):
    print(record.record_type, record.subtype, record.header.system_id_text)

catalog = HeaderCatalog.discover()
print(catalog.for_record_type(92))
```

On z/OS systems with ZOAU configured, SMF unloads can also be read directly from
datasets. ZOAU is optional and is not declared as a package dependency because
`zoautil_py` is not distributed on PyPI.

```python
from smf_parser import read_dataset

for record in read_dataset("USER.SMF.UNLOAD"):
    print(record.record_type, record.subtype)
```

`read_file()` and `read_records()` support two binary forms:

- `record_format="smf"`: each record starts with the SMF record length and
  segment descriptor from the SMF header.
- `record_format="rdw"`: each record is prefixed by an external four-byte RDW,
  followed by the SMF record bytes.

The default `record_format="auto"` detects those forms for seekable inputs.

`read_dataset()` uses `zoautil_py.datasets.read_as_bytes()` and supports the same
record formats. It detects whether each returned dataset record is already an
SMF record or still contains an external RDW.
