import json
from pathlib import Path
import struct
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import verified_overlay as overlay
import dq11_pack


class VerifiedOverlayTests(unittest.TestCase):
    def test_duplicate_archive_names_preserve_distinct_members(self):
        entries=[dq11_pack.Entry('same.arc',0,0,0,len(data),i,data)
                 for i,data in enumerate([b'first',b'second'])]
        arc=dq11_pack.Archive('PACK','<',24,24,0,0xfeff,24,0,0,entries)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'output.pack'
            overlay.write_archive(arc,{0:b'changed'},path)
            actual=dq11_pack.read_archive(path)
            self.assertEqual([e.data for e in actual.entries],[b'changed',b'second'])

    def test_original_text_guard_and_metadata_preservation(self):
        blob = bytearray(48)
        blob[:4] = b'BXON'
        blob[32:36] = b'&&&&'
        blob[36:40] = '日本'.encode('utf-16le')
        struct.pack_into('<I', blob, 24, 12)
        row = dict(pointer=24, native='日本', text='English')
        changed = overlay.patch_strings(bytes(blob), [row])
        self.assertEqual(overlay.string_at(changed, 24), 'English')
        self.assertEqual(changed[:24], blob[:24])
        self.assertEqual(changed[28:len(blob)], blob[28:])
        with self.assertRaisesRegex(ValueError, 'native_source_text_mismatch'):
            overlay.patch_strings(bytes(blob), [row | {'native': 'wrong'}])

    def test_duplicate_pointer_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_text_pointer'):
            blob=bytearray(48);blob[:4]=b'BXON';blob[32:36]=b'&&&&'
            blob[36:40]='日本'.encode('utf-16le');struct.pack_into('<I',blob,24,12)
            row=dict(pointer=24,native='日本',text='English')
            overlay.patch_strings(bytes(blob), [row,row])

    def test_native_map_guards_and_complete_paths(self):
        inputs=ROOT/'src/verified-inputs'
        rows=overlay.load(inputs/'dialogue.json')
        links=overlay.load(inputs/'runtime_links.json')
        jobs=overlay.load(inputs/'jobs.json')
        template=(inputs/'voice-template.bxon').read_bytes()
        blob,count=overlay.voice_payload(rows,links,jobs,template)
        end=44+12384*12
        header=struct.unpack_from('<8I',blob,end)
        self.assertEqual(header[:6],(0x34565144,32,5064,24,7452,5048))
        self.assertEqual(header[6],len(blob)-end)
        self.assertEqual(header[7],6)
        records=[struct.unpack_from('<6I',blob,end+32+i*24) for i in range(count)]
        fire=[r for r in records if r[4]==12174]
        self.assertEqual(len(fire),1)
        self.assertEqual(fire[0][3],1100)
        paths=blob[end+32+count*24:]
        self.assertEqual(paths[-32:].split(b'\0')[0],b'str/dqxi_voice/V_05047.bcstm')

    def test_runtime_sound_asset_mismatch_rejected(self):
        inputs=ROOT/'src/verified-inputs';rows=overlay.load(inputs/'dialogue.json')
        links=overlay.load(inputs/'runtime_links.json');jobs=overlay.load(inputs/'jobs.json')
        template=(inputs/'voice-template.bxon').read_bytes()
        links[0]['sound_id']=7452
        with self.assertRaisesRegex(ValueError,'runtime_asset_sound_id_mismatch'):
            overlay.voice_payload(rows,links,jobs,template)


if __name__=='__main__':
    unittest.main()
