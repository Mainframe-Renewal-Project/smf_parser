# Local z/OS Headers

This directory is for local IBM z/OS C headers used to build and test `pysmf` outside z/OS.

Copy headers into `local_headers/zos/` and point builds or tests at them with:

```sh
PYSMF_ZOS_INCLUDE=local_headers/zos
```

The copied headers are ignored by git. Do not commit IBM-provided header contents.
