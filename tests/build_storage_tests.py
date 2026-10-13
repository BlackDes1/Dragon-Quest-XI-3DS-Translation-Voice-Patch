import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import build_storage as storage
import pc_movie_builder as movies


class BuildStorageTests(unittest.TestCase):
    def fixture(self, root):
        def write(name, data):
            p = root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            return p
        self.write = write
        self.voice = write('pc-components/voice-components/sound/voice.bcstm', b'generated voice'*1024)
        write('pc-components/component-report.json', b'{"voices":true}')
        write('pc-assets/pc-extracted/bank.uexp', b'extracted PC source'*1024)
        write('pc-assets/pc-extraction-report.json', b'{"complete":true}')
        write('pc-movies/movie/MOVIE_001.moflex', b'generated movie'*1024)
        write('pc-movies/movie-build-report.json', b'{"complete":true,"movie_count":10}')
        write('original-3ds/romfs/original.pack', b'original data'*1024)
        write('original-3ds/exefs/code.bin', b'original code')
        write('original-3ds/romfs.bin', b'IVFC image'*1024)
        self.selected = write('original-3ds/decrypted-content.0000.00000006.cxi', b'plaintext source'*1024)
        self.encrypted = write('original-3ds/content.0000.00000006', b'encrypted copy'*1024)
        extraction = dict(title_id='0004000000199200', romfs_file_count=1,
                          contents=[dict(Path=str(self.selected))])
        write('original-3ds/cia-extraction-report.json', json.dumps(extraction).encode())
        write('original-3ds/extract.log', b'extraction verified')
        target = root/'Mod/romfs/sound/voice.bcstm'
        storage.generated_media(self.voice, target)
        write('Mod/code.ips', b'current code patch')
        files = [dict(path=str(p.relative_to(root/'Mod')), bytes=p.stat().st_size,
                      sha256=storage.digest(p)) for p in (target, root/'Mod/code.ips')]
        write('Mod/files.json', json.dumps(files).encode())
        write('Mod/build-report.json', b'{"complete":true}')
        self.output = target

    def test_hardlink_remains_valid_after_staging_is_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.assertEqual(self.voice.stat().st_ino, self.output.stat().st_ino)
            before = storage.digest(self.output)
            report = storage.cleanup(root, 'overlay', 'layeredfs')
            self.assertTrue(report['complete'])
            self.assertFalse((root/'pc-components').exists())
            self.assertFalse((root/'pc-assets').exists())
            self.assertFalse((root/'pc-movies').exists())
            self.assertTrue((root/'original-3ds/romfs').exists())
            self.assertEqual(storage.digest(self.output), before)
            self.assertTrue((root/'reports/movie-build-report.json').is_file())

    def test_cross_volume_falls_back_to_a_verified_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, dest = root/'input', root/'output'
            source.write_bytes(b'complete output'*1024)
            with patch.object(storage.os, 'link', side_effect=OSError(errno.EXDEV, 'cross-device')):
                self.assertEqual(storage.generated_media(source, dest), 'copy')
            self.assertNotEqual(source.stat().st_ino, dest.stat().st_ino)
            self.assertEqual(source.read_bytes(), dest.read_bytes())

    def test_bad_fallback_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, dest = root/'input', root/'output'
            source.write_bytes(b'complete output')
            with patch.object(storage.os, 'link', side_effect=OSError('unsupported')), \
                 patch.object(storage.shutil, 'copyfile', side_effect=lambda s,d: Path(d).write_bytes(b'bad')):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    storage.generated_media(source, dest)
            self.assertFalse(dest.exists())

    def test_layeredfs_extraction_releases_images_but_retains_romfs_and_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            storage.cleanup(root, 'extraction', 'layeredfs')
            self.assertFalse(self.selected.exists())
            self.assertFalse(self.encrypted.exists())
            self.assertFalse((root/'original-3ds/romfs.bin').exists())
            self.assertTrue((root/'original-3ds/romfs/original.pack').is_file())
            self.assertTrue((root/'original-3ds/exefs/code.bin').is_file())

    def test_cia_extraction_retains_reusable_plaintext_and_region_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            storage.cleanup(root, 'extraction', 'cia')
            self.assertTrue(self.selected.is_file())
            self.assertFalse(self.encrypted.exists())
            self.assertTrue((root/'original-3ds/romfs.bin').is_file())

    def test_completed_layeredfs_keeps_only_final_mod_and_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            before = storage.digest(self.output)
            report = storage.cleanup(root, 'complete', 'layeredfs')
            self.assertTrue(report['complete'])
            self.assertFalse((root/'original-3ds').exists())
            self.assertEqual(storage.digest(self.output), before)
            self.assertTrue((root/'reports/build-report.json').is_file())
            self.assertTrue((root/'reports/cia-extraction-report.json').is_file())

    def test_verified_cia_is_the_only_retained_playable_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            cia = self.write('cia/DQXI-S-3DS.cia', b'verified CIA'*1024)
            self.write('cia/.dqxi-private/verify/content', b'verified readback'*1024)
            self.write('cia/.dqxi-private/rebuild/rebuild.log', b'readback complete')
            self.write('cia/container-report.json', json.dumps(dict(container_content_readback_verified=True,
                output_bytes=cia.stat().st_size, output_sha256=storage.digest(cia))).encode())
            before = storage.digest(cia)
            storage.cleanup(root, 'complete', 'cia')
            self.assertFalse((root/'Mod').exists())
            self.assertFalse((root/'original-3ds').exists())
            self.assertFalse((root/'cia/.dqxi-private').exists())
            self.assertEqual(storage.digest(cia), before)
            self.assertTrue((root/'reports/build-report.json').is_file())
            self.assertTrue((root/'reports/cia-logs/rebuild/rebuild.log').is_file())

    def test_corrupt_final_cia_prevents_all_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.write('cia/DQXI-S-3DS.cia', b'bad CIA')
            self.write('cia/container-report.json', json.dumps(dict(container_content_readback_verified=True,
                output_bytes=7, output_sha256='0'*64)).encode())
            with self.assertRaisesRegex(ValueError, 'CIA evidence'):
                storage.cleanup(root, 'complete', 'cia')
            self.assertTrue(self.voice.is_file())
            self.assertTrue(self.output.is_file())
            self.assertTrue(self.selected.is_file())

    def test_incomplete_mod_keeps_existing_sources_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.write('Mod/build-report.json', b'{"complete":false}')
            checkpoint = self.write('pc-movies.partial/checkpoints/movie.json', b'verified receipt')
            with self.assertRaisesRegex(ValueError, 'complete'):
                storage.cleanup(root, 'overlay', 'layeredfs')
            self.assertTrue(self.voice.is_file())
            self.assertTrue(checkpoint.is_file())

    def test_changed_mod_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.output.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                storage.cleanup(root, 'complete', 'layeredfs')
            self.assertTrue(self.voice.is_file())

    def test_linked_source_directory_is_rejected_before_any_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'build'
            self.fixture(root)
            external = Path(temp)/'outside'
            external.mkdir()
            (external/'keep').write_bytes(b'original source')
            (root/'pc-assets/linked').symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'Linked cleanup'):
                storage.cleanup(root, 'overlay', 'layeredfs')
            self.assertEqual((external/'keep').read_bytes(), b'original source')
            self.assertTrue(self.voice.exists())

    def test_completed_movie_work_releases_wavs_and_preserves_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root/'work'
            folder = work/'movie-001'
            folder.mkdir(parents=True)
            (folder/'english-mix.wav').write_bytes(b'working audio'*1024)
            (folder/'moflex-encode-decode.log').write_bytes(b'full decode passed')
            movies.release_movie_work(work, 1, root/'movie-logs')
            self.assertFalse(folder.exists())
            self.assertEqual((root/'movie-logs/MOVIE_001.log').read_bytes(), b'full decode passed')


if __name__ == '__main__':
    unittest.main()
