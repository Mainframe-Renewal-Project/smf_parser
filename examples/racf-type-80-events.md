# Find RACF Type 80 Events

SMF type 80 records contain RACF event data. This example prints the event code, qualifier, user, job name, and system for each structured type 80 record.

```python
from pysmf import read_structured_dataset

for record in read_structured_dataset(
    "USER.SMF.UNLOAD(0)",
    record_types={80},
    errors="skip",
):
    print(
        record.offset,
        record["smf80evt"],
        record["smf80evq"],
        record.clean_field_text("smf80usr"),
        record.clean_field_text("smf80jbn"),
        record.system_id_text,
    )
```

To look for command-like RACF events, filter on the event code:

```python
COMMAND_EVENT_CODES = {4, 6}

for record in read_structured_dataset("USER.SMF.UNLOAD(0)", record_types={80}, errors="skip"):
    event_code = int(record["smf80evt"])
    if event_code not in COMMAND_EVENT_CODES:
        continue

    print(
        record.offset,
        event_code,
        record.clean_field_text("smf80usr"),
        record.clean_field_text("smf80jbn"),
    )
```

Variable sections can contain command text or related RACF data:

```python
for section in record.sections + record.extended_sections:
    if section.clean_text:
        print(section.data_type, section.clean_text)
```
