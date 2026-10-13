import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import dq11_pack
import pc_dialogue_build as build_dialogue
import threeds_textblock


def make_textblock(key, text, speaker='Erik', alternate=''):
    blob = bytearray(92)
    blob[:4] = b'BXON'
    blob[12:22] = b'TextBlock\0'
    blob[40:44] = b'&&&&'
    struct.pack_into('<I', blob, 44, 1)
    blob[56:60] = b'&&&&'
    struct.pack_into('<I', blob, 72, key)
    for pointer, value in ((76, speaker), (80, text), (84, alternate)):
        if value is None:
            continue
        blob.extend(b'\0'*(-len(blob) % 4)+b'&&&&')
        target = len(blob)
        blob.extend((value+'\0').encode('utf-16le'))
        struct.pack_into('<I', blob, pointer, target-pointer)
    return bytes(blob)


def make_pack(path, textblock, extra_entries=()):
    entry = dq11_pack.Entry('cs_text.bxon', 0, 0, 0, len(textblock), 0, textblock)
    archive = dq11_pack.Archive('PACK', '<', 0, 0, 0, 0xfeff, 0, 0, 0,
                                [entry, *extra_entries])
    blob = bytearray(dq11_pack.build_archive(archive))
    struct.pack_into('<I', blob, 20, zlib.crc32(blob[24:]) & 0xffffffff)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


class PcDialogueBuild(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.romfs = self.root/'romfs'
        self.pc_text = self.root/'pc-text'/'en'
        self.pc_text.mkdir(parents=True)
        self.source = 'pakchunk0-WindowsNoEditor/JackGame/Content/L10N/en/Scenario/DT_Test.uasset'
        self.row_hash = 'a'*64
        self.recipe = self.root/'recipe.json'
        self.recipe.write_text(json.dumps({
            'schema_version': 1,
            'mapping_revision': 'fixture',
            'source_content_included': False,
            'entries': [dict(scene='test_scene', target_id=42, target_index=0,
                             entry='cs_text.bxon', source=self.source,
                             source_index=0, source_offset=48,
                             source_row_sha256=self.row_hash)],
        }), encoding='utf-8')
        self.pc_source_text = '<nametab_show=UN00001>We will pray for your safe return.<nametab_hide><end>'
        (self.pc_text/'DT_Test.json').write_text(json.dumps({
            'schema': 'JackDataTableText',
            'rows': [dict(source=self.source, index=0, offset=48, size=64,
                          row_sha256=self.row_hash, label='row', Text=self.pc_source_text)],
        }), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_shipped_recipe_contains_anchors_not_translation_payload(self):
        recipe, rows = build_dialogue.read_recipe(ROOT/'src/recipes/pc_dialogue_map.json')
        self.assertEqual(len(rows), 5210)
        self.assertFalse(recipe['source_content_included'])
        allowed = {'scene', 'target_id', 'target_index', 'entry', 'source',
                   'source_index', 'source_offset', 'source_row_sha256'}
        self.assertTrue(all(set(row) == allowed for row in rows))
        self.assertEqual(recipe['coverage_summary']['pc_no_text_match'], 328)
        self.assertEqual(recipe['coverage_summary']['pc_ambiguous_text_match'], 13)
        self.assertFalse(recipe['coverage_summary']['gameplay_verified'])

    def test_verified_pc_anchor_builds_marked_balanced_overlay(self):
        original_text = 'Japanese source'
        original = make_textblock(42, original_text, 'Erik', 'alternate stays')
        pack_path = self.romfs/'param/scenario/cs/test_scene.pack'
        make_pack(pack_path, original)

        output = self.root/'dialogue-output'
        report = build_dialogue.build(self.romfs, self.pc_text, self.recipe, output)

        self.assertTrue(report['complete'])
        self.assertFalse(report['standalone_mod_complete'])
        self.assertEqual(report['targets']['dialogue_rows_written'], 1)
        self.assertEqual(report['layout']['max_columns'], 30)
        patched_pack = dq11_pack.read_archive(output/'romfs/param/scenario/cs/test_scene.pack')
        patched = next(e.data for e in patched_pack.entries if e.name == 'cs_text.bxon')
        row = threeds_textblock.read(patched)[0]
        self.assertEqual(row['text'], '\ue100We will pray for\nyour safe return.')
        self.assertEqual(row['speaker'], 'Erik')
        self.assertEqual(row['alternate'], 'alternate stays')

    def test_ambiguous_target_pack_is_held(self):
        block = make_textblock(42, 'Japanese source')
        make_pack(self.romfs/'param/scenario/cs/test_scene.pack', block)
        make_pack(self.romfs/'script/test_scene.pack', block)
        report = build_dialogue.build(self.romfs, self.pc_text, self.recipe,
                                      self.root/'ambiguous-output')
        self.assertFalse(report['complete'])
        self.assertEqual(report['targets']['unresolved_reasons']['target_pack_ambiguous'], 1)
        self.assertEqual(report['targets']['dialogue_rows_written'], 0)

    def test_unknown_pc_tag_is_held(self):
        self.pc_source_text = '<yesno>We will pray for your safe return.'
        (self.pc_text/'DT_Test.json').write_text(json.dumps({
            'schema': 'JackDataTableText',
            'rows': [dict(source=self.source, index=0, offset=48, size=64,
                          row_sha256=self.row_hash, label='row', Text=self.pc_source_text)],
        }), encoding='utf-8')
        make_pack(self.romfs/'param/scenario/cs/test_scene.pack',
                  make_textblock(42, 'Japanese source'))
        report = build_dialogue.build(self.romfs, self.pc_text, self.recipe,
                                      self.root/'held-output')
        self.assertFalse(report['complete'])
        self.assertEqual(report['layout']['held_rows'], 1)
        self.assertEqual(report['layout']['unresolved_reasons'],
                         {'PC event/presentation tag requires typed 3DS mapping': 1})

    def test_unsafe_archive_member_path_is_held(self):
        bad = dq11_pack.Entry('../escape.bin', 0, 0, 0, 1, 0, b'X')
        make_pack(self.romfs/'param/scenario/cs/test_scene.pack',
                  make_textblock(42, 'Japanese source'), [bad])
        report = build_dialogue.build(self.romfs, self.pc_text, self.recipe,
                                      self.root/'unsafe-output')
        self.assertFalse(report['complete'])
        self.assertEqual(report['targets']['unresolved_reasons'],
                         {'target_pack_unresolved': 1})


if __name__ == '__main__':
    unittest.main()
