# Read Structured Records From A Dataset

Use `read_structured_dataset()` when the SMF data is in a z/OS dataset and you want parsed fields instead of raw records.

```python
from pysmf import read_structured_dataset

for record in read_structured_dataset(
    "USER.SMF.UNLOAD(0)",
    record_types={80},
    errors="skip",
):
    print(
        record.offset,
        record.record_type,
        record.subtype,
        record.system_id_text,
    )
```

`record_types` keeps the scan focused. `errors="skip"` lets a broad scan continue if pySMF can read a record header but does not yet have structured parser support for that record body.

Structured records expose decoded fields, raw fields, sections, and source metadata:

```python
for record in read_structured_dataset("USER.SMF.UNLOAD(0)", record_types={80}, errors="skip"):
    print(record["smf80evt"])
    print(record.clean_field_text("smf80usr"))
    print(record.raw_fields["smf80usr"])

    for section in record.sections:
        if section.clean_text:
            print(section.data_type, section.offset, section.clean_text)
```
