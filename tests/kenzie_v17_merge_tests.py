import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
sys.path.insert(0, str(ROOT/'third_party/kenzie'))
import delta
import verified_overlay as overlay


def no_private_use(text):
    return ''.join(c for c in text if not ('\ue000' <= c <= '\uf8ff'))


def visible_normalized(text):
    return ' '.join(no_private_use(text).split()).casefold()


def private_use_hash(text):
    markers = ''.join(c for c in text if '\ue000' <= c <= '\uf8ff')
    return hashlib.sha256(markers.encode('utf-16le')).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode('utf-16le')).hexdigest()


class KenzieV17MergeTests(unittest.TestCase):
    def test_layout_audit_keeps_words_and_control_markers(self):
        inputs = ROOT/'src/verified-inputs'
        audit = json.loads((inputs/'kenzie-layout-audit.json').read_text())
        rows = json.loads((inputs/'dialogue.json').read_text())
        by_key = {(row['scene'], row['text_id']): row for row in rows}
        self.assertEqual(audit['changed_rows'], 58)
        self.assertEqual(len(audit['rows']), 58)
        self.assertEqual(audit['limits'], {
            'max_visible_characters_per_line': 30, 'max_lines': 3})
        self.assertEqual(audit['upstream_release'], '0.7.0')
        seen = set()
        for record in audit['rows']:
            key = (record['scene'], record['text_id'])
            self.assertNotIn(key, seen)
            seen.add(key)
            text = by_key[key]['text']
            self.assertEqual(text_hash(text), record['new_text_sha256'])
            self.assertEqual(private_use_hash(text), record['control_token_sha256'])
            self.assertEqual(hashlib.sha256(visible_normalized(text).encode()).hexdigest(),
                             record['normalized_visible_sha256'])
            lines = [no_private_use(line) for line in text.splitlines()]
            self.assertEqual(len(lines), record['after_lines'])
            self.assertLessEqual(len(lines), 3)
            self.assertLessEqual(max(map(len, lines), default=0), 30)
            self.assertGreater(record['before_lines'], record['after_lines'])

    def test_bundled_area_title_deltas_are_pinned(self):
        inputs = ROOT/'src/verified-inputs'
        manifest = json.loads((inputs/'kenzie-area-title-assets.json').read_text())
        self.assertEqual(manifest['upstream_release'], '0.7.0')
        self.assertEqual(manifest['upstream_commit'],
                         'ea515509d0ab082320bedfbb27602ae2b655c956')
        self.assertEqual(len(manifest['files']), 28)
        paths = set()
        for item in manifest['files']:
            self.assertTrue(item['path'].startswith('romfs/ui/location/'))
            self.assertTrue(item['path'].endswith('.bch'))
            self.assertNotIn(item['path'].lower(), paths)
            paths.add(item['path'].lower())
            patch = inputs/'kenzie-area-title-deltas'/item['payload']
            self.assertTrue(patch.is_file())
            self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(),
                             item['payload_sha256'])
        source = b'original BCH data' * 64
        target = source[:31] + b'English title asset' + source[52:]
        self.assertEqual(delta.apply(source, delta.create(source, target)), target)

    def test_area_title_build_applies_only_matching_sources(self):
        commit = 'ea515509d0ab082320bedfbb27602ae2b655c956'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root/'original'
            inputs = root/'inputs'
            output = root/'output'
            patch_dir = inputs/'kenzie-area-title-deltas'
            patch_dir.mkdir(parents=True)
            records = []
            originals = {}
            targets = {}
            for index in range(28):
                name = f'location_test_{index:02d}.bch'
                rel = f'ui/location/{name}'
                source = (b'original-location-' + bytes([index])) * 32
                target = source[:40] + b'English-area-title' + source[58:]
                source_path = original/rel
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(source)
                payload = f'{index:04d}.dqdelta'
                patch = delta.create(source, target)
                (patch_dir/payload).write_bytes(patch)
                records.append({
                    'path': 'romfs/' + rel,
                    'payload': payload,
                    'source_sha256': hashlib.sha256(source).hexdigest(),
                    'target_sha256': hashlib.sha256(target).hexdigest(),
                    'payload_sha256': hashlib.sha256(patch).hexdigest(),
                    'source_size': len(source),
                    'target_size': len(target),
                })
                originals[name] = source
                targets[name] = target
            (inputs/'kenzie-area-title-assets.json').write_text(json.dumps({
                'schema_version': 1,
                'upstream_release': '0.7.0',
                'upstream_commit': commit,
                'files': records,
            }))

            applied, skipped = overlay.apply_kenzie_area_title_assets(
                original, inputs, output)
            self.assertEqual((applied, skipped), (28, []))
            for name, target in targets.items():
                self.assertEqual((output/'ui/location'/name).read_bytes(), target)

            (original/'ui/location/location_test_00.bch').write_bytes(b'wrong source')
            applied, skipped = overlay.apply_kenzie_area_title_assets(
                original, inputs, root/'second-output')
            self.assertEqual(applied, 27)
            self.assertEqual(skipped, [{
                'path': 'romfs/ui/location/location_test_00.bch',
                'reason': 'source_hash_mismatch',
            }])


if __name__ == '__main__':
    unittest.main()
