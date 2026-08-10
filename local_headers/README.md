# Local z/OS Headers

This directory is for local IBM z/OS C headers used to build and test `pysmf` outside z/OS.

Copy z/OS headers into `local_headers/zos/` and IBM uppercase headers into
`local_headers/IBM/`. Point builds or tests at them with:

```sh
PYSMF_ZOS_INCLUDE=local_headers/zos
PYSMF_IBM_INCLUDE=local_headers/IBM
```

On PowerShell:

```powershell
$env:PYSMF_ZOS_INCLUDE = "local_headers/zos"
$env:PYSMF_IBM_INCLUDE = "local_headers/IBM"
```

The copied headers are ignored by git. Do not commit IBM-provided header contents.
