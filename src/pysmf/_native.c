#define PY_SSIZE_T_CLEAN

#include <Python.h>
#include <errno.h>
#ifdef __MVS__
#include <iconv.h>
#endif
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

static int is_printable_text(Py_UCS4 character) {
    return (
        (character >= 'A' && character <= 'Z') ||
        (character >= 'a' && character <= 'z') ||
        (character >= '0' && character <= '9') ||
        character == ' ' || character == '#' || character == '$' ||
        character == '@' || character == '.' || character == '_' ||
        character == '-' || character == '/' || character == '(' ||
        character == ')' || character == ':' || character == ','
    );
}

static int is_token_character(char character) {
    return (
        (character >= 'A' && character <= 'Z') ||
        (character >= '0' && character <= '9') ||
        character == '#' || character == '$' || character == '@'
    );
}

static char normalized_ascii(Py_UCS4 character, int ignore_case) {
    if (ignore_case && character >= 'a' && character <= 'z') {
        character -= 32;
    }
    if (character > 127) {
        return '\0';
    }
    return (char)character;
}

static Py_ssize_t trimmed_ebcdic_length(const unsigned char *data, Py_ssize_t length) {
    while (length > 0) {
        unsigned char last = data[length - 1];
        if (last != 0x40 && last != 0x00) {
            break;
        }
        length--;
    }
    return length;
}

#ifdef __MVS__
static const char *iconv_source_encoding(const char *encoding) {
    if (strcmp(encoding, "cp1047") == 0 || strcmp(encoding, "CP1047") == 0) {
        return "IBM-1047";
    }
    return encoding;
}

static PyObject *decode_ebcdic_iconv(const unsigned char *data, Py_ssize_t length, const char *encoding) {
    iconv_t converter;
    char *input;
    char *input_position;
    size_t input_remaining;
    size_t output_capacity;
    size_t output_remaining;
    char *output;
    char *output_position;
    PyObject *decoded;

    converter = iconv_open("UTF-8", iconv_source_encoding(encoding));
    if (converter == (iconv_t)-1) {
        PyErr_SetFromErrno(PyExc_UnicodeError);
        return NULL;
    }

    output_capacity = (size_t)(length == 0 ? 1 : length * 4 + 4);
    output = PyMem_New(char, output_capacity);
    if (output == NULL) {
        iconv_close(converter);
        return PyErr_NoMemory();
    }

    input = (char *)data;
    input_position = input;
    input_remaining = (size_t)length;
    output_position = output;
    output_remaining = output_capacity;

    while (iconv(converter, &input_position, &input_remaining, &output_position, &output_remaining) == (size_t)-1) {
        if (errno == E2BIG) {
            size_t used = (size_t)(output_position - output);
            char *resized;
            output_capacity *= 2;
            resized = PyMem_Realloc(output, output_capacity);
            if (resized == NULL) {
                PyMem_Free(output);
                iconv_close(converter);
                return PyErr_NoMemory();
            }
            output = resized;
            output_position = output + used;
            output_remaining = output_capacity - used;
            continue;
        }
        /* Match Python's errors="replace" behavior for undecodable bytes. */
        if (output_remaining < 3) {
            size_t used = (size_t)(output_position - output);
            char *resized;
            output_capacity *= 2;
            resized = PyMem_Realloc(output, output_capacity);
            if (resized == NULL) {
                PyMem_Free(output);
                iconv_close(converter);
                return PyErr_NoMemory();
            }
            output = resized;
            output_position = output + used;
            output_remaining = output_capacity - used;
        }
        *output_position++ = (char)0xEF;
        *output_position++ = (char)0xBF;
        *output_position++ = (char)0xBD;
        output_remaining -= 3;
        input_position++;
        input_remaining--;
    }

    decoded = PyUnicode_DecodeUTF8(output, (Py_ssize_t)(output_position - output), "replace");
    PyMem_Free(output);
    if (iconv_close(converter) != 0 && decoded == NULL) {
        return PyErr_SetFromErrno(PyExc_UnicodeError);
    }
    return decoded;
}
#endif

static PyObject *decode_ebcdic_text(const unsigned char *data, Py_ssize_t length, const char *encoding) {
#ifdef __MVS__
    return decode_ebcdic_iconv(data, length, encoding);
#else
    return PyUnicode_Decode((const char *)data, length, encoding, "replace");
#endif
}

static PyObject *decode_trimmed_ebcdic_text(const unsigned char *data, Py_ssize_t length, const char *encoding) {
    return decode_ebcdic_text(data, trimmed_ebcdic_length(data, length), encoding);
}

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
    if (expected <= 255 && data[5] == (unsigned char)expected) {
        return 1;
    }
    if (data[5] == EXTENDED_RECORD_INDICATOR && (data[4] & EXTENDED_HEADER_FLAG)) {
        return read_unsigned_be(data + 52, 2) == (unsigned long long)expected;
    }
    return 0;
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

int append_self_defining_variable_sections(PyObject *dict, const char *key, const unsigned char *data, Py_ssize_t record_length, unsigned long long section_offset, unsigned long long section_count, unsigned long long type_size, unsigned long long length_size, unsigned long long data_offset) {
    PyObject *list;
    unsigned long long occurrence;
    unsigned long long base_offset;
    int appended = 0;
    if (section_count == 0) {
        return 0;
    }
    if (type_size == 0 || length_size == 0) {
        PyErr_SetString(PyExc_ValueError, "SMF variable section metadata has a zero field size");
        return -1;
    }
    if (type_size > 2 || length_size > 2 || data_offset > 4096) {
        PyErr_SetString(PyExc_ValueError, "SMF variable section metadata is outside supported bounds");
        return -1;
    }
    if (section_offset == 0 || section_count > 4096 || section_offset > (unsigned long long)record_length) {
        return 0;
    }
    base_offset = section_offset;
    for (occurrence = 0; occurrence < section_count; occurrence++) {
        unsigned long long data_type;
        unsigned long long section_length;
        unsigned long long payload_offset;
        unsigned long long next_offset;
        if (base_offset + data_offset > (unsigned long long)record_length) {
            PyErr_SetString(PyExc_ValueError, "SMF variable section header extends past the record");
            return -1;
        }
        data_type = read_unsigned_be(data + base_offset, (Py_ssize_t)type_size);
        section_length = read_unsigned_be(data + base_offset + type_size, (Py_ssize_t)length_size);
        payload_offset = base_offset + data_offset;
        next_offset = payload_offset + section_length;
        if (data_type == 0 && section_length == 0) {
            base_offset += data_offset;
            continue;
        }
        if (section_length == 0 || section_length > 4096 || next_offset > (unsigned long long)record_length) {
            PyErr_SetString(PyExc_ValueError, "SMF variable section length is outside the record");
            return -1;
        }
        list = section_list(dict, key);
        if (list == NULL) {
            return -1;
        }
        if (append_section(list, data_type, data + payload_offset, (Py_ssize_t)section_length, (Py_ssize_t)payload_offset) < 0) {
            return -1;
        }
        appended++;
        base_offset = next_offset;
    }
    return appended;
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

int append_self_defining_long_triplet_directory(PyObject *dict, const char *key, const unsigned char *data, Py_ssize_t record_length, unsigned long long directory, unsigned long long count) {
    unsigned long long index;
    int appended = 0;
    if (directory == 0 || count == 0) {
        return 0;
    }
    if (directory > (unsigned long long)record_length) {
        return 0;
    }
    if (count > ((unsigned long long)record_length - directory) / 8) {
        return 0;
    }
    for (index = 0; index < count; index++) {
        Py_ssize_t entry_offset = (Py_ssize_t)(directory + (index * 8));
        unsigned long long section_offset = read_unsigned_be(data + entry_offset, 4);
        unsigned long long section_length = read_unsigned_be(data + entry_offset + 4, 2);
        unsigned long long section_count = read_unsigned_be(data + entry_offset + 6, 2);
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
        appended += triplet_sections;
    }
    return appended;
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

int is_packed_smf_date(const unsigned char *data) {
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

static PyObject *clean_decoded_text_object(PyObject *text) {
    Py_ssize_t length;
    Py_ssize_t index;
    Py_ssize_t output_length = 0;
    int pending_space = 0;
    char *output;
    PyObject *result;

    if (PyUnicode_READY(text) < 0) {
        return NULL;
    }

    length = PyUnicode_GET_LENGTH(text);
    output = PyMem_New(char, length == 0 ? 1 : length);
    if (output == NULL) {
        return PyErr_NoMemory();
    }

    for (index = 0; index < length; index++) {
        Py_UCS4 character = PyUnicode_READ_CHAR(text, index);
        char output_character = is_printable_text(character) ? (char)character : ' ';
        if (output_character == ' ') {
            if (output_length > 0) {
                pending_space = 1;
            }
            continue;
        }
        if (pending_space) {
            output[output_length++] = ' ';
            pending_space = 0;
        }
        output[output_length++] = output_character;
    }

    if (output_length < 2) {
        PyMem_Free(output);
        return PyUnicode_FromStringAndSize("", 0);
    }
    result = PyUnicode_FromStringAndSize(output, output_length);
    PyMem_Free(output);
    return result;
}

static PyObject *py_clean_decoded_text(PyObject *self, PyObject *args) {
    PyObject *text;

    if (!PyArg_ParseTuple(args, "U", &text)) {
        return NULL;
    }
    return clean_decoded_text_object(text);
}

static PyObject *py_decode_ebcdic(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *keywords[] = {"data", "encoding", NULL};
    Py_buffer view;
    const char *encoding = "cp1047";
    PyObject *decoded;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*|s", keywords, &view, &encoding)) {
        return NULL;
    }
    decoded = decode_trimmed_ebcdic_text((const unsigned char *)view.buf, view.len, encoding);
    PyBuffer_Release(&view);
    return decoded;
}

static int plausible_fixed_text_object(PyObject *text) {
    Py_ssize_t length;
    Py_ssize_t index;
    Py_ssize_t token_length = 0;
    Py_ssize_t token_count = 0;
    Py_ssize_t one_character_tokens = 0;

    if (PyUnicode_READY(text) < 0) {
        return -1;
    }
    length = PyUnicode_GET_LENGTH(text);
    if (length == 0) {
        return 0;
    }
    for (index = 0; index <= length; index++) {
        char character = '\0';
        if (index < length) {
            character = normalized_ascii(PyUnicode_READ_CHAR(text, index), 1);
        }
        if (character != '\0' && is_token_character(character)) {
            token_length++;
            continue;
        }
        if (token_length > 0 && token_length <= 64) {
            token_count++;
            if (token_length == 1) {
                one_character_tokens++;
            }
        }
        token_length = 0;
    }
    return token_count > 0 && one_character_tokens * 3 <= token_count;
}

static PyObject *py_is_plausible_fixed_text(PyObject *self, PyObject *args) {
    PyObject *text;
    int plausible;

    if (!PyArg_ParseTuple(args, "U", &text)) {
        return NULL;
    }
    plausible = plausible_fixed_text_object(text);
    if (plausible < 0) {
        return NULL;
    }
    if (plausible) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyObject *py_is_plausible_identifier(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *keywords[] = {"data", "allow_blank", "encoding", NULL};
    Py_buffer view;
    int allow_blank = 0;
    const char *encoding = "cp1047";
    Py_ssize_t length;
    Py_ssize_t index;
    PyObject *decoded;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*|ps", keywords, &view, &allow_blank, &encoding)) {
        return NULL;
    }
    length = trimmed_ebcdic_length((const unsigned char *)view.buf, view.len);
    if (length == 0) {
        PyBuffer_Release(&view);
        if (allow_blank) {
            Py_RETURN_TRUE;
        }
        Py_RETURN_FALSE;
    }

    decoded = decode_ebcdic_text((const unsigned char *)view.buf, length, encoding);
    PyBuffer_Release(&view);
    if (decoded == NULL) {
        return NULL;
    }
    if (PyUnicode_READY(decoded) < 0) {
        Py_DECREF(decoded);
        return NULL;
    }

    for (index = 0; index < PyUnicode_GET_LENGTH(decoded); index++) {
        Py_UCS4 character = PyUnicode_READ_CHAR(decoded, index);
        int allowed = (
            (character >= 'A' && character <= 'Z') ||
            (character >= 'a' && character <= 'z') ||
            (character >= '0' && character <= '9') ||
            character == '#' || character == '$' || character == '@' || character == '_'
        );
        if (!allowed) {
            Py_DECREF(decoded);
            Py_RETURN_FALSE;
        }
    }

    Py_DECREF(decoded);
    Py_RETURN_TRUE;
}

static PyObject *py_clean_ebcdic_text(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *keywords[] = {"data", "encoding", NULL};
    Py_buffer view;
    const char *encoding = "cp1047";
    Py_ssize_t length;
    PyObject *decoded;
    PyObject *cleaned;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*|s", keywords, &view, &encoding)) {
        return NULL;
    }

    length = view.len;
    decoded = decode_trimmed_ebcdic_text((const unsigned char *)view.buf, length, encoding);
    PyBuffer_Release(&view);
    if (decoded == NULL) {
        return NULL;
    }
    cleaned = clean_decoded_text_object(decoded);
    Py_DECREF(decoded);
    return cleaned;
}

static PyObject *py_decoded_tokens(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *keywords[] = {"text", "min_length", "max_length", NULL};
    PyObject *text;
    PyObject *tokens;
    Py_ssize_t length;
    Py_ssize_t index;
    Py_ssize_t token_length = 0;
    int min_length = 2;
    int max_length = 64;
    char *token;
    PyObject *result;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "U|ii", keywords, &text, &min_length, &max_length)) {
        return NULL;
    }
    if (min_length < 0 || max_length < min_length) {
        PyErr_SetString(PyExc_ValueError, "token length bounds are invalid");
        return NULL;
    }
    if (PyUnicode_READY(text) < 0) {
        return NULL;
    }

    length = PyUnicode_GET_LENGTH(text);
    tokens = PyList_New(0);
    if (tokens == NULL) {
        return NULL;
    }
    token = PyMem_New(char, length == 0 ? 1 : length);
    if (token == NULL) {
        Py_DECREF(tokens);
        return PyErr_NoMemory();
    }

    for (index = 0; index <= length; index++) {
        char character = '\0';
        if (index < length) {
            character = normalized_ascii(PyUnicode_READ_CHAR(text, index), 1);
        }
        if (character != '\0' && is_token_character(character)) {
            token[token_length++] = character;
            continue;
        }
        if (token_length >= min_length && token_length <= max_length) {
            PyObject *token_object = PyUnicode_FromStringAndSize(token, token_length);
            if (token_object == NULL || PyList_Append(tokens, token_object) < 0) {
                Py_XDECREF(token_object);
                PyMem_Free(token);
                Py_DECREF(tokens);
                return NULL;
            }
            Py_DECREF(token_object);
        }
        token_length = 0;
    }

    PyMem_Free(token);
    result = PyList_AsTuple(tokens);
    Py_DECREF(tokens);
    return result;
}

static PyObject *py_text_matches(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *keywords[] = {"text", "value", "ignore_case", "token", NULL};
    PyObject *text;
    PyObject *value;
    Py_ssize_t text_length;
    Py_ssize_t value_length;
    Py_ssize_t index;
    Py_ssize_t value_index;
    int ignore_case = 1;
    int token = 0;
    char *haystack;
    char *needle;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "UU|pp", keywords, &text, &value, &ignore_case, &token)) {
        return NULL;
    }
    if (PyUnicode_READY(text) < 0 || PyUnicode_READY(value) < 0) {
        return NULL;
    }
    text_length = PyUnicode_GET_LENGTH(text);
    value_length = PyUnicode_GET_LENGTH(value);
    if (value_length == 0 || value_length > text_length) {
        Py_RETURN_FALSE;
    }

    haystack = PyMem_New(char, text_length);
    needle = PyMem_New(char, value_length);
    if (haystack == NULL || needle == NULL) {
        PyMem_Free(haystack);
        PyMem_Free(needle);
        return PyErr_NoMemory();
    }
    for (index = 0; index < text_length; index++) {
        haystack[index] = normalized_ascii(PyUnicode_READ_CHAR(text, index), ignore_case);
    }
    for (index = 0; index < value_length; index++) {
        needle[index] = normalized_ascii(PyUnicode_READ_CHAR(value, index), ignore_case);
    }

    for (index = 0; index <= text_length - value_length; index++) {
        int matched = 1;
        for (value_index = 0; value_index < value_length; value_index++) {
            if (haystack[index + value_index] != needle[value_index]) {
                matched = 0;
                break;
            }
        }
        if (!matched) {
            continue;
        }
        if (token) {
            Py_ssize_t before_index = index - 1;
            Py_ssize_t after_index = index + value_length;
            int before_ok = before_index < 0 || !is_token_character(haystack[before_index]);
            int after_ok = after_index >= text_length || !is_token_character(haystack[after_index]);
            if (!before_ok || !after_ok) {
                continue;
            }
        }
        PyMem_Free(haystack);
        PyMem_Free(needle);
        Py_RETURN_TRUE;
    }

    PyMem_Free(haystack);
    PyMem_Free(needle);
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
    {"decode_ebcdic", (PyCFunction)py_decode_ebcdic, METH_VARARGS | METH_KEYWORDS, "Decode a fixed-width EBCDIC SMF field."},
    {"clean_decoded_text", py_clean_decoded_text, METH_VARARGS, "Clean decoded SMF text."},
    {"clean_ebcdic_text", (PyCFunction)py_clean_ebcdic_text, METH_VARARGS | METH_KEYWORDS, "Decode and clean EBCDIC SMF text."},
    {"is_plausible_fixed_text", py_is_plausible_fixed_text, METH_VARARGS, "Return whether cleaned decoded text looks like fixed SMF text."},
    {"is_plausible_identifier", (PyCFunction)py_is_plausible_identifier, METH_VARARGS | METH_KEYWORDS, "Return whether an EBCDIC field is a plausible SMF identifier."},
    {"decoded_tokens", (PyCFunction)py_decoded_tokens, METH_VARARGS | METH_KEYWORDS, "Return decoded SMF text tokens."},
    {"text_matches", (PyCFunction)py_text_matches, METH_VARARGS | METH_KEYWORDS, "Return whether decoded SMF text matches a value."},
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
