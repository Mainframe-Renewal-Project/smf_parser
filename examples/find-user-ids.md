# Find User IDs In Decoded Text

Structured records can expose decoded text from fields and variable sections. This example looks for values that resemble RACF user IDs.

`decoded_tokens()` splits decoded field and section text into candidate words, which works well for short IDs and command names.

```python
from collections import Counter

from pysmf import read_structured_dataset

user_counts: Counter[str] = Counter()

for record in read_structured_dataset(
    "USER.SMF.UNLOAD(0)",
    record_types={80},
    errors="skip",
):
    for user_id in record.decoded_tokens(min_length=2, max_length=8):
        if user_id.isdigit():
            continue
        if any(character.isalpha() or character in "#$@" for character in user_id):
            user_counts[user_id] += 1

for user_id, count in user_counts.most_common(25):
    print(f"{user_id:8} {count}")
```

Use `decoded_fields()` when you want field names with the decoded values:

```python
for name, text in record.decoded_fields().items():
    print(name, text)
```

Use `find_text()` when you already know the user ID you care about:

```python
for record in read_structured_dataset("USER.SMF.UNLOAD(0)", record_types={80}, errors="skip"):
    if record.find_text("USER123", token=True):
        print(record.offset, record.record_type, record.clean_field_text("smf80usr"))
```
