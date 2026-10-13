import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import pc_movie_builder as builder


class PcMovieBuilderTests(unittest.TestCase):
    def test_all_legacy_movie_assets_resolve_in_regular_and_supplemental_banks(self):
        fixture = json.loads((ROOT/'tests/fixtures/movie_voice_metadata.json').read_text())
        manifest = json.loads((ROOT/'src/pc_asset_manifest.json').read_text())
        by_name = {Path(bank['source']['path']).name: bank for bank in fixture['banks']}
        assets = [asset for asset in manifest['assets']
                  if Path(asset['path']).name in by_name and asset['path'].endswith('.uexp')]
        self.assertEqual(len(assets), 8)
        references = {event['asset'] for movie in fixture['movies'] for event in movie['events']}
        self.assertEqual(len(references), 150)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for asset in assets:
                path = root/asset['chunk']/asset['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(Path(asset['path']).name.encode())
            manifest_path = root/'manifest.json'
            manifest_path.write_text(json.dumps({'assets': assets}))
            with patch.object(builder.sab_reader, 'embedded', side_effect=lambda raw: (0, raw)), \
                 patch.object(builder.sab_reader, 'read',
                              side_effect=lambda raw: by_name[raw.decode()]):
                indexed, _ = builder.index_movie_voices(
                    references, root, ROOT/'src/recipes/voice_jobs.json', manifest_path)
                self.assertEqual(set(indexed), references)
                for movie in fixture['movies']:
                    for event in movie['events']:
                        stream = indexed[event['asset']]
                        if stream['codec'] != 'Silence':
                            self.assertLessEqual(event['time'] + stream['samples']/stream['sample_rate'],
                                                 builder.duration_for(movie['frames']) + 12/359)
                # Regular-bank scanning alone does not repair the omitted
                # intro bank: extraction must request CS_020 as well.
                without_intro_bank = [a for a in assets if 'VO_A_010_CS_020' not in a['path']]
                manifest_path.write_text(json.dumps({'assets': without_intro_bank}))
                with self.assertRaisesRegex(ValueError, 'A010CS010_E00000_UN00002_00_a0'):
                    builder.index_movie_voices(
                        references, root, ROOT/'src/recipes/voice_jobs.json', manifest_path)

    def test_voice_preflight_failure_happens_before_any_movie_encode(self):
        plan_path = ROOT/'src/pc_movie_build_manifest.json'
        plan = json.loads(plan_path.read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pc = root/'pc'
            extracted = root/'extracted'
            extracted.mkdir()
            for row in plan['movies']:
                source = pc/row['source']
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b'source')
            scenes = root/'scenes.json'
            scenes.write_text(json.dumps({'report': {'complete': True}}))
            output = root/'pc-movies'
            with patch.object(builder, 'verify_mobipeg'), \
                 patch.object(builder, 'event_rows', return_value=[]), \
                 patch.object(builder, 'resolve_movie_voices', side_effect=ValueError('missing voice')), \
                 patch.object(builder, 'convert_direct_movie') as convert:
                with self.assertRaisesRegex(ValueError, 'missing voice'):
                    builder.build(pc, extracted, scenes, output, 'decoder', 'ffmpeg', 'ffprobe',
                                  ROOT/'src/recipes/voice_jobs.json', ROOT/'src/pc_asset_manifest.json',
                                  plan_path)
            convert.assert_not_called()
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob('pc-movies.partial-*')))

    def test_voice_decoder_checks_original_pcm_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'voice.wav'
            def fake_run(command, label, **kwargs):
                with wave.open(str(target), 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(44100)
                    wav.writeframes(b'\x01\0'*100)
                return SimpleNamespace(stdout='')
            with patch.object(builder, 'run', side_effect=fake_run):
                builder.decode_bank('decoder', 'bank.sab', 1, target,
                                    profile={'samples': 100, 'sample_rate': 44100, 'channels': 1})
                with self.assertRaisesRegex(ValueError, 'profile differs'):
                    builder.decode_bank('decoder', 'bank.sab', 1, target,
                                        profile={'samples': 99, 'sample_rate': 44100, 'channels': 1})

    def test_retimed_title_keeps_full_pc_audio_before_tempo_conversion(self):
        plan = json.loads((ROOT/'src/pc_movie_build_manifest.json').read_text())
        row = next(row for row in plan['movies'] if row['number'] == 1)
        commands = []
        def fake_run(command, label, **kwargs):
            commands.append(command)
            with wave.open(str(command[-1]), 'wb') as wav:
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(48000)
                wav.writeframes(b'\0\0'*2*100)
            return SimpleNamespace(stdout='')
        def fake_encode(ffmpeg, ffprobe, inputs, filters, maps, destination, *args):
            Path(destination).write_bytes(b'moflex')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'pc'/row['source']
            source.parent.mkdir(parents=True)
            source.write_bytes(b'source')
            work, output = root/'work', root/'movie'
            work.mkdir(); output.mkdir()
            with patch.object(builder, 'run', side_effect=fake_run), \
                 patch.object(builder, 'create_mixed_audio', return_value=0), \
                 patch.object(builder, 'encode_moflex', side_effect=fake_encode):
                builder.convert_direct_movie(row, root/'pc', {}, root, 'decoder', 'ffmpeg', 'ffprobe',
                                              'jobs', 'manifest', work, output, 400, 224)
            self.assertEqual(len(commands), 2)
            for command in commands:
                self.assertEqual(float(command[command.index('-t')+1]), row['pc_seconds'])

    def test_movie_voice_jobs_uses_full_asset_and_ignores_unreferenced_collisions(self):
        source = dict(asset='A030CS032_S01500', bank_chunk='pakchunk0-WindowsNoEditor',
                      bank_path='Voice/SWAV.uexp', subsong=18, material_index=17,
                      samples=426046, sample_rate=44100, channels=1, codec='CRI HCA')
        jobs = [
            dict(source, index=1544, segment_start_sample_22050=None,
                 segment_end_sample_22050=None),
            dict(source, index=5043, segment_start_sample_22050=0,
                 segment_end_sample_22050=114436),
            dict(source, index=5044, segment_start_sample_22050=114436,
                 segment_end_sample_22050=213023),
            dict(source, asset='UNREFERENCED_DUPLICATE', index=1, bank_path='Voice/one.uexp'),
            dict(source, asset='UNREFERENCED_DUPLICATE', index=2, bank_path='Voice/two.uexp'),
        ]

        resolved = builder.movie_voice_jobs({'A030CS032_S01500'}, jobs)

        self.assertEqual(set(resolved), {'A030CS032_S01500'})
        self.assertEqual(resolved['A030CS032_S01500']['index'], 1544)
        self.assertEqual(resolved['A030CS032_S01500']['segment_start_sample_22050'], 0)
        self.assertIsNone(resolved['A030CS032_S01500']['segment_end_sample_22050'])

    def test_movie_voice_jobs_rejects_referenced_assets_from_distinct_streams(self):
        base = dict(asset='MOVIE_VOICE', bank_chunk='chunk', bank_path='Voice/SWAV.uexp',
                    subsong=4, material_index=3, samples=100, sample_rate=44100,
                    channels=1, codec='CRI HCA')
        with self.assertRaisesRegex(ValueError, 'Ambiguous PC voice job asset: MOVIE_VOICE'):
            builder.movie_voice_jobs({'MOVIE_VOICE'}, [
                dict(base, index=1), dict(base, index=2, subsong=5)
            ])

    def test_resolve_movie_voices_decodes_selected_full_stream(self):
        base = dict(asset='MOVIE_VOICE', bank_chunk='chunk', bank_path='Voice/SWAV.uexp',
                    subsong=4, material_index=3, samples=100, sample_rate=44100,
                    channels=1, codec='CRI HCA')
        jobs = [dict(base, index=1, segment_start_sample_22050=None,
                     segment_end_sample_22050=None),
                dict(base, index=2, segment_start_sample_22050=0,
                     segment_end_sample_22050=25)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'extracted'
            bank = root/'chunk'/'Voice'/'SWAV.uexp'
            bank.parent.mkdir(parents=True)
            bank.write_bytes(b'bank')
            work = Path(temp)/'work'
            work.mkdir()
            with patch.object(builder, 'read_json', return_value={'jobs': jobs}), \
                 patch.object(builder.sab_reader, 'embedded', return_value=(None, b'sab')), \
                 patch.object(builder.sab_reader, 'read', return_value={'streams': []}), \
                 patch.object(builder.pc_components, 'select_stream',
                              return_value=dict(base, assets=['MOVIE_VOICE'])), \
                 patch.object(builder, 'decode_bank'), \
                 patch.object(builder.pc_components, 'normalize_wav') as normalize, \
                 patch.object(builder, 'wave_is_silent', return_value=False):
                resolved, silent = builder.resolve_movie_voices(
                    [{'asset': 'MOVIE_VOICE'}], root, Path(temp)/'decoder.exe',
                    Path(temp)/'jobs.json', Path(temp)/'manifest.json', work)
            normalize.assert_not_called()
            self.assertEqual(resolved, {'MOVIE_VOICE': work/'movie-voice-000-00004.wav'})
            self.assertEqual(silent, set())

    def test_movie_failure_before_encode_writes_build_root_log(self):
        with tempfile.TemporaryDirectory() as temp:
            build_root = Path(temp)/'DQXI-Build'
            output = build_root/'pc-movies'
            argv = ['pc_movie_builder.py', '--pc-root', str(Path(temp)/'pc'),
                    '--extracted-root', str(Path(temp)/'romfs'),
                    '--scene-events', str(Path(temp)/'scene-events.json'),
                    '--output', str(output), '--decoder', str(Path(temp)/'decoder.exe'),
                    '--ffmpeg', str(Path(temp)/'ffmpeg.exe'),
                    '--ffprobe', str(Path(temp)/'ffprobe.exe')]
            with patch.object(sys, 'argv', argv), \
                 patch.object(builder, 'build', side_effect=ValueError('ambiguous movie voice')):
                with self.assertRaisesRegex(RuntimeError, 'Full movie build log'):
                    builder.main()
            log_path = build_root/'movie-build-failure.log'
            self.assertTrue(log_path.is_file())
            self.assertIn('ambiguous movie voice', log_path.read_text())
            self.assertIn('Traceback:', log_path.read_text())

    def test_ffmpeg_progress_is_reported_and_saved(self):
        class FakeProcess:
            stdout = iter(['frame=0\n', 'progress=continue\n', 'frame=4\n', 'progress=end\n'])
            returncode = 0

            def wait(self):
                return self.returncode

            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp)/'movie.log'
            output = StringIO()
            with patch.object(builder.subprocess, 'Popen', return_value=FakeProcess()), \
                 redirect_stdout(output):
                result = builder.run(['ffmpeg', '-progress', 'pipe:1'],
                                     'MOFLEX encoding', log_path, progress_frames=4)
            self.assertIn('frame=4', result.stdout)
            self.assertIn('MOFLEX encoding: 4/4 frames (100%)', output.getvalue())
            self.assertIn('progress=end', log_path.read_text())

    def test_moflex_encoding_uses_direct_inputs_and_full_decoder_readback(self):
        calls = []
        profile = {'streams': [
            {'codec_type': 'video', 'codec_name': 'mobiclip', 'width': 400,
             'height': 224},
            {'codec_type': 'audio', 'codec_name': 'adpcm_ima_moflex',
             'sample_rate': '48000'}
        ]}

        def fake_run(command, label, **kwargs):
            calls.append(([str(value) for value in command], label))
            if label == 'MOFLEX encoding':
                Path(command[-1]).write_bytes(b'moflex')
            output = json.dumps(profile) if label == 'MOFLEX stream readback' else ''
            if label == 'MOFLEX full decode':
                output = 'frame=4\nprogress=end\n'
            return SimpleNamespace(stdout=output)

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'movie.moflex'
            with patch.object(builder, 'run', side_effect=fake_run):
                builder.encode_moflex('ffmpeg', 'ffprobe',
                    ['-i', 'source.usm', '-i', 'mix.wav'],
                    ['-vf', 'scale=400:224:flags=lanczos,fps=359/12'],
                    ['0:v:0', '1:a:0'], destination, 4, builder.duration_for(4))
            self.assertTrue(destination.is_file())

        self.assertEqual(len(calls), 3)
        command, label = calls[0]
        self.assertEqual(label, 'MOFLEX encoding')
        self.assertIn('source.usm', command)
        self.assertTrue(command[-1].endswith('movie.moflex'))
        self.assertIn('mobiclip', command)
        self.assertNotIn('-frames:v', command)
        self.assertIn('scale=400:224:flags=lanczos,fps=359/12', command)
        self.assertEqual(command.count('-map'), 2)
        self.assertEqual(command[command.index('-f')+1], 'moflex')
        self.assertNotIn('ffv1', command)

        probe, label = calls[1]
        self.assertEqual(label, 'MOFLEX stream readback')
        self.assertIn('-show_streams', probe)
        self.assertNotIn('-count_packets', probe)

        decode, label = calls[2]
        self.assertEqual(label, 'MOFLEX full decode')
        self.assertIn('-fps_mode', decode)
        self.assertIn('passthrough', decode)
        self.assertIn('null', decode)

    def test_moflex_decoder_rejects_wrong_frame_count(self):
        profile = {'streams': [
            {'codec_type': 'video', 'codec_name': 'mobiclip', 'width': 400,
             'height': 224, 'nb_read_packets': '3'},
            {'codec_type': 'audio', 'codec_name': 'adpcm_ima_moflex',
             'sample_rate': '48000'}
        ]}

        def fake_run(command, label, **kwargs):
            if label == 'MOFLEX encoding':
                Path(command[-1]).write_bytes(b'moflex')
            log_path = kwargs.get('log_path')
            if log_path is not None:
                log_path = Path(log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(log_path.read_text() + label + '\n' if log_path.exists() else label + '\n')
            output = json.dumps(profile) if label == 'MOFLEX stream readback' else ''
            if label == 'MOFLEX full decode':
                output = 'frame=3\nprogress=end\n'
            return SimpleNamespace(stdout=output)

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'stage'/'package'/'movie'/'movie.moflex'
            destination.parent.mkdir(parents=True)
            log_path = Path(temp)/'stage'/'work'/'moflex.log'
            failure_log = Path(temp)/'MOVIE_001-encode-failure.log'
            with patch.object(builder, 'run', side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, 'frame'):
                    builder.encode_moflex('ffmpeg', 'ffprobe', ['-i', 'source.usm'],
                        [], ['0:v:0'], destination, 4, builder.duration_for(4),
                        log_path, failure_log)
            self.assertFalse(destination.exists())
            self.assertTrue(failure_log.is_file())
            self.assertIn('MOFLEX full decode', failure_log.read_text())

    def test_moflex_rejects_zero_byte_encoder_output_before_probe(self):
        calls = []

        def fake_run(command, label, **kwargs):
            calls.append(label)
            return SimpleNamespace(stdout='')

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'movie.moflex'
            with patch.object(builder, 'run', side_effect=fake_run):
                with self.assertRaisesRegex(ValueError, 'zero-byte'):
                    builder.encode_moflex('ffmpeg', 'ffprobe', ['-i', 'source.usm'],
                        [], ['0:v:0'], destination, 4, builder.duration_for(4))
            self.assertEqual(calls, ['MOFLEX encoding'])
            self.assertFalse(destination.exists())

    def test_manifest_builds_all_ten_native_movie_slots_from_seven_pc_sources(self):
        manifest = json.loads((ROOT/'src/pc_movie_build_manifest.json').read_text())
        self.assertEqual({row['number'] for row in manifest['movies']}, {1, 2, 3, 4, 5, 6, 10})
        self.assertEqual(len({row['source'] for row in manifest['movies']}), 7)
        self.assertEqual(manifest['retrospective_frame_counts'], {'7': 2005, '8': 2163, '9': 2592})
        self.assertEqual(len(manifest['retrospectives']), 3)
        self.assertEqual((manifest['width'], manifest['height'], manifest['fps']), (400, 224, '359/12'))
        tools = json.loads((ROOT/'src/pc_tool_manifest.json').read_text())['mobipeg']
        self.assertEqual(tools['version'], '2.3')
        self.assertTrue(tools['url'].startswith('https://github.com/quatric/mobipeg/releases/'))
        self.assertEqual(len(tools['archive_sha256']), 64)
        self.assertEqual({row['path'] for row in tools['files']}, {'ffmpeg.exe', 'ffprobe.exe'})

    def test_movie_events_only_use_english_open_rows_and_skip_replaced_caption_clips(self):
        scene = {'path': 'Maps/Product/Title_CS_A010_010.umap', 'tracks': {
            'sound_tracks': [
                {'scalar_fields': {'EnableByEn': True, 'TrackTitle': 'English'}, 'rows': [
                    {'fields': {'AssetPathName': '/Game/SWAV_A010.voice', 'Time': 1.25,
                                'Volume': 0.75, 'Pitch': 1.0}}
                ]},
                {'scalar_fields': {'EnableByEn': False}, 'rows': [
                    {'fields': {'AssetPathName': '/Game/SWAV_Japanese.voice', 'Time': 2.0}}
                ]}
            ],
            'caption_tracks': [
                {'scalar_fields': {'EnableByEn': True, 'EnableByJp': False}, 'rows': [
                    {'fields': {'TextID': ':CAPTION_KEEP', 'TimeVar': 3.0, 'bCloseFlag': False}},
                    {'fields': {'TextID': ':CAPTION_CLOSE', 'TimeVar': 4.0, 'bCloseFlag': True}},
                    {'fields': {'TextID': ':CAPTION_REPLACED', 'TimeVar': 5.0, 'bCloseFlag': False}}
                ]},
                {'scalar_fields': {'EnableByEn': False, 'EnableByJp': True}, 'rows': [
                    {'fields': {'TextID': ':JAPANESE_ONLY', 'TimeVar': 6.0, 'bCloseFlag': False}}
                ]}
            ]
        }}
        events = builder.event_rows({'maps': [scene]}, 'Title_CS_A010_010.umap', ['CAPTION_REPLACED'])
        self.assertEqual([(e['asset'], e['time'], e['volume']) for e in events], [
            ('voice', 1.25, 0.75), ('CAPTION_KEEP', 3.0, 1.0)
        ])

    def test_event_map_and_mobipeg_capabilities_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'exactly one parsed PC event map'):
            builder.event_rows({'maps': []}, 'missing.umap')
        with self.assertRaisesRegex(ValueError, 'not isolated'):
            builder.event_rows({'maps': [{'path': 'scene.umap', 'tracks': {
                'caption_tracks': [{'scalar_fields': {'EnableByEn': True, 'EnableByJp': True}, 'rows': []}]
            }}]}, 'scene.umap')

    def test_pcm_voice_helpers_reject_empty_wav_and_detect_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            silent = Path(temp)/'silent.wav'
            active = Path(temp)/'active.wav'
            for path, frames in ((silent, b'\0\0'*64), (active, b'\x01\0'*64)):
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
                    wav.writeframes(frames)
            self.assertTrue(builder.wave_is_silent(silent))
            self.assertFalse(builder.wave_is_silent(active))
            self.assertEqual(builder.wave_profile(active), (64, 22050))

    def test_all_retrospective_frame_maps_validate_and_fail_on_changed_total(self):
        plan = builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
        for number in (7, 8, 9):
            expected = plan['retrospective_frame_counts'][str(number)]
            segments = builder.retrospective_segments(number, plan['retrospectives'][str(number)], expected)
            self.assertEqual(sum(s['frames'] for s in segments), expected)
            with self.assertRaisesRegex(ValueError, 'expected'):
                builder.retrospective_segments(number, plan['retrospectives'][str(number)], expected+1)
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            builder.retrospective_segments(7, [['I', 0, 100, 1, 100]], 200)

    def test_invalid_retrospective_manifest_stops_before_source_preflight_or_encode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'pc').mkdir(); (root/'extracted').mkdir()
            plan = builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
            plan['retrospective_frame_counts']['9'] += 1
            plan_path = root/'plan.json'
            plan_path.write_text(json.dumps(plan))
            with patch.object(builder, 'verify_mobipeg') as verify, \
                 patch.object(builder, 'resolve_movie_voices') as voices, \
                 patch.object(builder, 'convert_direct_movie') as encode:
                with self.assertRaisesRegex(ValueError, 'MOVIE_009'):
                    builder.build(root/'pc', root/'extracted', root/'scenes.json', root/'pc-movies',
                                  'decoder', 'ffmpeg', 'ffprobe', 'jobs', 'assets', plan_path)
            verify.assert_not_called(); voices.assert_not_called(); encode.assert_not_called()

    def checkpoint_scenario(self, change):
        plan = builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pc, extracted = root/'pc', root/'extracted'
            extracted.mkdir()
            for row in plan['movies']:
                source = pc/row['source']
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(('source%d' % row['number']).encode())
            for tool in ('ffmpeg', 'ffprobe'):
                (root/tool).write_bytes(tool.encode())
            scene_path, plan_path = root/'scenes.json', root/'plan.json'
            scene_path.write_text(json.dumps({'report': {'complete': True}}))
            plan_path.write_text(json.dumps(plan))
            output = root/'pc-movies'
            calls = []
            fail = [True]

            def record(number, frames, destination, source, source_hash):
                path = destination/('MOVIE_%03d.moflex' % number)
                path.write_bytes(('encoded%d' % number).encode())
                return dict(name=path.name, frames=frames, decoded_frames_verified=frames,
                            fps='359/12', width=400, height=224, bytes=path.stat().st_size,
                            sha256=builder.sha256(path), stream_readback_verified=True,
                            sources_user_supplied=True, source=str(source.relative_to(pc)),
                            source_sha256=source_hash, source_bytes=source.stat().st_size)

            def direct(row, pc, scenes, extracted, decoder, ffmpeg, ffprobe, jobs, assets,
                       work, destination, width, height, voice_cache=None, source_hash=None):
                calls.append(row['number'])
                return record(row['number'], row['frames'], destination, pc/row['source'], source_hash)

            def retrospective(number, edits, source, ffmpeg, ffprobe, work, destination,
                              width, height, suffix_start, expected_frames, source_hash=None):
                calls.append(number)
                # Exercise the actual caller/callee contract that caused the user's failure.
                builder.retrospective_segments(number, edits[str(number)], expected_frames)
                if number == 8 and fail[0]:
                    raise ValueError('synthetic later encode failure')
                return record(number, expected_frames, destination, source, source_hash)

            def build():
                return builder.build(pc, extracted, scene_path, output, 'decoder', root/'ffmpeg',
                                     root/'ffprobe', 'jobs', 'assets', plan_path)

            with patch.object(builder, 'verify_mobipeg'), \
                 patch.object(builder, 'event_rows', return_value=[]), \
                 patch.object(builder, 'resolve_movie_voices', return_value=({}, set())), \
                 patch.object(builder, 'convert_direct_movie', side_effect=direct), \
                 patch.object(builder, 'convert_retrospective', side_effect=retrospective), \
                 redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, 'later encode failure'):
                    build()
                partial = root/'pc-movies.partial'
                self.assertFalse(output.exists())
                self.assertEqual(len(list((partial/'checkpoints').glob('*.json'))), 8)
                self.assertEqual(len(list((partial/'package/movie').glob('*.moflex'))), 8)
                if change == 'corrupt':
                    (partial/'package/movie/MOVIE_002.moflex').write_bytes(b'broken')
                elif change == 'source':
                    row = next(row for row in plan['movies'] if row['number'] == 6)
                    (pc/row['source']).write_bytes(b'changed source')
                elif change == 'edit':
                    plan['retrospectives']['7'][0][1] += 0.5
                    plan_path.write_text(json.dumps(plan))
                elif change == 'receipt':
                    receipt = partial/'checkpoints/MOVIE_003.moflex.json'
                    data = builder.read_json(receipt)
                    data['record']['decoded_frames_verified'] = 0
                    receipt.write_text(json.dumps(data))
                calls.clear(); fail[0] = False
                (root/'movie-build-failure.log').write_text('old failure')
                report = build()
                self.assertTrue(report['complete'])
                self.assertEqual(report['movie_count'], 10)
                self.assertFalse(partial.exists())
                self.assertFalse((root/'movie-build-failure.log').exists())
                self.assertEqual(len(list((output/'movie').glob('*.moflex'))), 10)
            return calls

    def test_resume_reuses_eight_verified_movies_after_a_later_failure(self):
        self.assertEqual(self.checkpoint_scenario('none'), [8, 9])

    def test_resume_rebuilds_a_corrupt_movie_instead_of_accepting_its_receipt(self):
        self.assertEqual(self.checkpoint_scenario('corrupt'), [2, 8, 9])

    def test_source_change_rebuilds_the_ending_and_its_retrospectives(self):
        self.assertEqual(self.checkpoint_scenario('source'), [6, 7, 8, 9])

    def test_retrospective_edit_change_reuses_all_direct_movie_checkpoints(self):
        self.assertEqual(self.checkpoint_scenario('edit'), [7, 8, 9])

    def test_resume_rejects_a_checkpoint_without_full_decode_evidence(self):
        self.assertEqual(self.checkpoint_scenario('receipt'), [3, 8, 9])


if __name__ == '__main__':
    unittest.main()
