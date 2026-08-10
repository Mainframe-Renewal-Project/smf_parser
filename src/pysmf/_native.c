#define PY_SSIZE_T_CLEAN

#include <Python.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ifasmfh.h>
#include <ifasmfr.h>

#define MIN_RECORD_LENGTH 18
#define MAX_RECORD_LENGTH 32756
#define STANDARD_HEADER_LENGTH 24
#define DATE_FIRST_HEADER_LENGTH 20
#define EXTENDED_RECORD_INDICATOR 126
#define SUBTYPE_VALID_FLAG 0x40
#define EXTENDED_HEADER_FLAG 0x20
#define VBS_MAX_LOGICAL_RECORD_LENGTH 32760

PyObject *generated_parse_record(PyObject *self, PyObject *args);

int set_long(PyObject *dict, const char *key, long long value) {
    PyObject *object = PyLong_FromLongLong(value);
    int result;
    if (object == NULL) {
        return -1;
    }
    result = PyDict_SetItemString(dict, key, object);
    Py_DECREF(object);
    return result;
}

int set_bytes(PyObject *dict, const char *key, const unsigned char *data, Py_ssize_t length) {
    PyObject *object = PyBytes_FromStringAndSize((const char *)data, length);
    int result;
    if (object == NULL) {
        return -1;
    }
    result = PyDict_SetItemString(dict, key, object);
    Py_DECREF(object);
    return result;
}

unsigned long long read_unsigned_be(const unsigned char *data, Py_ssize_t length) {
    unsigned long long value = 0;
    Py_ssize_t index;
    for (index = 0; index < length; index++) {
        value = (value << 8) | data[index];
    }
    return value;
}

long long read_signed_be(const unsigned char *data, Py_ssize_t length) {
    unsigned long long value = read_unsigned_be(data, length);
    unsigned long long sign_bit;
    if (length <= 0 || length >= (Py_ssize_t)sizeof(unsigned long long)) {
        return (long long)value;
    }
    sign_bit = 1ULL << ((length * 8) - 1);
    if (value & sign_bit) {
        value |= (~0ULL) << (length * 8);
    }
    return (long long)value;
}

int validate_record_type(const unsigned char *data, int expected) {
    return data[5] == (unsigned char)expected;
}

static int append_section(PyObject *list, unsigned long long data_type, const unsigned char *data, Py_ssize_t length, Py_ssize_t offset) {
    PyObject *section = PyDict_New();
    int result;
    if (section == NULL) {
        return -1;
    }
    if (set_long(section, "data_type", (long long)data_type) < 0) {
        Py_DECREF(section);
        return -1;
    }
    if (set_long(section, "offset", (long long)offset) < 0) {
        Py_DECREF(section);
        return -1;
    }
    if (set_bytes(section, "data", data, length) < 0) {
        Py_DECREF(section);
        return -1;
    }
    result = PyList_Append(list, section);
    Py_DECREF(section);
    return result;
}

static PyObject *section_list(PyObject *dict, const char *key) {
    PyObject *list = PyDict_GetItemString(dict, key);
    if (list != NULL) {
        if (!PyList_Check(list)) {
            return NULL;
        }
        return list;
    }
    list = PyList_New(0);
    if (list == NULL) {
        return NULL;
    }
    if (PyDict_SetItemString(dict, key, list) < 0) {
        Py_DECREF(list);
        return NULL;
    }
    Py_DECREF(list);
    return PyDict_GetItemString(dict, key);
}

int append_self_defining_triplet_sections(PyObject *dict, const char *key, const unsigned char *data, Py_ssize_t record_length, unsigned long long data_type, unsigned long long section_offset, unsigned long long section_length, unsigned long long section_count) {
    PyObject *list;
    unsigned long long occurrence;
    if (section_offset == 0 || section_length == 0 || section_count == 0) {
        return 0;
    }
    if (section_length > 4096 || section_count > 4096) {
        return 0;
    }
    if (section_offset > (unsigned long long)record_length) {
        return 0;
    }
    if (section_count > ((unsigned long long)record_length - section_offset) / section_length) {
        return 0;
    }
    list = section_list(dict, key);
    if (list == NULL) {
        return -1;
    }
    for (occurrence = 0; occurrence < section_count; occurrence++) {
        Py_ssize_t offset = (Py_ssize_t)(section_offset + (occurrence * section_length));
        if (append_section(list, data_type, data + offset, (Py_ssize_t)section_length, offset) < 0) {
            return -1;
        }
    }
    return (int)section_count;
}

int append_self_defining_section_directory(PyObject *dict, const char *key, const unsigned char *data, Py_ssize_t record_length, unsigned long long directory, unsigned long long count) {
    unsigned long long index;
    int appended = 0;
    int inferred_count = 0;
    if (directory == 0) {
        return 0;
    }
    if (directory > (unsigned long long)record_length) {
        return 0;
    }
    if (count == 0) {
        count = ((unsigned long long)record_length - directory) / 6;
        inferred_count = 1;
    }
    if (count > ((unsigned long long)record_length - directory) / 6) {
        return 0;
    }
    for (index = 0; index < count; index++) {
        Py_ssize_t entry_offset = (Py_ssize_t)(directory + (index * 6));
        unsigned long long section_offset = read_unsigned_be(data + entry_offset, 2);
        unsigned long long section_length = read_unsigned_be(data + entry_offset + 2, 2);
        unsigned long long section_count = read_unsigned_be(data + entry_offset + 4, 2);
        int triplet_sections = append_self_defining_triplet_sections(
                dict,
                key,
                data,
                record_length,
                (unsigned long long)entry_offset,
                section_offset,
                section_length,
                section_count);
        if (triplet_sections < 0) {
            return -1;
        }
        if (triplet_sections == 0 && (inferred_count || appended > 0)) {
            break;
        }
        appended += triplet_sections;
    }
    return 0;
}

static uint16_t read_u16_be(const unsigned char *data) {
    return (uint16_t)(((uint16_t)data[0] << 8) | (uint16_t)data[1]);
}

static int32_t read_i32_be(const unsigned char *data) {
    uint32_t value = ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) | ((uint32_t)data[2] << 8) | (uint32_t)data[3];
    return (int32_t)value;
}

static int decode_packed_time_hundredths(const unsigned char *data, int32_t *time_hundredths) {
    unsigned char nibbles[8];
    int index;
    int hours;
    int minutes;
    int seconds;
    int tenths;

    for (index = 0; index < 4; index++) {
        nibbles[index * 2] = (unsigned char)(data[index] >> 4);
        nibbles[index * 2 + 1] = (unsigned char)(data[index] & 0x0F);
    }
    if (nibbles[7] != 0x0C && nibbles[7] != 0x0D && nibbles[7] != 0x0F) {
        return 0;
    }
    for (index = 0; index < 7; index++) {
        if (nibbles[index] > 9) {
            return 0;
        }
    }

    hours = nibbles[0] * 10 + nibbles[1];
    minutes = nibbles[2] * 10 + nibbles[3];
    seconds = nibbles[4] * 10 + nibbles[5];
    tenths = nibbles[6];
    if (hours > 23 || minutes > 59 || seconds > 59) {
        return 0;
    }

    *time_hundredths = (int32_t)((((hours * 60) + minutes) * 60 + seconds) * 100 + tenths * 10);
    return 1;
}

static int32_t decode_smf_time_hundredths(const unsigned char *data) {
    int32_t time_hundredths;
    if (decode_packed_time_hundredths(data, &time_hundredths)) {
        return time_hundredths;
    }
    return read_i32_be(data);
}

static int is_packed_smf_date(const unsigned char *data) {
    unsigned char nibbles[8];
    int index;
    int day_of_year;

    for (index = 0; index < 4; index++) {
        nibbles[index * 2] = (unsigned char)(data[index] >> 4);
        nibbles[index * 2 + 1] = (unsigned char)(data[index] & 0x0F);
    }
    if (nibbles[7] != 0x0F) {
        return 0;
    }
    for (index = 0; index < 7; index++) {
        if (nibbles[index] > 9) {
            return 0;
        }
    }
    day_of_year = nibbles[4] * 100 + nibbles[5] * 10 + nibbles[6];
    return day_of_year >= 1 && day_of_year <= 366;
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
    int date_first_header = 0;
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
    date_first_header = !is_packed_smf_date(data + 10) && is_packed_smf_date(data + 6);
    time_hundredths = date_first_header ? 0 : decode_smf_time_hundredths(data + 6);

    if (date_first_header && length >= DATE_FIRST_HEADER_LENGTH && view.len >= DATE_FIRST_HEADER_LENGTH) {
        has_subsystem = 1;
        if (flags & SUBTYPE_VALID_FLAG) {
            has_subtype = 1;
            subtype = read_u16_be(data + 18);
        }
        header_length = DATE_FIRST_HEADER_LENGTH;
    } else if (length >= STANDARD_HEADER_LENGTH && view.len >= STANDARD_HEADER_LENGTH) {
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
    PyTuple_SET_ITEM(result, 6, PyBytes_FromStringAndSize((const char *)(data + (date_first_header ? 6 : 10)), 4));
    PyTuple_SET_ITEM(result, 7, PyBytes_FromStringAndSize((const char *)(data + (date_first_header ? 10 : 14)), 4));
    PyTuple_SET_ITEM(result, 8, none_or_bytes(has_subsystem, data + (date_first_header ? 14 : 18), 4));
    PyTuple_SET_ITEM(result, 9, none_or_long(has_subtype, subtype));
    PyTuple_SET_ITEM(result, 10, PyLong_FromUnsignedLong(header_length));
    PyTuple_SET_ITEM(result, 11, none_or_long(has_extended_header, extended_header_length));
    PyTuple_SET_ITEM(result, 12, none_or_long(has_extended_header, extended_version));
    PyTuple_SET_ITEM(result, 13, none_or_long(has_extended_header, extended_flags));
    PyTuple_SET_ITEM(result, 14, none_or_long(has_extended_record_type, extended_record_type));

    PyBuffer_Release(&view);
    return result;
}

static PyObject *py_decode_smf_time_hundredths(PyObject *self, PyObject *args) {
    Py_buffer view;
    int32_t time_hundredths;

    if (!PyArg_ParseTuple(args, "y*", &view)) {
        return NULL;
    }
    if (view.len != 4) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "SMF time field must be exactly 4 bytes");
        return NULL;
    }

    time_hundredths = decode_smf_time_hundredths((const unsigned char *)view.buf);
    PyBuffer_Release(&view);
    return PyLong_FromLong(time_hundredths);
}

static PyObject *py_is_packed_smf_date(PyObject *self, PyObject *args) {
    Py_buffer view;
    int packed;

    if (!PyArg_ParseTuple(args, "y*", &view)) {
        return NULL;
    }
    packed = view.len == 4 && is_packed_smf_date((const unsigned char *)view.buf);
    PyBuffer_Release(&view);
    if (packed) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *read_vbs_dataset(PyObject *self, PyObject *args, PyObject *kwargs) {
#ifdef __MVS__
    static char *keywords[] = {"dataset_name", "records", "offset", "tail", "record_types", NULL};
    static const char *open_modes[] = {"rb,type=record", "r,type=record", NULL};
    const char *dataset_name;
    int records = 0;
    int offset = 0;
    int tail = 0;
    PyObject *record_types = Py_None;
    char dataset_path[512];
    unsigned char buffer[VBS_MAX_LOGICAL_RECORD_LENGTH];
    int mode_index;
    int last_open_errno = 0;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|iipO", keywords, &dataset_name, &records, &offset, &tail, &record_types)) {
        return NULL;
    }
    if (records < 0 || offset < 0) {
        PyErr_SetString(PyExc_ValueError, "records and offset must be non-negative");
        return NULL;
    }
    (void)record_types;

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
            int reached_record_limit;

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

            reached_record_limit = !tail && records > 0 && PyList_GET_SIZE(result) + 1 >= records;

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

            if (reached_record_limit) {
                break;
            }
        }

        if (fclose(file) != 0) {
            Py_DECREF(result);
            return PyErr_SetFromErrnoWithFilename(PyExc_OSError, dataset_path);
        }

        if (
            PyList_GET_SIZE(result) == 0 &&
            open_modes[mode_index + 1] != NULL
        ) {
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
    {"parse_record", generated_parse_record, METH_VARARGS, "Parse fixed SMF record fields using generated IBM C header mappings."},
    {"decode_smf_time_hundredths", py_decode_smf_time_hundredths, METH_VARARGS, "Decode a 4-byte SMF time field."},
    {"is_packed_smf_date", py_is_packed_smf_date, METH_VARARGS, "Return whether a 4-byte field is a packed SMF date."},
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
