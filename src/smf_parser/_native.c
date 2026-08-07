#define PY_SSIZE_T_CLEAN

#include <Python.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <ifasmfh.h>
#include <ifasmfr.h>

#define MIN_RECORD_LENGTH 18
#define MAX_RECORD_LENGTH 32756
#define STANDARD_HEADER_LENGTH 24
#define EXTENDED_RECORD_INDICATOR 126
#define SUBTYPE_VALID_FLAG 0x40
#define EXTENDED_HEADER_FLAG 0x20
#define VBS_MAX_LOGICAL_RECORD_LENGTH 32760

static uint16_t read_u16_be(const unsigned char *data) {
    return (uint16_t)(((uint16_t)data[0] << 8) | (uint16_t)data[1]);
}

static int32_t read_i32_be(const unsigned char *data) {
    uint32_t value = ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) | ((uint32_t)data[2] << 8) | (uint32_t)data[3];
    return (int32_t)value;
}

static PyObject *none_or_long(int present, long value) {
    if (!present) {
        Py_RETURN_NONE;
    }
    return PyLong_FromLong(value);
}

static PyObject *none_or_bytes(int present, const unsigned char *data, Py_ssize_t length) {
    if (!present) {
        Py_RETURN_NONE;
    }
    return PyBytes_FromStringAndSize((const char *)data, length);
}

static PyObject *parse_header(PyObject *self, PyObject *args) {
    Py_buffer view;
    uint16_t raw_length;
    uint16_t length;
    uint16_t segment_descriptor;
    unsigned char flags;
    unsigned char record_type_indicator;
    int32_t time_hundredths;
    int has_subsystem = 0;
    int has_subtype = 0;
    int has_extended_header = 0;
    int has_extended_record_type = 0;
    uint16_t subtype = 0;
    uint16_t extended_header_length = 0;
    unsigned char extended_version = 0;
    unsigned char extended_flags = 0;
    uint16_t extended_record_type = 0;
    uint16_t header_length = MIN_RECORD_LENGTH;
    const unsigned char *data;
    PyObject *result;

    if (!PyArg_ParseTuple(args, "y*", &view)) {
        return NULL;
    }

    data = (const unsigned char *)view.buf;
    if (view.len < MIN_RECORD_LENGTH) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_EOFError, "SMF record is shorter than the minimum 18-byte header");
        return NULL;
    }

    raw_length = read_u16_be(data);
    length = (raw_length & 0x8000) ? (uint16_t)(raw_length & 0x7FFF) : raw_length;
    if (length < MIN_RECORD_LENGTH || length > MAX_RECORD_LENGTH) {
        PyBuffer_Release(&view);
        PyErr_Format(PyExc_ValueError, "SMF record declares invalid length %u", (unsigned int)length);
        return NULL;
    }
    if (view.len < length) {
        PyBuffer_Release(&view);
        PyErr_Format(
            PyExc_EOFError,
            "SMF record declares %u bytes but only %zd are available",
            (unsigned int)length,
            view.len
        );
        return NULL;
    }

    segment_descriptor = read_u16_be(data + 2);
    flags = data[4];
    record_type_indicator = data[5];
    time_hundredths = read_i32_be(data + 6);

    if (length >= STANDARD_HEADER_LENGTH && view.len >= STANDARD_HEADER_LENGTH) {
        has_subsystem = 1;
        if (flags & SUBTYPE_VALID_FLAG) {
            has_subtype = 1;
            subtype = read_u16_be(data + 22);
        }
        header_length = STANDARD_HEADER_LENGTH;
    }

    if (
        record_type_indicator == EXTENDED_RECORD_INDICATOR &&
        (flags & EXTENDED_HEADER_FLAG) &&
        length >= 56 &&
        view.len >= 56
    ) {
        uint16_t candidate_ext_length = read_u16_be(data + 24);
        unsigned char candidate_version = data[26];
        if ((candidate_version == 1 || candidate_version == 2) && (candidate_ext_length == 32 || candidate_ext_length == 68)) {
            uint16_t candidate_header_length = (uint16_t)(STANDARD_HEADER_LENGTH + candidate_ext_length);
            if (view.len >= candidate_header_length && length >= candidate_header_length) {
                has_extended_header = 1;
                has_extended_record_type = 1;
                extended_header_length = candidate_ext_length;
                extended_version = candidate_version;
                extended_flags = data[27];
                extended_record_type = read_u16_be(data + 52);
                header_length = candidate_header_length;
            }
        }
    }

    result = PyTuple_New(15);
    if (result == NULL) {
        PyBuffer_Release(&view);
        return NULL;
    }

    PyTuple_SET_ITEM(result, 0, PyLong_FromUnsignedLong(length));
    PyTuple_SET_ITEM(result, 1, PyLong_FromUnsignedLong(raw_length));
    PyTuple_SET_ITEM(result, 2, PyLong_FromUnsignedLong(segment_descriptor));
    PyTuple_SET_ITEM(result, 3, PyLong_FromUnsignedLong(flags));
    PyTuple_SET_ITEM(result, 4, PyLong_FromUnsignedLong(record_type_indicator));
    PyTuple_SET_ITEM(result, 5, PyLong_FromLong(time_hundredths));
    PyTuple_SET_ITEM(result, 6, PyBytes_FromStringAndSize((const char *)(data + 10), 4));
    PyTuple_SET_ITEM(result, 7, PyBytes_FromStringAndSize((const char *)(data + 14), 4));
    PyTuple_SET_ITEM(result, 8, none_or_bytes(has_subsystem, data + 18, 4));
    PyTuple_SET_ITEM(result, 9, none_or_long(has_subtype, subtype));
    PyTuple_SET_ITEM(result, 10, PyLong_FromUnsignedLong(header_length));
    PyTuple_SET_ITEM(result, 11, none_or_long(has_extended_header, extended_header_length));
    PyTuple_SET_ITEM(result, 12, none_or_long(has_extended_header, extended_version));
    PyTuple_SET_ITEM(result, 13, none_or_long(has_extended_header, extended_flags));
    PyTuple_SET_ITEM(result, 14, none_or_long(has_extended_record_type, extended_record_type));

    PyBuffer_Release(&view);
    return result;
}

static PyObject *read_vbs_dataset(PyObject *self, PyObject *args, PyObject *kwargs) {
#ifdef __MVS__
    static char *keywords[] = {"dataset_name", "records", "offset", "tail", NULL};
    static const char *open_modes[] = {"rb,type=record", "r,type=record", NULL};
    const char *dataset_name;
    int records = 0;
    int offset = 0;
    int tail = 0;
    char dataset_path[512];
    unsigned char buffer[VBS_MAX_LOGICAL_RECORD_LENGTH];
    int mode_index;
    int last_open_errno = 0;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|iip", keywords, &dataset_name, &records, &offset, &tail)) {
        return NULL;
    }
    if (records < 0 || offset < 0) {
        PyErr_SetString(PyExc_ValueError, "records and offset must be non-negative");
        return NULL;
    }

    if (strncmp(dataset_name, "//", 2) == 0 || strncmp(dataset_name, "DD:", 3) == 0 || dataset_name[0] == '/') {
        if (snprintf(dataset_path, sizeof(dataset_path), "%s", dataset_name) >= (int)sizeof(dataset_path)) {
            PyErr_SetString(PyExc_ValueError, "dataset name is too long");
            return NULL;
        }
    } else if (snprintf(dataset_path, sizeof(dataset_path), "//'%.500s'", dataset_name) >= (int)sizeof(dataset_path)) {
        PyErr_SetString(PyExc_ValueError, "dataset name is too long");
        return NULL;
    }

    for (mode_index = 0; open_modes[mode_index] != NULL; mode_index++) {
        FILE *file = fopen(dataset_path, open_modes[mode_index]);
        PyObject *result;
        int skipped = 0;

        if (file == NULL) {
            last_open_errno = errno;
            continue;
        }

        result = PyList_New(0);
        if (result == NULL) {
            fclose(file);
            return NULL;
        }

        for (;;) {
            size_t bytes_read = fread(buffer, 1, sizeof(buffer), file);
            PyObject *record;

            if (bytes_read == 0) {
                if (feof(file)) {
                    break;
                }
                Py_DECREF(result);
                fclose(file);
                return PyErr_SetFromErrnoWithFilename(PyExc_OSError, dataset_path);
            }

            if (skipped < offset) {
                skipped += 1;
                continue;
            }

            record = PyBytes_FromStringAndSize((const char *)buffer, (Py_ssize_t)bytes_read);
            if (record == NULL) {
                Py_DECREF(result);
                fclose(file);
                return NULL;
            }
            if (PyList_Append(result, record) < 0) {
                Py_DECREF(record);
                Py_DECREF(result);
                fclose(file);
                return NULL;
            }
            Py_DECREF(record);

            if (!tail && records > 0 && PyList_GET_SIZE(result) >= records) {
                break;
            }
        }

        if (fclose(file) != 0) {
            Py_DECREF(result);
            return PyErr_SetFromErrnoWithFilename(PyExc_OSError, dataset_path);
        }

        if (PyList_GET_SIZE(result) == 0 && open_modes[mode_index + 1] != NULL) {
            Py_DECREF(result);
            continue;
        }

        if (tail && records > 0 && PyList_GET_SIZE(result) > records) {
            Py_ssize_t length = PyList_GET_SIZE(result);
            PyObject *tail_records = PyList_GetSlice(result, length - records, length);
            Py_DECREF(result);
            return tail_records;
        }
        return result;
    }

    if (last_open_errno != 0) {
        errno = last_open_errno;
        return PyErr_SetFromErrnoWithFilename(PyExc_OSError, dataset_path);
    }

    return PyList_New(0);
#else
    PyErr_SetString(PyExc_NotImplementedError, "VBS dataset reading is only available in native z/OS builds");
    return NULL;
#endif
}

static PyMethodDef methods[] = {
    {"parse_header", parse_header, METH_VARARGS, "Parse an SMF record header using the compiled z/OS C header build."},
    {"read_vbs_dataset", (PyCFunction)read_vbs_dataset, METH_VARARGS | METH_KEYWORDS, "Read logical records from a z/OS VBS dataset using native record I/O."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native",
    "Native SMF parsing helpers built against z/OS C headers.",
    -1,
    methods,
};

PyMODINIT_FUNC PyInit__native(void) {
    return PyModule_Create(&module);
}
