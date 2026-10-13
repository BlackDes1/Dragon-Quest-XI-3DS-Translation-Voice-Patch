import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'python'))
import pc_scene_events


class SceneEventTests(unittest.TestCase):
    def test_supplemental_scene_and_voice_inventory_exports_ids_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scene_base = 'Maps/Product/World/F01/Test/Test_CS_A010_010'
            voice_base = 'Sounds/Voice_NE/Field/VO_Fld_PC/SWAV_fld_UN10101_jump'
            assets = [
                {'chunk':'pakchunk0-WindowsNoEditor','path':scene_base+'.umap','kind':'scene'},
                {'chunk':'pakchunk0-WindowsNoEditor','path':scene_base+'.uexp','kind':'scene'},
                {'chunk':'pakchunk0-WindowsNoEditor','path':voice_base+'.uasset','kind':'voice_extra'},
                {'chunk':'pakchunk0-WindowsNoEditor','path':voice_base+'.uexp','kind':'voice_extra'},
            ]
            for asset in assets:
                path = root / asset['chunk'] / asset['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            manifest = {'assets':assets,'scene_map_files':2,'scene_map_pairs':1,
                        'additional_voice_files':2,'additional_voice_banks':1}
            scene = {
                'counts': {'exports':3},
                'caption_tracks':[{'object_name':'CaptionTrack_0','class_name':'JackCaptionTrack',
                    'scalar_fields':{'EnableByEn':True},'evidence_sha256':'a'*64,
                    'rows':[{'fields':{'TextID':':A010CS010_S00000','TimeVar':2.5,
                                       'Text':'must not be exported'}}]}],
                'sound_tracks':[{'object_name':'VoiceTrack_0','class_name':'JackVoiceTrack',
                    'scalar_fields':{'EnableByEn':True},'evidence_sha256':'b'*64,
                    'rows':[{'fields':{'AssetPathName':'SWAV_fld_UN10101_jump','Time':2.5,
                                       'Volume':1.0}}]}],
                'synchro_tracks':[]
            }
            parsed_bank = {'streams':[{'subsong':1,'material_index':0,'samples':22050,
                'sample_rate':22050,'channels':1,'codec':'CRI HCA','assets':['fld_UN10101_jump']} ]}
            with patch.object(pc_scene_events.ue4_voice_reader.Package,'from_path',return_value=object()), \
                 patch.object(pc_scene_events.ue4_voice_reader,'read_scene',return_value=scene), \
                 patch.object(pc_scene_events.sab_reader,'embedded',return_value=(8,b'SAB')), \
                 patch.object(pc_scene_events.sab_reader,'read',return_value=parsed_bank):
                voice_report=pc_scene_events.inspect_supplemental_voice_banks(root,root,manifest)
                scene_report=pc_scene_events.export_scene_events(root,root,manifest)
            self.assertTrue(voice_report['complete'])
            self.assertEqual(voice_report['parsed_banks'],1)
            self.assertEqual(voice_report['streams'],1)
            self.assertTrue(scene_report['complete'])
            self.assertEqual(scene_report['caption_rows'],1)
            self.assertEqual(scene_report['sound_rows'],1)
            self.assertEqual(scene_report['unique_text_ids'],1)
            exported=json.loads((root/'pc-scenes/scene-events.json').read_text())
            encoded=json.dumps(exported,ensure_ascii=False)
            self.assertIn(':A010CS010_S00000',encoded)
            self.assertIn('SWAV_fld_UN10101_jump',encoded)
            self.assertNotIn('must not be exported',encoded)
            self.assertFalse(exported['report']['native_3ds_mapping_verified'])

    def test_incomplete_pair_manifest_is_rejected(self):
        manifest={'assets':[{'chunk':'pakchunk0-WindowsNoEditor','path':'Maps/Test.umap','kind':'scene'}],
                  'scene_map_files':1,'scene_map_pairs':1}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'count mismatch'):
                pc_scene_events.export_scene_events(temp,temp,manifest)


if __name__ == '__main__':
    unittest.main()
