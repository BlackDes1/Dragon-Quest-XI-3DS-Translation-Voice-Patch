import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'python'))
import dq11_pack


class Dq11PackInventoryTests(unittest.TestCase):
    def test_inventory_counts_and_parses_paca_and_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'romfs'
            root.mkdir()
            output = Path(temp) / 'inventory.json'

            entry = dq11_pack.Entry('notice.txt', 0, 0, 0, 4, 0, b'test')
            for name, magic in (('plain.pack', 'PACK'), ('paca.pack', 'PACA')):
                archive = dq11_pack.Archive(magic, '<', 0, 0, 0, 0xFEFF,
                                            0, 0, 0, [entry])
                (root / name).write_bytes(
                    dq11_pack.build_archive(archive, output_magic=magic)
                )

            dq11_pack.command_inventory(Namespace(root=root, output=output))

            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['archive_magic_counts'], {'PACA': 1, 'PACK': 1})
            self.assertEqual(report['archive_counts'], {
                'files_seen': 2,
                'parsed': 2,
                'parse_errors': 0,
                'paca_parsed': 1,
                'compressed_paca': 0,
            })
            self.assertEqual(len(report['archives']), 2)
            self.assertTrue(all(item['entries'][0]['name'] == 'notice.txt'
                                for item in report['archives']))

    def test_expanded_compressed_paca_remains_read_only_for_rebuild(self):
        archive = dq11_pack.Archive('PACA', '<', 100, 50, 0, 0xFEFF,
                                    0, 0, 0, [])
        with self.assertRaisesRegex(ValueError, 'rebuilding is not implemented'):
            dq11_pack.build_archive(archive)


if __name__ == '__main__':
    unittest.main()
