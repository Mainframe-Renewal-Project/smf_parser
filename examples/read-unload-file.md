# Read An SMF Unload File

Use `read_structured_file()` for local or z/OS Unix files that contain SMF records.

```python
from pysmf import read_structured_file

for record in read_structured_file("smf.unload", errors="skip"):
    print(record.offset, record.record_type, record.subtype, record.system_id_text)
```

If you only need record headers, use `read_file()` instead:

```python
from pysmf import read_file

for record in read_file("smf.unload"):
    print(record.offset, record.record_type, record.subtype, record.header.system_id_text)
```

`read_file()` and `read_structured_file()` default to `record_format="auto"` for seekable inputs. Pass `record_format="smf"` or `record_format="rdw"` when the format is already known.

```python
for record in read_structured_file("smf-with-rdw.unload", record_format="rdw", errors="skip"):
    print(record.offset, record.record_type)
```
