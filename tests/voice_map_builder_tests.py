import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'/'python'))
import voice_map_builder as vm


class VoiceMapBuilderTests(unittest.TestCase):
    def test_fingerprint_ignores_layout_and_pager_marker(self):
        self.assertEqual(vm.fingerprint('We will pray for your safe return.'),
                         vm.fingerprint('\ue100We will pray\nfor your safe return.'))

    def test_alias_resolution_prefers_whole_clip_over_manual_segments(self):
        jobs = {
            'A010CS010_S00000': [
                dict(asset='A010CS010_S00000', sound_id=7452, subsong=4,
                     material_index=3, samples=44100, sample_rate=44100,
                     segment_start_sample_22050=None, segment_end_sample_22050=None),
                dict(asset='A010CS010_S00000', sound_id=12499, subsong=4,
                     material_index=3, samples=44100, sample_rate=44100,
                     segment_start_sample_22050=0, segment_end_sample_22050=22050),
            ]
        }
        sound, duration = vm.resolve_sound(dict(assets=['missing_alias', 'A010CS010_S00000'],
            subsong=4, material_index=3, samples=44100, sample_rate=44100), jobs)
        self.assertEqual(sound, 7452)
        self.assertAlmostEqual(duration, 1.0)

    def test_map_binary_header_and_sorted_rows(self):
        entries = [
            dict(h1=9, h2=1, length=5, text_id=20, sound_id=7453, page_rate=5000),
            dict(h1=1, h2=8, length=4, text_id=10, sound_id=7452, page_rate=6000),
        ]
        data, ordered = vm.encode_map(entries, 2)
        self.assertEqual(struct.unpack_from('<8I', data),
                         (vm.MAGIC, vm.MAP_VERSION, 2, 24, 7452, 2, len(data), 0))
        self.assertEqual(ordered[0]['text_id'], 10)
        self.assertEqual(len(data), 32 + 2*24)

    def test_build_holds_conflicting_fingerprint_and_reports_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pc = root/'pc-text'
            pc.mkdir()
            table = 'chunk/shared_dialogue.uasset'
            rows = [dict(source=table, index=i, offset=12+i*24,
                         row_sha256=chr(97+i)*64, Text='Same spoken line.')
                    for i in range(2)]
            (pc/'shared_dialogue.json').write_text(json.dumps({'rows': rows}),
                                                    encoding='utf8')
            dialogue_recipe = root/'dialogue.json'
            dialogue_recipe.write_text(json.dumps({'schema_version': 1,
                'mapping_revision': 'collision-fixture', 'entries': [
                    dict(scene='scene_a', target_id=100, target_index=0,
                         entry='cs_text.bxon', source=table, source_index=0,
                         source_offset=12, source_row_sha256='a'*64),
                    dict(scene='scene_b', target_id=100, target_index=0,
                         entry='cs_text.bxon', source=table, source_index=1,
                         source_offset=36, source_row_sha256='b'*64),
                ]}), encoding='utf8')
            voice_recipe = root/'voice.json'
            assignments = []
            jobs_rows = []
            for i, (scene, asset, sound_id) in enumerate(
                    [('scene_a', 'A000CS000_S00000', 7452),
                     ('scene_b', 'B000CS000_S00000', 7453)]):
                assignments.append(dict(scene=scene, text_id=100, target_index=0,
                    runtime_verified=True, streams=[dict(assets=[asset], subsong=1,
                        material_index=0, samples=44100, sample_rate=44100)]))
                jobs_rows.append(dict(index=i, sound_id=sound_id, asset=asset,
                    subsong=1, material_index=0, samples=44100, sample_rate=44100,
                    segment_start_sample_22050=None, segment_end_sample_22050=None))
            voice_recipe.write_text(json.dumps({'schema_version': 1,
                'assignments': assignments,
                'summary': {'expected_current_build_assignments': 2,
                            'page_rate_runtime_validated': True}}), encoding='utf8')
            jobs = root/'jobs.json'
            jobs.write_text(json.dumps({'jobs': jobs_rows}), encoding='utf8')

            report = vm.build(pc, dialogue_recipe, voice_recipe, jobs, root/'out')

            self.assertFalse(report['complete'])
            self.assertEqual(report['fingerprint_conflict_groups'], 1)
            self.assertEqual(report['fingerprint_conflict_assignments'], 2)
            self.assertEqual(report['assignments_mapped'], 0)
            self.assertEqual(report['held']['conflicting_voice_fingerprint'], 2)
            self.assertEqual(report['fingerprint_conflicts'][0]['sound_ids'], [7452, 7453])
            self.assertEqual({r['scene'] for r in report['fingerprint_conflicts'][0]['assignments']},
                             {'scene_a', 'scene_b'})
            self.assertEqual(json.loads((root/'out'/'voice-map-report.json').read_text())
                             ['fingerprint_conflict_groups'], 1)

    def test_build_recipe_uses_only_pc_text_at_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pc = root/'pc-text'
            pc.mkdir()
            table = 'chunk/dialogue.uasset'
            row_hash = 'a'*64
            (pc/'dialogue.json').write_text(json.dumps({'rows': [dict(
                source=table, index=0, offset=12, row_sha256=row_hash,
                Text='Hello there, friend.')]}), encoding='utf8')
            dialogue_recipe = root/'dialogue.json'
            dialogue_recipe.write_text(json.dumps({'schema_version': 1,
                'mapping_revision': 'test', 'entries': [dict(
                    scene='a_010_cs_010', target_id=100, target_index=0,
                    entry='cs_text.bxon', source=table, source_index=0,
                    source_offset=12, source_row_sha256=row_hash)]}), encoding='utf8')
            voice_recipe = root/'voice.json'
            voice_recipe.write_text(json.dumps({'schema_version': 1, 'assignments': [dict(
                scene='a_010_cs_010', text_id=100, target_index=0,
                runtime_verified=True,
                streams=[dict(assets=['A010CS010_S00000'], subsong=4,
                    material_index=3, samples=44100, sample_rate=44100)] )],
                'summary': {'expected_current_build_assignments': 1,
                            'page_rate_runtime_validated': True}}), encoding='utf8')
            jobs = root/'jobs.json'
            jobs.write_text(json.dumps({'jobs': [dict(index=0, sound_id=7452,
                asset='A010CS010_S00000', subsong=4, material_index=3,
                samples=44100, sample_rate=44100, segment_start_sample_22050=None,
                segment_end_sample_22050=None)]}), encoding='utf8')
            output = root/'out'
            report = vm.build(pc, dialogue_recipe, voice_recipe, jobs, output)
            self.assertTrue(report['recipe_complete'])
            self.assertTrue(report['complete'])
            self.assertEqual(report['assignments_required'], 1)
            data = (output/'map.bin').read_bytes()
            self.assertEqual(struct.unpack_from('<8I', data)[2:6], (1, 24, 7452, 1))
            row = struct.unpack_from('<6I', data, 32)
            self.assertEqual(row[:3], vm.fingerprint('\ue100Hello there, friend.'))
            self.assertEqual(row[3:5], (100, 7452))
            self.assertNotIn('Hello there', (output/'voice-map-report.json').read_text(encoding='utf8'))

    def test_release_recipe_is_explicitly_incomplete(self):
        recipe = json.loads((ROOT/'src'/'recipes'/'voice_assignments.json').read_text(encoding='utf8'))
        self.assertEqual(len(recipe['assignments']), 5045)
        self.assertEqual(recipe['summary']['expected_current_build_assignments'], 5095)
        self.assertFalse(recipe['summary']['page_rate_runtime_validated'])


if __name__ == '__main__':
    unittest.main()
