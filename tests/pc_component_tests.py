"""Meaningful codec, segment, dialogue and recipe checks without game payloads."""
import argparse
import array
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import dialog_layout as dl
import pc_components as pc
import pc_source_inventory as inventory
import completion_data
import textserifu_reader as text_reader
from wav_to_bcstm_pcm16 import convert

DECODER = None


class Components(unittest.TestCase):
    def test_reported_wasted_lines(self):
        row = dl.reflow('We will pray for\nyour\nsafe\nreturn.')
        self.assertEqual(row['pages'], [['We will pray for', 'your safe return.']])
        self.assertEqual(row['fingerprint'], list(dl.fingerprint('We will pray for your safe return.')))

    def test_balanced_dialogue_uses_the_second_row(self):
        row = dl.reflow('We will pray for your safe return.')
        self.assertEqual(row['text'], 'We will pray for\nyour safe return.')
        self.assertEqual([dl.visible_width(line) for line in row['pages'][0]], [16, 17])
        self.assertEqual(len(row['pages'][0]), 2)

    def test_three_rows_and_no_word_loss(self):
        original = '\ue100'+' '.join(['Welcome to Erdrea, traveller.']*12)
        result = dl.reflow(original)
        self.assertGreater(len(result['pages']), 1)
        self.assertTrue(all(len(page) <= 3 for page in result['pages']))
        self.assertTrue(all(dl.visible_width(line) <= 30 for page in result['pages'] for line in page))
        self.assertEqual(dl.fingerprint(original), dl.fingerprint(result['text']))

    def test_placeholder_reservation_and_rejection(self):
        result = dl.reflow('Welcome, \x04\x01! May you have a safe journey home.')
        self.assertEqual(dl.TOKEN.findall(result['text']), ['\x04\x01'])
        self.assertTrue(all(dl.visible_width(line) <= 30 for page in result['pages'] for line in page))
        for value in ('test \x04\x05', 'A'*31, 'test \ue101', 'test\0'):
            with self.assertRaises(ValueError):
                dl.reflow(value)

    def test_random_voice_identity(self):
        rng = random.Random(1377)
        for _ in range(200):
            words = [''.join(rng.choices('abcdefghij', k=rng.randrange(1, 16))) for _ in range(40)]
            original = '\n'.join(words)
            result = dl.reflow(original)
            self.assertEqual(dl.fingerprint(original), dl.fingerprint(result['text']))
            self.assertTrue(all(dl.visible_width(line) <= 30 for p in result['pages'] for line in p))

    def test_unicode_whitespace_preserves_voice_identity(self):
        # These characters caused the reported AssertionError with generic \s.
        for separator in ('\u00a0', '\u0085', '\u1680', '\u2002', '\u2028', '\u2029', '\u202f', '\u205f'):
            original = separator+'Hello'+separator+'traveller.'+separator
            result = dl.reflow(original)
            self.assertEqual(dl.fingerprint(original), dl.fingerprint(result['text']))
            self.assertEqual(result['text'].count(separator), 3)
        result = dl.reflow('Hello\u3000traveller.\tWelcome\r\nhome.')
        self.assertEqual(result['text'], 'Hello traveller. Welcome home.')

    def test_marker_does_not_collide_with_control_placeholder(self):
        with self.assertRaises(ValueError):
            dl.reflow('Hello \x04\x01 \uf000')

    def test_fullwidth_text_is_not_misclassified_as_private_marker(self):
        self.assertEqual(dl.visible_width('！（１２３）'), 6)
        self.assertEqual(dl.from_pc('Level（１２）!')['pages'], [['Level（１２）!']])
        for marker in ('\ue025', '\uf8c0', '\uf8d0', '\U000f0000', '\U00100000'):
            with self.assertRaises(ValueError):
                dl.reflow('text '+marker)
        with self.assertRaises(ValueError):
            dl.reflow('text\ue100marker')
        self.assertEqual(dl.reflow('\ue100visible')['text'], '\ue100visible')

    def test_layout_identity_failure_reported_without_dropping_row(self):
        table = dict(name='DT_Example', chunk='pakchunk0-WindowsNoEditor',
                     english='L10N/en/DT_Example.uasset', japanese='DT_Example.uasset')
        parsed = dict(schema='JackDataTableText', rows=[dict(label='KeepMe', index=0, offset=48,
                          size=20, row_sha256='a'*64, fields=dict(Text='Private row'))])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'output'
            with patch.object(pc.ue4_voice_reader.Package, 'from_path', return_value=object()), \
                 patch.object(text_reader, 'describe', return_value=dict(schema='JackDataTableText')), \
                 patch.object(text_reader, 'read', return_value=parsed), \
                 patch.object(dl, 'from_pc', side_effect=dl.LayoutIdentityError('Layout identity mismatch')):
                report = pc.export_texts(Path(temp)/'source', output, [table])
            self.assertEqual(report['parsed_tables'], 2)
            self.assertEqual(report['layout_unresolved_rows'], 1)
            self.assertFalse(report['layout_complete'])
            self.assertNotIn('Private row', json.dumps(report))
            exported = pc.read_json(output/'pc-text/en/DT_Example.json')['rows'][0]
            self.assertEqual(exported['Text'], 'Private row')
            self.assertEqual((exported['index'], exported['offset'], exported['size']), (0,48,20))
            self.assertEqual(exported['row_sha256'], 'a'*64)
            self.assertEqual(exported['source'], 'pakchunk0-WindowsNoEditor/L10N/en/DT_Example.uasset')
            self.assertNotIn('dialog_layout', exported)
            self.assertEqual(pc.read_json(output/'text-progress-report.json'), report)

    def test_pc_tags_and_menu(self):
        result = dl.from_pc('We will pray<br>for your safe return.<end>')
        self.assertEqual(result['pages'], [['We will pray for', 'your safe return.']])
        marked = dl.from_pc('<nametab_show=UN10201>We will pray<br>for your safe return.<nametab_hide><end>')
        self.assertEqual(marked['text'], 'We will pray for\nyour safe return.')
        self.assertEqual(marked['fingerprint'], result['fingerprint'])
        self.assertEqual(dl.menu_label('Defeated Monster List'), 'Monster List')
        with self.assertRaises(ValueError):
            dl.from_pc('<center>This child...')

    def test_source_path_escape(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('../outside', '/absolute', 'C:/file'):
                with self.assertRaises(ValueError):
                    pc.safe(root, name)

    def test_actual_asset_reference_not_order(self):
        job = dict(asset='EnglishAlias', samples=4410, sample_rate=44100, channels=1, codec='CRI HCA', subsong=2)
        stream = dict(job, assets=['EnglishAlias'], subsong=17)
        self.assertEqual(pc.select_stream({'streams':[stream]}, job)['subsong'], 17)
        with self.assertRaises(ValueError):
            pc.select_stream({'streams':[stream,stream]}, job)
        with self.assertRaises(ValueError):
            pc.select_stream({'streams':[dict(stream, samples=4420)]}, job)

    def test_duplicate_alias_resolves_only_by_unique_measured_profile(self):
        job = dict(asset='SharedAlias', samples=78021, sample_rate=44100,
                   channels=1, codec='CRI HCA', subsong=7)
        wrong = dict(job, assets=['SharedAlias'], samples=75832, subsong=8)
        right = dict(job, assets=['SharedAlias'], subsong=7)
        self.assertEqual(pc.select_stream({'streams':[wrong, right]}, job)['subsong'], 7)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            pc.select_stream({'streams':[right, dict(right, subsong=9)]}, job)
        with self.assertRaisesRegex(ValueError, 'profile mismatch'):
            pc.select_stream({'streams':[wrong]}, job)

    def test_missing_alias_does_not_block_other_clips_in_bank(self):
        base = dict(bank_chunk='chunk', bank_path='bank.uexp', language='en',
                    samples=4410, sample_rate=44100, channels=1, codec='CRI HCA')
        jobs = [dict(base, index=i, asset=name) for i, name in enumerate(('Valid', 'Missing', 'AlsoValid'))]
        streams = [dict(base, assets=[name], subsong=i+1) for i, name in enumerate(('Valid', 'AlsoValid'))]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'chunk/bank.uexp'; path.parent.mkdir(); path.write_bytes(b'fixture')
            with patch.object(pc.sab_reader, 'embedded', return_value=(0, b'fixture')) as _, patch.object(pc.sab_reader, 'read', return_value=dict(streams=streams)):
                report = pc.inspect_voices(temp, jobs)
        self.assertEqual(report['structurally_validated_clips'], 2)
        self.assertEqual(report['problems'][0]['jobs'], [1])
        self.assertEqual(report['problems'][0]['scope'], 'clip')
        self.assertFalse(report['complete'])

    def test_pcm_normalization_segment_and_codec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, normal, target = root/'input.wav', root/'segment.wav', root/'segment.bcstm'
            samples = array.array('h')
            for i in range(8195):
                samples.extend((i % 2000-1000, 1000-i % 2000))
            with wave.open(str(source), 'wb') as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
                w.writeframes(samples.tobytes())
            count, rate, frames = pc.normalize_wav(source, normal, 3, 4098)
            self.assertEqual((count,rate,frames), (8195,44100,4095))
            with wave.open(str(normal), 'rb') as w:
                raw = w.readframes(w.getnframes())
                self.assertEqual(raw, bytes(frames*2))
            convert(normal, target)
            self.assertEqual(pc.verify_bcstm(target, frames), frames)
            with self.assertRaises(ValueError):
                pc.normalize_wav(source, normal, 0, 4099)
            if DECODER:
                decoded = root/'readback.wav'
                subprocess.run([str(DECODER), '-i', '-o', str(decoded), str(target)], check=True,
                               capture_output=True)
                with wave.open(str(decoded), 'rb') as w:
                    self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                                     (1,2,22050,frames))
                    self.assertEqual(w.readframes(frames), raw)
            damaged = bytearray(target.read_bytes());struct.pack_into('<I', damaged, 108, frames+1)
            target.write_bytes(damaged)
            with self.assertRaises(ValueError):
                pc.verify_bcstm(target, frames)

    def test_recipe_completeness_and_segments(self):
        recipe = pc.read_json(ROOT/'src/recipes/voice_jobs.json')
        jobs = recipe['jobs']
        self.assertEqual(len(jobs), 5048)
        self.assertEqual([j['index'] for j in jobs], list(range(5048)))
        self.assertEqual([j['sound_id'] for j in jobs], list(range(7452,12500)))
        self.assertEqual(len({(j['bank_chunk'],j['bank_path']) for j in jobs}), 424)
        self.assertEqual(sum(j['language'] != 'en' for j in jobs), 0)
        for job in jobs:
            self.assertFalse(any('sha' in key for key in job))
            if 'segment_start_sample_22050' in job:
                self.assertLess(job['segment_start_sample_22050'], job['segment_end_sample_22050'])
                self.assertLessEqual(job['segment_end_sample_22050'], (job['samples']*22050+job['sample_rate']//2)//job['sample_rate'])

    def test_nonzero_pcm_readback_across_blocks(self):
        if not DECODER:
            self.skipTest('Supply --decoder for independent audio readback')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source, normal, target, decoded=(root/n for n in ('original.wav','normal.wav','voice.bcstm','decoded.wav'))
            raw=array.array('h',(i % 30000-15000 for i in range(8197))).tobytes()
            with wave.open(str(source),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(raw)
            count,rate,frames=pc.normalize_wav(source,normal)
            self.assertEqual((count,rate,frames),(8197,22050,8197))
            convert(normal,target);pc.verify_bcstm(target,frames)
            subprocess.run([str(DECODER),'-i','-o',str(decoded),str(target)],check=True,capture_output=True)
            with wave.open(str(decoded),'rb') as w:
                self.assertEqual(w.getnframes(),8197)
                self.assertEqual(w.readframes(8197),raw)

    def test_unknown_language_is_reported_not_converted(self):
        # Asset names alone cannot certify English audio.
        job = pc.read_json(ROOT/'src/recipes/voice_jobs.json')['jobs'][0]
        self.assertEqual(job['language'], 'en')
        self.assertTrue('/Voice_NE/' in job['bank_path'])
        report = pc.inspect_voices('/nonexistent-voice-source', [job])
        self.assertFalse(report['complete'])
        self.assertEqual(report['problems'][0]['jobs'], [0])

    def test_failed_schema_retains_targeted_diagnostics(self):
        table = dict(name='DT_Unsupported', chunk='pakchunk0-WindowsNoEditor',
                     english='L10N/en/DT_Unsupported.uasset', japanese='DT_Unsupported.uasset')
        profile = dict(schema='UnknownNativeRow', counts=dict(names=2, imports=1, exports=1))
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(pc.ue4_voice_reader.Package, 'from_path', return_value=object()), \
                 patch.object(text_reader, 'describe', return_value=profile), \
                 patch.object(text_reader, 'read', side_effect=ValueError('unsupported_text_row_schema:UnknownNativeRow')):
                report = pc.export_texts(Path(temp)/'source', Path(temp)/'output', [table])
            self.assertFalse(report['complete'])
            self.assertEqual(len(report['problems']), 2)
            problem = report['problems'][0]
            self.assertEqual(problem['profile']['schema'], 'UnknownNativeRow')
            self.assertEqual(problem['uexp'], 'L10N/en/DT_Unsupported.uexp')
            self.assertFalse((Path(temp)/'output/pc-text').exists())
            self.assertEqual(pc.read_json(Path(temp)/'output/text-progress-report.json'), report)

    def test_layout_diagnostics_count_reasons_without_text(self):
        table = dict(name='DT_Example', chunk='pakchunk0-WindowsNoEditor',
                     english='L10N/en/DT_Example.uasset', japanese='DT_Example.uasset')
        rows = [dict(label='Row_'+str(i), index=i, offset=48+i*48, size=20,
                     row_sha256=format(i+1, '064x'),
                     fields=dict(Text='<center>Private dialogue '+str(i))) for i in range(8)]
        parsed = dict(schema='JackDataTableText', rows=rows)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(pc.ue4_voice_reader.Package, 'from_path', return_value=object()), \
                 patch.object(text_reader, 'describe', return_value=dict(schema='JackDataTableText')), \
                 patch.object(text_reader, 'read', return_value=parsed):
                report = pc.export_texts(Path(temp)/'source', Path(temp)/'output', [table])
            reasons = report['tables'][0]['layout_problems']
            self.assertEqual(sum(r['count'] for r in reasons.values()), 8)
            self.assertEqual(len(next(iter(reasons.values()))['example_labels']), 5)
            self.assertNotIn('Private dialogue', json.dumps(report))

    def test_reuse_checks_actual_recipe_files_not_success_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'exports'; source.mkdir()
            manifest = root/'manifest.json'; report = root/'report.json'
            asset = dict(chunk='chunk', path='file.uexp')
            manifest.write_text(json.dumps(dict(assets=[asset])))
            report.write_text(json.dumps(dict(complete=True, required_assets=1, extracted_assets=1,
                                             assets=[dict(asset, bytes=3)])))
            path = source/'chunk/file.uexp'; path.parent.mkdir(); path.write_bytes(b'abc')
            self.assertEqual(inventory.validate_extraction(source, report, manifest)['verified_files'], 1)
            path.write_bytes(b'ab')
            with self.assertRaises(ValueError):
                inventory.validate_extraction(source, report, manifest)
            path.unlink()
            with self.assertRaises(ValueError):
                inventory.validate_extraction(source, report, manifest)
            outside = root/'outside'; outside.write_bytes(b'abc'); path.symlink_to(outside)
            with self.assertRaises(ValueError):
                inventory.validate_extraction(source, report, manifest)
            path.unlink(); path.write_bytes(b'abc')
            manifest.write_text(json.dumps(dict(assets=[asset, dict(chunk='chunk', path='new.uexp')])))
            with self.assertRaises(ValueError):
                inventory.validate_extraction(source, report, manifest)

    def test_movie_inventory_requires_only_pc_usm_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pc_root = root/'pc'; romfs = root/'romfs'
            plan = root/'plan.json'
            plan.write_text(json.dumps(dict(movies=[{'source':'Game/Content/Movies/film.usm'}])))
            path = pc_root/'Game/Content/Movies/film.usm'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'PRIVATE MOVIE CONTENT')
            result = inventory.movie_inventory(pc_root, romfs, movie_plan_path=plan)
            self.assertTrue(result['source_inventory_complete'])
            self.assertEqual(result['required_movie_sources'], 1)
            self.assertEqual(result['original_3ds_files'], [])
            self.assertFalse(result['content_read'])
            self.assertFalse(result['conversion_complete'])
            self.assertFalse(result['scene_mapping_verified'])
            self.assertNotIn('PRIVATE MOVIE CONTENT', json.dumps(result))
            path.unlink()
            result = inventory.movie_inventory(pc_root, romfs, movie_plan_path=plan)
            self.assertFalse(result['source_inventory_complete'])
            self.assertEqual(result['problems'][0]['path'], 'Game/Content/Movies/film.usm')

    def test_completion_report_excludes_source_dialogue_and_contains_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=root/('pc-components-v6-'+32*'a');folder.mkdir()
            text_file=folder/'pc-text/en/DT_X.json';text_file.parent.mkdir(parents=True)
            text_file.write_text(json.dumps({'rows':[
                {'label':'tag-row','Text':'hidden <unknown> dialogue','dialog_layout_unresolved':'unknown tag'},
                {'label':'marker-row','Text':'private \ue001 words（１２）','dialog_layout_unresolved':'native marker'}]}))
            (folder/'component-report.json').write_text(json.dumps({'texts':{'tables':[{'name':'DT_X','language':'en'}]},
                'voices':{'problems':[{'bank_chunk':'chunk','bank_path':'bank.uexp'}]}}))
            bank=root/'pc-assets/pc-extracted/chunk/bank.uexp';bank.parent.mkdir(parents=True);bank.write_bytes(b'bankbytes')
            manifest_path=Path(pc.RECIPES.parent/'pc_asset_manifest.json')
            jobs_path=Path(pc.RECIPES/'voice_jobs.json')
            def read_json(path):
                if Path(path)==manifest_path:return {'assets':[{'chunk':'chunk','path':'bank.uexp','kind':'voice'}]}
                if Path(path)==jobs_path:return {'jobs':[dict(bank_chunk='chunk',bank_path='bank.uexp',index=1)]}
                return json.loads(Path(path).read_text(encoding='utf-8-sig'))
            streams=[{'assets':['sample'],'subsong':3,'material_index':2,'samples':100,
                      'sample_rate':22050,'channels':1,'codec':'HCA'}]
            with (patch.object(pc,'read_json',side_effect=read_json), patch.object(pc.sab_reader,'embedded',return_value=(0,b'bank')),
                  patch.object(pc.sab_reader,'read',return_value={'streams':streams}), patch.object(pc,'inspect_voices',return_value={'complete':False,'problems':[]})):
                report=completion_data.collect(root)
            self.assertEqual(report['tables'][0]['tags'],{'<unknown>':1})
            self.assertEqual(report['tables'][0]['private_use_markers'],{'U+E001':1})
            self.assertEqual(report['tables'][0]['marker_example_labels'],{'U+E001':['marker-row']})
            self.assertEqual(report['tables'][0]['fullwidth_characters'],
                             {'U+FF08':1,'U+FF11':1,'U+FF12':1,'U+FF09':1})
            encoded=json.dumps(report,ensure_ascii=False)
            self.assertNotIn('hidden <unknown> dialogue',encoded)
            self.assertNotIn('private \ue001 words',encoded)
            self.assertEqual(report['voice_banks'][0]['streams'][0]['subsong'],3)

    def test_completion_report_uses_retained_metadata_after_compact_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=root/'reports';folder.mkdir()
            (folder/'component-report.json').write_text(json.dumps({
                'texts':{'tables':[{'name':'DT_X','language':'en','Text':'PRIVATE SOURCE TEXT',
                    'layout_problems':{'unknown tag':{'count':2,'example_labels':['row-1']}}}]},
                'voices':{'problems':[]},'extra':'PRIVATE SOURCE TEXT'}))
            report=completion_data.collect(root)
            self.assertTrue(report['source_exports_released'])
            self.assertFalse(report['detailed_source_inspection_available'])
            self.assertEqual(report['tables'][0]['unresolved_rows'],2)
            self.assertNotIn('PRIVATE SOURCE TEXT',json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--decoder', type=Path)
    args, rest = parser.parse_known_args()
    DECODER = args.decoder
    unittest.main(argv=[sys.argv[0]]+rest)
