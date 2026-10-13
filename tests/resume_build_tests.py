"""Resume validation with synthetic exports and actual BCSTM payloads."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import pc_components
import pc_movie_builder
import resume_build


class ResumeBuildTests(unittest.TestCase):
    def fixture(self, root):
        build, pc, cia = root/'build', root/'pc', root/'original.cia'
        cia.write_bytes(b'synthetic source identity')

        def write(relative, value):
            path = build/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))

        write('original-3ds/cia-extraction-report.json', dict(title_id='0004000000199200',
            source_cia=str(cia), romfs_file_count=1, romfs_total_bytes=3))
        for relative in ('original-3ds/romfs/base.bin', 'original-3ds/exefs/code.bin',
                         'pc-assets/pc-extracted/chunk/bank.uexp'):
            path = build/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'raw')
        manifest = root/'assets.json'
        manifest.write_text(json.dumps({'assets': [dict(chunk='chunk', path='bank.uexp')]}))
        write('pc-assets/pc-extraction-report.json', dict(complete=True, required_assets=1,
            extracted_assets=1, assets=[dict(chunk='chunk', path='bank.uexp', bytes=3)]))
        jobs = [dict(index=0, path='one.bcstm', samples=100, sample_rate=44100),
                dict(index=1, path='two.bcstm', samples=100, sample_rate=44100,
                     segment_start_sample_22050=5, segment_end_sample_22050=25)]
        jobs_path = root/'jobs.json'
        jobs_path.write_text(json.dumps({'jobs': jobs}))
        voices = []
        for job, samples in zip(jobs, (50, 20)):
            wav_path = root/'source.wav'
            with wave.open(str(wav_path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
                wav.writeframes(b'\x01\x00'*samples)
            output = build/'pc-components/voice-components/sound'/job['path']
            output.parent.mkdir(parents=True, exist_ok=True)
            pc_components.convert(wav_path, output)
            voices.append(dict(index=job['index'], path='sound/'+job['path'],
                               samples=samples, sample_rate=22050))
        write('pc-components/component-report.json', dict(voice_conversion=dict(
            complete=True, required=2, converted=2, missing_indices=[], files=voices)))
        plan = pc_movie_builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
        scenes = [dict(path=row['scene_map'], tracks={}) for row in plan['movies'] if row['scene_map']]
        write('pc-components/pc-scenes/scene-events.json', dict(report=dict(complete=True), maps=scenes))
        return build, cia, pc, manifest, jobs_path

    def test_reuses_sources_and_validates_complete_and_segmented_gameplay_voices(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.fixture(Path(temporary))
            result = resume_build.validate_resume(*args)
            self.assertTrue(result['sources_reusable'])
            self.assertEqual(result['gameplay_voices_checked'], 2)
            self.assertEqual(result['romfs_files'], 1)
            self.assertFalse(result['complete_movie_package'])

    def test_rejects_changed_cia_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = list(self.fixture(Path(temporary)))
            args[1] = Path(temporary)/'different.cia'
            with self.assertRaisesRegex(ValueError, 'does not match'):
                resume_build.validate_resume(*args)

    def test_rejects_missing_new_recipe_asset_without_reextracting_anything(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.fixture(Path(temporary))
            args[3].write_text(json.dumps({'assets': [dict(chunk='chunk', path='bank.uexp'),
                                                     dict(chunk='chunk', path='new-intro-bank.uexp')]}))
            with self.assertRaisesRegex(ValueError, 'current PC recipes'):
                resume_build.validate_resume(*args)

    def test_rejects_truncated_gameplay_voice(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.fixture(Path(temporary))
            (args[0]/'pc-components/voice-components/sound/two.bcstm').write_bytes(b'CSTM')
            with self.assertRaisesRegex(ValueError, 'BCSTM'):
                resume_build.validate_resume(*args)

    def test_rejects_changed_original_romfs_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.fixture(Path(temporary))
            (args[0]/'original-3ds/romfs/base.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'ROMFS export'):
                resume_build.validate_resume(*args)

    def test_rejects_incomplete_scene_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.fixture(Path(temporary))
            (args[0]/'pc-components/pc-scenes/scene-events.json').write_text(json.dumps({'report': {'complete': False}}))
            with self.assertRaisesRegex(ValueError, 'scene event'):
                resume_build.validate_resume(*args)

    def test_complete_movie_package_is_reused_only_after_file_and_source_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.fixture(root)
            build, _, pc, _, _ = args
            plan = pc_movie_builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
            frames = {r['number']: r['frames'] for r in plan['movies']}
            frames.update({int(n): f for n, f in plan['retrospective_frame_counts'].items()})
            sources = {r['number']: r['source'] for r in plan['movies']}
            sources.update({n: sources[6] for n in (7, 8, 9)})
            movies = build/'pc-movies/movie'
            movies.mkdir(parents=True)
            records = []
            for number in range(1, 11):
                source = pc/sources[number]
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b'PC source')
                path = movies/('MOVIE_%03d.moflex' % number)
                path.write_bytes(b'verified file fixture')
                records.append(dict(name=path.name, frames=frames[number], decoded_frames_verified=frames[number],
                    width=400, height=224, fps='359/12', stream_readback_verified=True,
                    sources_user_supplied=True, bytes=path.stat().st_size, sha256=pc_movie_builder.sha256(path),
                    source=sources[number], source_bytes=source.stat().st_size, source_sha256=pc_movie_builder.sha256(source)))
            (build/'pc-movies/movie-build-report.json').write_text(json.dumps(dict(complete=True, movie_count=10, files=records)))
            self.assertTrue(resume_build.validate_resume(*args)['complete_movie_package'])
            (movies/'MOVIE_007.moflex').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'MOVIE_007'):
                resume_build.validate_resume(*args)


if __name__ == '__main__':
    unittest.main()
