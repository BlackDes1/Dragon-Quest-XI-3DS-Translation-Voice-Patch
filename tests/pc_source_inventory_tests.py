import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import pc_source_inventory


class PcSourceInventoryTests(unittest.TestCase):
    def test_reuses_complete_exports_and_caches_shared_parent_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root/'pakchunk0'/'Text'/'one.bin'
            second = root/'pakchunk0'/'Text'/'two.bin'
            first.parent.mkdir(parents=True)
            first.write_bytes(b'one')
            second.write_bytes(b'two!')
            manifest = root/'manifest.json'
            report = root/'report.json'
            manifest.write_text(json.dumps({'assets': [
                {'chunk': 'pakchunk0', 'path': 'Text/one.bin'},
                {'chunk': 'pakchunk0', 'path': 'Text/two.bin'},
            ]}), encoding='utf-8')
            report.write_text(json.dumps({
                'complete': True, 'required_assets': 2, 'extracted_assets': 2,
                'assets': [
                    {'chunk': 'pakchunk0', 'path': 'Text/one.bin', 'bytes': 3},
                    {'chunk': 'pakchunk0', 'path': 'Text/two.bin', 'bytes': 4},
                ],
            }), encoding='utf-8')
            result = pc_source_inventory.validate_extraction(root, report, manifest)
            self.assertTrue(result['reused'])
            self.assertEqual(result['verified_files'], 2)

    def test_rejects_symlinked_asset_parent_even_with_shared_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base/'source'
            outside = base/'outside'
            root.mkdir()
            outside.mkdir()
            (outside/'file.bin').write_bytes(b'outside')
            link = root/'linked'
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('directory symlink creation is unavailable')
            with self.assertRaisesRegex(ValueError, 'Linked inventory path'):
                pc_source_inventory.local_file(root.resolve(), 'linked/file.bin', {root.resolve()})

    def test_checks_asset_leaf_even_if_its_path_is_in_the_directory_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base/'source'
            root.mkdir()
            (base/'outside.bin').write_bytes(b'outside')
            linked_file = root/'linked.bin'
            try:
                linked_file.symlink_to(base/'outside.bin')
            except (OSError, NotImplementedError):
                self.skipTest('file symlink creation is unavailable')
            with self.assertRaisesRegex(ValueError, 'Linked inventory path'):
                pc_source_inventory.local_file(root.resolve(), 'linked.bin', {root.resolve(), linked_file})

    def test_rejects_unsafe_manifest_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'Unsafe inventory path'):
                pc_source_inventory.local_file(Path(temporary).resolve(), '../outside.bin', set())


if __name__ == '__main__':
    unittest.main()
