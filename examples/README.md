# pySMF Examples

These examples show the usual pySMF workflows with the simplified API.

pySMF is intended to parse real SMF data on z/OS, where it can use IBM C headers and the native extension built from those headers.

## Examples

- [Read Structured Records From A Dataset](read-structured-dataset.md)
- [Find RACF Type 80 Events](racf-type-80-events.md)
- [Find User IDs In Decoded Text](find-user-ids.md)
- [Read An SMF Unload File](read-unload-file.md)

## Common Pattern

For most application code, start with `read_structured_dataset()` or `read_structured_file()`.

```python
from pysmf import read_structured_dataset

for record in read_structured_dataset("USER.SMF.UNLOAD(0)", record_types={80}, errors="skip"):
    print(record.record_type, record.subtype, record.system_id_text)
```

Use `errors="skip"` when scanning broad data and you want to continue past record types that do not yet have structured parser coverage.
