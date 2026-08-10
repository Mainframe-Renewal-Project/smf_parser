# Local SMF Data

This directory is for local SMF unloads, VBS captures, and small diagnostic record samples used while debugging `pysmf`.

Put raw SMF data under `local_data/smf/`. Transfer files in binary mode so RDWs, SMF record headers, and non-text payload bytes are preserved.

Suggested naming examples:

```text
local_data/smf/EXAMPLE.G0001V00.smf
local_data/smf/racf-type81-sample.vbs
local_data/smf/type80-records.bin
```

The copied data is ignored by git. Do not commit SMF unloads or production record contents.
