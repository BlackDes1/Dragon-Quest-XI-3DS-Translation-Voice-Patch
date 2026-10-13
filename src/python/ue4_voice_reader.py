"""Read-only reader for the exact DQXI cooked package profile in the samples.

Legacy -7, stripped engine/custom versions, hashed name map, 28-byte imports,
104-byte exports. This is not a general Unreal parser or a game-flow emulator.
Unknown profiles and malformed bounds fail closed. No scanning for loose names.
"""
import collections
import hashlib
import math
import struct
from pathlib import Path


class Reader:
    def __init__(self, data, position=0):
        self.data, self.position = data, position

    def take(self, length):
        if length < 0 or self.position < 0 or self.position + length > len(self.data):
            raise ValueError('read_out_of_bounds')
        result = self.data[self.position:self.position+length]
        self.position += length
        return result

    def number(self, fmt):
        return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))[0]

    def string(self):
        length = self.number('i')
        if not length:
            return ''
        if abs(length) > 1048576:
            raise ValueError('oversized_string')
        raw = self.take(length if length > 0 else -length*2)
        terminator = b'\0' if length > 0 else b'\0\0'
        if not raw.endswith(terminator):
            raise ValueError('string_terminator_missing')
        return raw[:-len(terminator)].decode('utf8' if length > 0 else 'utf-16le')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def count(reader, maximum):
    result = reader.number('i')
    if not 0 <= result <= maximum:
        raise ValueError('invalid_count')
    return result


class Package:
    def __init__(self, header, exports):
        self.header, self.payload = header, exports
        r = Reader(header)
        if r.number('I') != 0x9e2a83c1 or r.number('i') != -7:
            raise ValueError('unsupported_package_profile')
        if [r.number('i') for _ in range(4)] != [0, 0, 0, 0]:
            raise ValueError('unsupported_version_or_custom_versions')
        self.header_size = r.number('i')
        if self.header_size != len(header):
            raise ValueError('header_size_mismatch')
        self.folder = r.string()
        self.flags = r.number('I')
        nc, no, gc, go, ec, eo, ic, io, depends = [r.number('i') for _ in range(9)]
        if not 0 < nc <= 200000 or not 0 < ec <= 200000 or not 0 <= ic <= 200000:
            raise ValueError('package_table_count')
        if gc != 0 or go != 0:
            raise ValueError('unsupported_gatherable_text_table')
        if not r.position <= no <= io <= eo <= depends <= len(header):
            raise ValueError('package_table_bounds')
        if io+ic*28 != eo or eo+ec*104 != depends:
            raise ValueError('unsupported_import_export_stride')
        self.names = []
        r.position = no
        for _ in range(nc):
            self.names.append(r.string())
            r.take(4)  # Two serialized name hashes, not additional string bytes.
        if r.position != io:
            raise ValueError('name_map_end_mismatch')
        self.imports = []
        for _ in range(ic):
            self.imports.append(dict(package=self.name(r), class_name=self.name(r),
                                     outer=r.number('i'), name=self.name(r)))
        self.exports = []
        spans = []
        for index in range(ec):
            start = r.position
            e = dict(index=index+1, class_index=r.number('i'), super_index=r.number('i'),
                     template_index=r.number('i'), outer=r.number('i'), name=self.name(r),
                     flags=r.number('I'), size=r.number('q'), serial_offset=r.number('q'))
            offset = e['serial_offset']-len(header)
            if offset < 0 or e['size'] < 0 or offset+e['size'] > len(exports):
                raise ValueError('export_payload_bounds')
            e['payload_offset'] = offset
            e['data'] = exports[offset:offset+e['size']]
            if e['size']:
                spans.append((offset, offset+e['size']))
            self.exports.append(e)
            r.position = start+104
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('overlapping_exports')
        # Validate every class/outer reference, including unrelated export entries.
        for e in self.exports:
            for field in ['class_index', 'super_index', 'template_index', 'outer']:
                self.object(e[field])
        for imp in self.imports:
            self.object(imp['outer'])
        self.counts = dict(names=nc, imports=ic, exports=ec)

    @classmethod
    def from_path(cls, path):
        path = Path(path)
        return cls(path.read_bytes(), path.with_suffix('.uexp').read_bytes())

    def name(self, reader):
        index, number = reader.number('i'), reader.number('i')
        if not 0 <= index < len(self.names) or number < 0 or number > 10000000:
            raise ValueError('invalid_fname')
        return self.names[index]+('_'+str(number-1) if number else '')

    def object(self, index):
        if index == 0:
            return None
        if index < 0:
            if -index > len(self.imports):
                raise ValueError('invalid_import_reference')
            return self.imports[-index-1]
        if index > len(self.exports):
            raise ValueError('invalid_export_reference')
        return self.exports[index-1]

    def class_name(self, export):
        obj = self.object(export['class_index'])
        return obj['name'] if obj else None

    def tag(self, reader):
        start = reader.position
        name = self.name(reader)
        if name == 'None':
            return None
        typ = self.name(reader)
        size, index = reader.number('i'), reader.number('i')
        if size < 0 or index < 0:
            raise ValueError('invalid_property_size_or_index')
        metadata = {}
        if typ == 'StructProperty':
            metadata.update(struct=self.name(reader), struct_guid=reader.take(16).hex())
        elif typ == 'BoolProperty':
            value = reader.number('B')
            if value not in (0, 1) or size != 0:
                raise ValueError('invalid_bool_property')
            metadata['value'] = bool(value)
        elif typ in {'ByteProperty', 'EnumProperty'}:
            metadata['enum'] = self.name(reader)
        elif typ in {'ArrayProperty', 'SetProperty'}:
            metadata['inner'] = self.name(reader)
        elif typ == 'MapProperty':
            metadata.update(key=self.name(reader), value=self.name(reader))
        elif typ not in {'NameProperty', 'AssetObjectProperty', 'SoftObjectProperty',
                         'ObjectProperty', 'FloatProperty', 'IntProperty', 'StrProperty',
                         'TextProperty', 'DoubleProperty', 'UInt32Property', 'UInt64Property',
                         'Int64Property', 'Int16Property', 'UInt16Property', 'Int8Property'}:
            raise ValueError('unsupported_property_type:'+typ)
        has_guid = reader.number('B')
        if has_guid not in (0, 1):
            raise ValueError('invalid_property_guid_flag')
        if has_guid:
            metadata['property_guid'] = reader.take(16).hex()
        offset = reader.position
        return dict(name=name, type=typ, size=size, array_index=index, metadata=metadata,
                    tag_offset=start, data_offset=offset, data=reader.take(size))

    def properties(self, data, position=0):
        reader, result, seen = Reader(data, position), [], set()
        while True:
            prop = self.tag(reader)
            if prop is None:
                return result, reader.position
            identity = prop['name'], prop['array_index']
            if identity in seen:
                raise ValueError('duplicate_property')
            seen.add(identity)
            result.append(prop)

    def value(self, prop):
        r = Reader(prop['data'])
        typ = prop['type']
        if typ in {'NameProperty', 'AssetObjectProperty'}:
            result = self.name(r)
        elif typ in {'FloatProperty', 'DoubleProperty'}:
            result = r.number('f' if typ == 'FloatProperty' else 'd')
            if not math.isfinite(result):
                raise ValueError('nonfinite_property')
        elif typ == 'IntProperty':
            result = r.number('i')
        elif typ == 'ObjectProperty':
            result = r.number('i')
            self.object(result)
        elif typ == 'BoolProperty':
            result = prop['metadata']['value']
        elif typ == 'StrProperty':
            result = r.string()
        elif typ == 'EnumProperty' or typ == 'ByteProperty' and len(r.data) == 8:
            result = self.name(r)
        elif typ == 'ByteProperty':
            result = r.number('B')
        elif typ == 'ArrayProperty' and prop['metadata']['inner'] == 'ObjectProperty':
            result = [r.number('i') for _ in range(count(r, len(r.data)//4))]
            for i in result:
                self.object(i)
        else:
            # Unknown values are retained as raw evidence, never assigned a meaning.
            return dict(unresolved_type=typ, size=prop['size'], hex=prop['data'].hex())
        if r.position != len(r.data):
            raise ValueError('property_payload_size_mismatch')
        return result

    def struct_array(self, prop, expected_struct):
        if prop['type'] != 'ArrayProperty' or prop['metadata']['inner'] != 'StructProperty':
            raise ValueError('expected_struct_array')
        r = Reader(prop['data'])
        total = count(r, 100000)
        # The inner struct tag wraps all element data, not just the first row.
        inner = self.tag(r)
        if inner is None or inner['name'] != prop['name'] or inner['type'] != 'StructProperty':
            raise ValueError('array_inner_tag_mismatch')
        if inner['metadata']['struct'] != expected_struct or r.position != len(r.data):
            raise ValueError('array_struct_or_bounds_mismatch')
        rows, position = [], 0
        for _ in range(total):
            tags, end = self.properties(inner['data'], position)
            rows.append(dict(fields={t['name']: self.value(t) for t in tags},
                             property_offsets={t['name']: t['tag_offset'] for t in tags},
                             element_offset=inner['data_offset']+position))
            position = end
        if position != len(inner['data']):
            raise ValueError('struct_array_end_mismatch')
        return rows


def export_properties(package, export):
    props, end = package.properties(export['data'])
    # These tracks are regular UObjects with the serialized no-GUID trailer.
    if export['data'][end:] != b'\0'*4:
        raise ValueError('unexpected_track_native_tail')
    return {p['name']: p for p in props}


def read_scene(package):
    result = dict(counts=package.counts, caption_tracks=[], sound_tracks=[], synchro_tracks=[])
    types = {'JackCaptionTrack': ('CaptionTrack', 'JackCaptionTrackKey', 'caption_tracks'),
             'JackSynchroCaptionTrack': ('SynchroCaptionTrack', 'JackSynchroCaptionTrackKey', 'synchro_tracks'),
             'JackVoiceTrack': ('Sounds', 'SQEXSEADSoundTrackKey', 'sound_tracks')}
    for export in package.exports:
        cls = package.class_name(export)
        if cls not in types:
            continue
        array_name, schema, destination = types[cls]
        properties = export_properties(package, export)
        array = properties.get(array_name)
        rows = package.struct_array(array, schema) if array else []
        scalar_fields = {name: package.value(properties[name]) for name in
                         ['TrackTitle', 'EnableByEn', 'EnableByJp', 'bDisableTrack', 'Asset', 'LipSyncGroupName']
                         if name in properties}
        outer = package.object(export['outer'])
        result[destination].append(dict(export_index=export['index'], object_name=export['name'],
                                        outer_index=export['outer'], outer_name=outer['name'] if outer else None,
                                        class_name=cls, payload_offset=export['payload_offset'],
                                        scalar_fields=scalar_fields, array_data_offset=array['data_offset'] if array else None,
                                        rows=rows, evidence_sha256=sha(export['data'])))
    return result


def read_table(package):
    exports = [e for e in package.exports if package.class_name(e) == 'DataTable']
    if len(exports) != 1:
        raise ValueError('expected_one_datatable')
    export = exports[0]
    tags, end = package.properties(export['data'])
    props = {t['name']: t for t in tags}
    prop = props.get('RowStruct')
    if not prop or prop['type'] != 'ObjectProperty':
        raise ValueError('missing_row_struct')
    row_struct = package.object(package.value(prop))
    if not row_struct or row_struct.get('class_name') != 'ScriptStruct':
        raise ValueError('invalid_row_struct_reference')
    schema = row_struct['name']
    if schema not in {'JackDataTableVoicePreset', 'JackDataTablePartyTalkVoice', 'JackDataTableVoiceLabel'}:
        raise ValueError('unsupported_native_row_struct')
    r = Reader(export['data'], end)
    if r.number('i') != 0:
        raise ValueError('unsupported_datatable_guid')
    total = count(r, 100000)
    rows, names = [], set()
    for _ in range(total):
        offset = r.position
        name = package.name(r)
        if name in names:
            raise ValueError('duplicate_datatable_row')
        names.add(name)
        size = count(r, 1048576)
        data = Reader(r.take(size))
        if schema == 'JackDataTableVoicePreset':
            if size != 30:
                raise ValueError('unsupported_voicepreset_row_size')
            values = dict(Priority=data.number('i'), DelayTime=data.number('f'), Flags=data.number('B'),
                          VoiceAsset=package.name(data), DelayTimeEN=data.number('f'),
                          FlagsEN=data.number('B'), VoiceAssetEN=package.name(data))
            if not math.isfinite(values['DelayTime']) or not math.isfinite(values['DelayTimeEN']):
                raise ValueError('nonfinite_voice_delay')
        elif schema == 'JackDataTablePartyTalkVoice':
            values = dict(VoiceAsset=[package.name(data) for _ in range(count(data, size//8))])
        else:
            if size != 20:
                raise ValueError('unsupported_voicelabel_row_size')
            values = {field: data.number('i') for field in
                      ['bResidentResource', 'bCondition_Nemuri', 'bCondition_Mahi', 'bCondition_Konran', 'bCondition_Miryou']}
            if any(v not in (0, 1) for v in values.values()):
                raise ValueError('invalid_native_boolean')
        if data.position != len(data.data):
            raise ValueError('native_row_end_mismatch')
        rows.append(dict(row_name=name, offset=offset, size=size, fields=values))
    if r.position != len(r.data):
        raise ValueError('native_datatable_end_mismatch')
    return dict(schema=schema, counts=package.counts, rows=rows)
