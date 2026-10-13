"""Bounds-checked reader/writer for DQXI's flat native TextBlock rows."""
import struct


def _u32(blob, offset):
    if offset < 0 or offset+4 > len(blob):
        raise ValueError('textblock_pointer_out_of_bounds')
    return struct.unpack_from('<I', blob, offset)[0]


def _read_string(blob, pointer):
    delta = _u32(blob, pointer)
    if not delta:
        return None
    target = pointer+delta
    if target < 4 or target & 1 or target > len(blob) or blob[target-4:target] != b'&&&&':
        raise ValueError('textblock_string_marker_or_alignment')
    end = target
    while end+2 <= len(blob):
        if blob[end:end+2] == b'\0\0':
            try:
                return blob[target:end].decode('utf-16le')
            except UnicodeDecodeError as error:
                raise ValueError('textblock_invalid_utf16') from error
        end += 2
    raise ValueError('textblock_unterminated_string')


def read(blob):
    if len(blob) < 64 or blob[:4] != b'BXON' or blob[12:22] != b'TextBlock\0':
        raise ValueError('unsupported_textblock_schema')
    if blob[40:44] != b'&&&&':
        raise ValueError('textblock_header_marker')
    count = _u32(blob, 44)
    if count > (len(blob)-64)//28:
        raise ValueError('textblock_descriptor_table_bounds')
    if count and blob[56:60] != b'&&&&':
        raise ValueError('textblock_descriptor_marker')
    rows = []
    for index in range(count):
        offset = 64+index*28
        text = _read_string(blob, offset+16)
        if text is None:
            raise ValueError('textblock_missing_text')
        rows.append(dict(index=index, key=_u32(blob, offset+8),
                         speaker=_read_string(blob, offset+12), text=text,
                         alternate=_read_string(blob, offset+20),
                         text_pointer=offset+16, alternate_pointer=offset+20))
    return rows


def patch(blob, edits):
    before = read(blob)
    by_index = {row['index']: row for row in before}
    unknown = set(edits)-set(by_index)
    if unknown:
        raise ValueError('textblock_edit_index_out_of_bounds')
    output = bytearray(blob)
    allowed = set()
    for index, text in edits.items():
        row = by_index[index]
        if not isinstance(text, str) or '\0' in text:
            raise ValueError('textblock_invalid_replacement')
        if text == row['text']:
            continue
        output.extend(b'\0'*(-len(output) % 4)+b'&&&&')
        target = len(output)
        encoded = (text+'\0').encode('utf-16le')
        output.extend(encoded)
        pointer = row['text_pointer']
        delta = target-pointer
        if not 0 < delta <= 0xffffffff:
            raise ValueError('textblock_relative_pointer_overflow')
        struct.pack_into('<I', output, pointer, delta)
        allowed.update(range(pointer, pointer+4))

    if any(old != new for i, (old, new) in enumerate(zip(blob, output)) if i not in allowed):
        raise AssertionError('textblock_non_pointer_mutation')
    after = read(output)
    if len(before) != len(after):
        raise AssertionError('textblock_row_count_changed')
    for old, new in zip(before, after):
        expected = edits.get(old['index'], old['text'])
        if (old['key'], old['speaker'], old['alternate'], expected) != \
                (new['key'], new['speaker'], new['alternate'], new['text']):
            raise AssertionError('textblock_metadata_or_text_mismatch')
    return bytes(output)
