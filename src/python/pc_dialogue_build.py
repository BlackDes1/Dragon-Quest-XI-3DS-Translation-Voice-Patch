"""Build verified PC-derived dialogue packs as a ROMFS overlay.

The shipped recipe contains source-row hashes and native destination IDs only.
Text is read from the user's extracted PC tables. Unmapped, ambiguous, or
unsupported rows remain held and make the report incomplete.
"""
import argparse
import collections
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dialog_layout
import dq11_blz
import dq11_pack
import threeds_textblock


SHA256 = re.compile(r'^[0-9a-f]{64}$')
FIELDS = {'scene', 'target_id', 'target_index', 'entry', 'source',
          'source_index', 'source_offset', 'source_row_sha256'}


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def safe_relative(value):
    value = str(value).replace('\\', '/')
    parts = value.split('/')
    if not value or value.startswith('/') or ':' in value or '..' in parts:
        raise ValueError('unsafe_relative_path')
    return value


def read_recipe(path):
    recipe = load_json(path)
    if recipe.get('schema_version') != 1 or not isinstance(recipe.get('entries'), list):
        raise ValueError('unsupported_dialogue_recipe')
    result = []
    seen = set()
    for row in recipe['entries']:
        if set(row) != FIELDS:
            raise ValueError('dialogue_recipe_has_unexpected_fields')
        item = dict(row)
        item['source'] = safe_relative(item['source'])
        if (not isinstance(item['scene'], str) or not item['scene'] or
                not isinstance(item['entry'], str) or not item['entry']):
            raise ValueError('invalid_dialogue_recipe_identity')
        if not all(isinstance(item[k], int) and item[k] >= 0 for k in
                   ('target_id', 'target_index', 'source_index', 'source_offset')):
            raise ValueError('invalid_dialogue_recipe_index')
        if not SHA256.fullmatch(str(item['source_row_sha256'])):
            raise ValueError('invalid_dialogue_recipe_hash')
        identity = (item['scene'].lower(), item['entry'], item['target_index'])
        if identity in seen:
            raise ValueError('duplicate_dialogue_target')
        seen.add(identity)
        result.append(item)
    return recipe, result


def load_source_rows(pc_text_root, recipe_rows):
    wanted_sources = {r['source'] for r in recipe_rows}
    tables = {Path(source).stem for source in wanted_sources}
    index = {}
    missing_files = []
    duplicate_anchors = 0
    for table in sorted(tables):
        path = Path(pc_text_root)/(table+'.json')
        if not path.is_file():
            missing_files.append(table+'.json')
            continue
        data = load_json(path)
        rows = data.get('rows') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError('invalid_pc_text_export:'+path.name)
        for row in rows:
            source = row.get('source')
            if source not in wanted_sources:
                continue
            key = (source, row.get('index'), row.get('offset'), row.get('row_sha256'))
            if key in index:
                duplicate_anchors += 1
                if index[key].get('Text') != row.get('Text'):
                    raise ValueError('conflicting_pc_source_anchor')
            else:
                index[key] = row
    return index, dict(source_tables_requested=len(tables), source_tables_missing=missing_files,
                       duplicate_export_anchors=duplicate_anchors)


def layout_text(pc_row):
    text = pc_row.get('Text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('empty_pc_text')
    result = dialog_layout.from_pc(text)
    # U+E100 opts into the checked native three-row page handler. It is
    # ignored by the voice fingerprint, so line/page layout cannot change the
    # selected voice. This overlay is not installable until that hook is built.
    translated = '\ue100'+result['text']
    lines = result['text'].splitlines()
    if not lines or any(dialog_layout.visible_width(line) > dialog_layout.MAX_COLUMNS
                        for line in lines):
        raise AssertionError('dialog_layout_width_regression')
    return translated, len(lines), len(result['pages'])


def read_archive(path, scratch):
    blob = Path(path).read_bytes()
    if blob[:4] == b'PACA':
        blob = dq11_blz.decompress(blob)
    if blob[:4] not in (b'PACK', b'PACA'):
        raise ValueError('unsupported_pack_magic')
    probe = Path(scratch)/'archive.pack'
    probe.write_bytes(blob)
    archive = dq11_pack.read_archive(probe)
    # Archive member names later become local extraction paths during the
    # rebuild verification. Reject traversal and absolute paths before that.
    for entry in archive.entries:
        safe_relative(entry.name)
    return archive


def target_entry_map(archive, wanted_entries):
    result = {}
    for item in archive.entries:
        if item.name not in wanted_entries:
            continue
        if item.name in result:
            raise ValueError('duplicate_textblock_entry')
        result[item.name] = item
    return result


def candidate_matches(path, scene_rows, scratch):
    try:
        archive = read_archive(path, scratch)
        entries = target_entry_map(archive, {r['entry'] for r in scene_rows})
        by_entry = collections.defaultdict(list)
        for row in scene_rows:
            by_entry[row['entry']].append(row)
        for name, mapped in by_entry.items():
            entry = entries.get(name)
            if entry is None:
                return None
            records = threeds_textblock.read(entry.data)
            indexed = {r['index']: r for r in records}
            for row in mapped:
                target = indexed.get(row['target_index'])
                if target is None or target['key'] != row['target_id']:
                    return None
        return archive
    except (OSError, ValueError, struct.error, UnicodeError):
        return None


def rebuild_archive(archive, edits, scratch):
    replacement_root = Path(scratch)/'replace'
    if replacement_root.exists():
        shutil.rmtree(replacement_root)
    replacement_root.mkdir(parents=True)
    before = [(e.name, e.table_value, e.unknown, e.data) for e in archive.entries]
    for entry in archive.entries:
        changes = edits.get(entry.name)
        if changes:
            entry.data = threeds_textblock.patch(entry.data, changes)
            entry.size = len(entry.data)
            (replacement_root/entry.name).write_bytes(entry.data)
    result = bytearray(dq11_pack.build_archive(archive, replacement_root, 'PACK'))
    if len(result) < 24 or result[:4] != b'PACK':
        raise ValueError('rebuilt_pack_header_invalid')
    struct.pack_into('<I', result, 20, zlib.crc32(result[24:]) & 0xffffffff)
    check_path = Path(scratch)/'readback.pack'
    check_path.write_bytes(result)
    check = dq11_pack.read_archive(check_path)
    after = [(e.name, e.table_value, e.unknown, e.data) for e in check.entries]
    if len(before) != len(after):
        raise AssertionError('pack_entry_count_changed')
    changed = set(edits)
    for old, new in zip(before, after):
        if old[:3] != new[:3] or (old[0] not in changed and old[3] != new[3]):
            raise AssertionError('unplanned_pack_entry_change')
    return bytes(result)


def build(original_romfs, pc_text_root, recipe_path, output_root):
    original_romfs = Path(original_romfs).resolve()
    pc_text_root = Path(pc_text_root).resolve()
    output_root = Path(output_root).absolute()
    if not original_romfs.is_dir() or not pc_text_root.is_dir():
        raise ValueError('missing_original_romfs_or_pc_text_export')
    if output_root.exists():
        raise ValueError('output_already_exists')
    output_root.parent.mkdir(parents=True, exist_ok=True)
    recipe, recipe_rows = read_recipe(recipe_path)
    source_index, source_report = load_source_rows(pc_text_root, recipe_rows)
    entries_by_scene = collections.defaultdict(list)
    layout_by_target = {}
    counts = collections.Counter()
    layout_errors = collections.Counter()
    page_rows = 0
    max_page_count = 0

    for row in recipe_rows:
        anchor = (row['source'], row['source_index'], row['source_offset'],
                  row['source_row_sha256'])
        source_row = source_index.get(anchor)
        if source_row is None:
            counts['source_anchor_missing'] += 1
        else:
            counts['source_anchor_verified'] += 1
            try:
                translated, line_count, page_count = layout_text(source_row)
                layout_by_target[(row['scene'].lower(), row['entry'], row['target_index'])] = translated
                counts['layout_ready'] += 1
                counts['dialogue_lines'] += line_count
                page_rows += int(page_count > 1)
                max_page_count = max(max_page_count, page_count)
            except ValueError as error:
                layout_errors[str(error)] += 1
                counts['layout_held'] += 1
        entries_by_scene[row['scene'].lower()].append(row)

    candidates_by_scene = collections.defaultdict(list)
    wanted_scenes = set(entries_by_scene)
    for path in original_romfs.rglob('*'):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == '.pack':
            stem = path.stem.lower()
            if stem in wanted_scenes:
                candidates_by_scene[stem].append(path)

    output_temp = Path(tempfile.mkdtemp(prefix=output_root.name+'.partial-',
                                        dir=str(output_root.parent)))
    overlay = output_temp/'romfs'
    selected = {}
    target_failures = collections.Counter()
    try:
        with tempfile.TemporaryDirectory(prefix='dqxi-dialogue-probe-') as scratch:
            for scene, scene_rows in sorted(entries_by_scene.items()):
                paths = sorted(candidates_by_scene.get(scene, []))
                matches = []
                for path in paths:
                    archive = candidate_matches(path, scene_rows, scratch)
                    if archive is not None:
                        matches.append((path, archive))
                if len(matches) != 1:
                    key = 'target_pack_missing' if not paths else \
                          'target_pack_unresolved' if not matches else 'target_pack_ambiguous'
                    target_failures[key] += 1
                    continue
                selected[scene] = matches[0]
            counts['target_scenes_required'] = len(entries_by_scene)
            counts['target_scenes_selected'] = len(selected)
            counts['target_rows_selected'] = sum(len(entries_by_scene[s]) for s in selected)

            for scene, (path, archive) in sorted(selected.items()):
                edits = collections.defaultdict(dict)
                for row in entries_by_scene[scene]:
                    key = (scene, row['entry'], row['target_index'])
                    text = layout_by_target.get(key)
                    if text is not None:
                        edits[row['entry']][row['target_index']] = text
                if not edits:
                    continue
                result = rebuild_archive(archive, edits, scratch)
                relative = path.relative_to(original_romfs)
                safe_relative(relative.as_posix())
                destination = overlay/relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix+'.partial')
                temporary.write_bytes(result)
                os.replace(temporary, destination)
                counts['packs_written'] += 1
                counts['dialogue_rows_written'] += sum(len(v) for v in edits.values())

        complete = (counts['dialogue_rows_written'] == len(recipe_rows) and
                    not target_failures and not layout_errors and
                    not source_report['source_tables_missing'])
        report = {
            'schema_version': 1,
            'input_recipe_revision': recipe.get('mapping_revision'),
            'recipe_rows': len(recipe_rows),
            'source_content_in_recipe': False,
            'coverage_summary': recipe.get('coverage_summary', {}),
            'source': source_report | dict(verified_source_rows=counts['source_anchor_verified'],
                                          missing_source_rows=counts['source_anchor_missing']),
            'layout': dict(ready_rows=counts['layout_ready'], held_rows=counts['layout_held'],
                           pages_required=page_rows, max_pages_for_one_dialogue=max_page_count,
                           max_columns=dialog_layout.MAX_COLUMNS,
                           rows_per_page=dialog_layout.ROWS_PER_PAGE,
                           page_marker_required='U+E100',
                           unresolved_reasons=dict(layout_errors)),
            'targets': dict(required_scenes=len(entries_by_scene), selected_scenes=len(selected),
                            selected_rows=counts['target_rows_selected'],
                            packs_written=counts['packs_written'],
                            dialogue_rows_written=counts['dialogue_rows_written'],
                            unresolved_reasons=dict(target_failures)),
            'native_pager_required': page_rows > 0,
            'voice_map_integrated': False,
            'standalone_mod_complete': False,
            'complete': complete,
        }
        (output_temp/'dialogue-build-report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if output_root.parent != output_temp.parent:
            raise AssertionError('temporary_output_parent_changed')
        os.replace(output_temp, output_root)
        return report
    except Exception:
        shutil.rmtree(output_temp, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-romfs', type=Path, required=True)
    parser.add_argument('--pc-text-root', type=Path, required=True)
    parser.add_argument('--recipe', type=Path,
                        default=Path(__file__).resolve().parents[1]/'recipes/pc_dialogue_map.json')
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.original_romfs, args.pc_text_root, args.recipe, args.output_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
