"""Read DQXI LE SAB stream metadata, without decoding or modifying audio.

Only the observed version-2 SAB/HCA/silence profile is accepted. Names follow
actual sound -> sequence -> key-on -> track -> material references. Material
order defines decoder subsongs; sound/name order never does. Multiple aliases
are retained rather than replacing an earlier sound with a later name.
Layout reference: vgmstream src/meta/sqex_sead.c (see SOURCES.md).
"""
import hashlib
import struct


class Bank:
    def __init__(self, blob):
        self.blob = blob

    def take(self, offset, size):
        if offset < 0 or size < 0 or offset+size > len(self.blob):
            raise ValueError('sab_bounds')
        return self.blob[offset:offset+size]

    def num(self, offset, fmt):
        return struct.unpack(fmt, self.take(offset, struct.calcsize(fmt)))[0]

    def u8(self, p): return self.num(p, '<B')
    def u16(self, p): return self.num(p, '<H')
    def u32(self, p): return self.num(p, '<I')

    def text(self, offset, size):
        raw = self.take(offset, size+1)
        if raw[-1] != 0:
            raise ValueError('sab_name_not_terminated')
        return raw[:-1].split(b'\0', 1)[0].decode('utf8')

    def table(self, offset):
        if self.u16(offset+2) != 0x10:
            raise ValueError('sab_section_header')
        n = self.u16(offset+4)
        self.take(offset+16, n*4)
        entries = []
        for i in range(n):
            relative = self.u32(offset+16+i*4)
            if relative == 0xffffffff:
                entries.append(None)
            else:
                entry = offset+relative
                if relative < 16+n*4:
                    raise ValueError('sab_entry_overlaps_table')
                self.take(entry, 4)
                entries.append(entry)
        return entries


def embedded(blob):
    """Accept exactly one bounds-valid embedded SAB. No loose name scanning."""
    candidates = []
    start = 0
    while True:
        start = blob.find(b'sabf', start)
        if start < 0: break
        if start+16 <= len(blob):
            size = struct.unpack_from('<I', blob, start+12)[0]
            if size >= 32 and start+size <= len(blob):
                candidates.append((start, blob[start:start+size]))
        start += 4
    if len(candidates) != 1:
        raise ValueError('expected_one_embedded_sab:'+str(len(candidates)))
    return candidates[0]


def read(blob):
    b = Bank(blob)
    if b.take(0, 4) != b'sabf' or b.u8(4) != 2 or b.u16(6) != 16 or b.u8(8) != 4:
        raise ValueError('unsupported_sab_profile')
    if b.u32(12) != len(blob):
        raise ValueError('sab_size_mismatch')
    name_size = b.u8(9) or 15
    descriptor = b.text(16, name_size)
    section_start = (16+name_size+1+15)//16*16
    sections = {}
    for i, name in enumerate([b'snd ', b'seq ', b'trk ', b'mtrl']):
        q = section_start+i*16
        if b.take(q, 4) != name or b.u16(q+6) != 16:
            raise ValueError('sab_chunk_layout')
        sections[name] = b.u32(q+8)
    if list(sections.values()) != sorted(set(sections.values())):
        raise ValueError('sab_section_order')
    sound, seq, track, material = [b.table(sections[k]) for k in sections]
    aliases = [[] for _ in material]
    unknown = []
    for sound_index, p in enumerate(sound):
        if p is None: continue
        version, size = b.u8(p), b.u16(p+2)
        if version > 8:
            name = b.text(p+size, b.u8(p+0x23))
        else:
            name = b.text(p+0x50, 15)
        info = p+b.u16(p+0x1a)
        for _ in range(b.u8(p+5)):
            info_size, seq_index = b.u16(info+2), b.u16(info+4)
            if info_size < 8 or seq_index >= len(seq):
                raise ValueError('sab_sequence_reference')
            b.take(info, info_size); info += info_size
            q = seq[seq_index]
            if q is None: continue
            command = q+b.u16(q+(0x16 if b.u8(q) <= 2 else 6))
            while command < sections[b'trk ']:
                head, kind, body = b.u8(command+1), b.u8(command+2), b.u8(command+3)
                if head+body == 0:
                    break
                if head < 4:
                    raise ValueError('sab_command_size')
                b.take(command, head+body)
                if command+head+body > sections[b'trk ']:
                    raise ValueError('sab_command_crosses_section')
                if kind == 2:
                    if body < 4: raise ValueError('sab_keyon_body')
                    ti = b.u32(command+head)
                    if ti >= len(track): raise ValueError('sab_track_reference')
                    tr = track[ti]
                    if tr is not None:
                        track_type = b.u8(tr+1)
                        if track_type == 1:
                            mi = b.u16(tr+4)
                            if mi >= len(material) or material[mi] is None:
                                raise ValueError('sab_material_reference')
                            # A cross-bank reference cannot be inferred from the
                            # local stream position. Fail closed for this profile.
                            if b.u16(tr+6) != b.u16(10):
                                raise ValueError('unsupported_cross_bank_track')
                            aliases[mi].append(dict(asset=name, sound_index=sound_index,
                                                   sequence_index=seq_index, track_index=ti))
                        elif track_type == 2:
                            unknown.append(dict(sound_index=sound_index, asset=name,
                                                reason='sound_indirection_not_resolved'))
                        elif track_type != 0:
                            raise ValueError('unsupported_track_type')
                command += head+body
                if kind <= 0 or kind > 8: break
    rows = []
    for mi, p in enumerate(material):
        if p is None: continue
        if b.u16(p+2) != 32:
            raise ValueError('unsupported_material_header')
        channels, codec, rate = b.u8(p+4), b.u8(p+5), b.u32(p+8)
        extra, size = b.u32(p+0x14), b.u32(p+0x18)
        b.take(p+32, extra+size)
        if codec == 0:
            channels, rate, samples = 1, 48000, 48000
            encoding = 'Silence'
        elif codec == 7:
            encoding = 'CRI HCA'
            h = p+32+16
            if b.take(h, 4).translate(bytes(i&0x7f for i in range(256))) != b'HCA\0':
                raise ValueError('missing_hca_header')
            header_size = b.num(h+6, '>H')
            if header_size < 24 or header_size > extra+size-16:
                raise ValueError('hca_header_size')
            if bytes(c&0x7f for c in b.take(h+8, 4)) != b'fmt\0':
                raise ValueError('unsupported_hca_fmt_position')
            hca_channels = b.u8(h+12)
            hca_rate = int.from_bytes(b.take(h+13, 3), 'big')
            frames = b.num(h+16, '>I')
            delay, padding = b.num(h+20, '>H'), b.num(h+22, '>H')
            samples = frames*1024-delay-padding
            if hca_channels != channels or not 1 <= channels <= 8 or hca_rate <= 0 or samples < 0:
                raise ValueError('hca_metadata')
            rate = hca_rate
        else:
            raise ValueError('unsupported_sab_codec:'+str(codec))
        # Keep aliases for future explicit matching; one wave can have several
        # sound labels. Dummy/silent materials are never playable voice jobs.
        refs = list({(x['sound_index'],x['sequence_index'],x['track_index'],x['asset']):x
                     for x in aliases[mi]}.values())
        rows.append(dict(subsong=len(rows)+1, material_index=mi,
                         assets=list(dict.fromkeys(x['asset'] for x in refs)),
                         name_references=refs, samples=samples, sample_rate=rate,
                         channels=channels, codec=encoding, seconds=samples/rate,
                         material_offset=p, extradata_bytes=extra, stream_bytes=size))
    return dict(descriptor=descriptor, bank_sha256=hashlib.sha256(blob).hexdigest(),
                streams=rows, unresolved_sound_references=unknown)
