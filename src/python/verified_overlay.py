"""Rebuild supplied, source-guarded dialogue/UI and DQV4/32 resources.

All source strings are checked against the original ROMFS before any output
is promoted. Audio and movie inputs are required, never replaced with silence.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'third_party'/'kenzie'))
import dq11_pack
import threeds_textblock
import delta as kenzie_delta
from voice_map_builder import fingerprint, page_rate
from build_storage import generated_media


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative(value):
    value = value.replace('\\', '/')
    if not value or value.startswith('/') or ':' in value or '..' in value.split('/'):
        raise ValueError('unsafe_resource_path')
    return Path(value)


def string_at(blob, pointer):
    if pointer < 0 or pointer + 4 > len(blob):
        raise ValueError('pointer_bounds')
    at = pointer + struct.unpack_from('<I', blob, pointer)[0]
    if at < 4 or at % 2 or at >= len(blob) or blob[at-4:at] != b'&&&&':
        raise ValueError('string_marker')
    end = at
    while end + 2 <= len(blob):
        if blob[end:end+2] == b'\0\0':
            return blob[at:end].decode('utf-16le')
        end += 2
    raise ValueError('unterminated_string')


def patch_strings(blob, rows):
    if blob[:4] != b'BXON':
        raise ValueError('expected_bxon')
    out = bytearray(blob)
    allowed = set()
    seen = set()
    for row in rows:
        ptr = row['pointer']
        if ptr in seen:
            raise ValueError('duplicate_text_pointer')
        seen.add(ptr)
        if string_at(blob, ptr) != row['native']:
            raise ValueError('native_source_text_mismatch')
        text = row['text']
        if not isinstance(text, str) or '\0' in text:
            raise ValueError('invalid_replacement_text')
        out.extend(bytes(-len(out) % 4) + b'&&&&')
        target = len(out)
        out.extend((text + '\0').encode('utf-16le'))
        struct.pack_into('<I', out, ptr, target - ptr)
        allowed.update(range(ptr, ptr + 4))
    if any(a != b for i, (a, b) in enumerate(zip(blob, out)) if i not in allowed):
        raise AssertionError('non_pointer_metadata_modified')
    for row in rows:
        if string_at(out, row['pointer']) != row['text']:
            raise AssertionError('text_readback_failed')
    return bytes(out)


def apply_kenzie_area_title_assets(original, inputs, output_romfs):
    """Apply only exact-source Kenzie v0.7 location-art deltas."""
    manifest_path = inputs/'kenzie-area-title-assets.json'
    if not manifest_path.is_file():
        return 0, []
    manifest = load(manifest_path)
    if (manifest.get('schema_version') != 1 or
            manifest.get('upstream_release') != '0.7.0' or
            manifest.get('upstream_commit') != 'ea515509d0ab082320bedfbb27602ae2b655c956' or
            len(manifest.get('files', [])) != 28):
        raise ValueError('invalid_kenzie_area_title_manifest')
    applied, skipped, seen = 0, [], set()
    for item in manifest['files']:
        rel = relative(item['path'])
        if (len(rel.parts) != 4 or rel.parts[:3] != ('romfs', 'ui', 'location') or
                rel.suffix.lower() != '.bch' or str(rel).lower() in seen):
            raise ValueError('invalid_kenzie_area_title_path')
        seen.add(str(rel).lower())
        payload = item.get('payload', '')
        if not payload or Path(payload).name != payload:
            raise ValueError('invalid_kenzie_area_title_payload')
        source = original/Path(*rel.parts[1:])
        if not source.is_file():
            skipped.append(dict(path=str(rel), reason='source_file_missing'))
            continue
        source_data = source.read_bytes()
        if (len(source_data) != item.get('source_size') or
                digest_bytes(source_data) != item.get('source_sha256')):
            skipped.append(dict(path=str(rel), reason='source_hash_mismatch'))
            continue
        patch = inputs/'kenzie-area-title-deltas'/payload
        if not patch.is_file() or digest(patch) != item.get('payload_sha256'):
            raise ValueError('kenzie_area_title_delta_checksum_mismatch:' + str(rel))
        result = kenzie_delta.apply(source_data, patch.read_bytes())
        if (len(result) != item.get('target_size') or
                digest_bytes(result) != item.get('target_sha256')):
            raise ValueError('kenzie_area_title_target_checksum_mismatch:' + str(rel))
        destination = output_romfs/Path(*rel.parts[1:])
        if destination.exists():
            if digest(destination) == item['target_sha256']:
                applied += 1
                continue
            raise ValueError('kenzie_area_title_output_collision:' + str(rel))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(result)
        applied += 1
    return applied, skipped


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_archive(arc, replacements, path):
    before = [(e.name, e.unknown, e.table_value, e.data) for e in arc.entries]
    for index, entry in enumerate(arc.entries):
        if index in replacements or entry.name in replacements:
            entry.data = replacements.get(index, replacements.get(entry.name))
            entry.size = len(entry.data)
    # The game accepts PACK. Expand compressed PACA and retain every member;
    # emitting an ordinary PACK avoids a lossy/reverse-engineered compressor.
    arc.original_size = arc.declared_size
    blob = bytearray(dq11_pack.build_archive(arc, output_magic='PACK'))
    struct.pack_into('<I', blob, 20, zlib.crc32(blob[24:]) & 0xffffffff)
    check = dq11_pack.read_archive_bytes(bytes(blob))
    if len(check.entries) != len(before):
        raise AssertionError('archive_member_count_changed')
    for index, (old, new) in enumerate(zip(before, check.entries)):
        if old[:3] != (new.name, new.unknown, new.table_value):
            raise AssertionError('archive_metadata_changed')
        if new.data != replacements.get(index, replacements.get(new.name, old[3])):
            raise AssertionError('archive_unplanned_mutation')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def voice_payload(rows, links, jobs, template):
    texts = {(r['scene'], r['text_id']): r['text'] for r in rows}
    jobs_by_id = {j['sound_id']: j for j in jobs}
    if sorted(jobs_by_id) != list(range(7452, 7452 + 5048)):
        raise ValueError('voice_job_id_range')
    if len(jobs_by_id) != len(jobs):
        raise ValueError('duplicate_voice_jobs')
    count = struct.unpack_from('<I', template, 32)[0]
    end = 44 + count * 12
    old = struct.unpack_from('<8I', template, end)
    if count != 12384 or old[:2] != (0x34565144, 32) or old[7] != 6:
        raise ValueError('incompatible_native_voice_template')
    existing = collections.defaultdict(set)
    for i in range(old[2]):
        h1, h2, length, match, sound, rate = struct.unpack_from('<6I', template, end+32+i*24)
        existing[(h1, h2, length, sound)].add(match)
    native_rows = {}
    for link in links:
        job = jobs_by_id[link['sound_id']]
        if job['asset'].lstrip(':') != link['asset'].lstrip(':'):
            raise ValueError('runtime_asset_sound_id_mismatch')
        if list(fingerprint(link['text'])) != link['fingerprint']:
            raise ValueError('runtime_fingerprint_evidence_mismatch')
        text = texts[(link['scene'], link['text_id'])]
        h1, h2, length = fingerprint(text)
        duration = job['samples'] / job['sample_rate']
        if job.get('segment_end_sample_22050') is not None:
            duration = (job['segment_end_sample_22050'] -
                        job.get('segment_start_sample_22050', 0)) / 22050
        matches = existing[tuple(link['fingerprint'])+(link['sound_id'],)]
        if not matches:
            raise ValueError('runtime_link_missing_from_native_template')
        if len(matches) == 1:
            match = next(iter(matches))
        elif link.get('match_text_id', link['text_id']) in matches:
            match = link.get('match_text_id', link['text_id'])
        else:
            raise ValueError('ambiguous_native_text_id_guard')
        if match not in (0xffffffff, link['text_id']):
            raise ValueError('native_text_id_guard_mismatch')
        key = (h1, h2, length, match)
        value = (link['sound_id'], page_rate(duration, length))
        if key in native_rows and native_rows[key] != value:
            raise ValueError('conflicting_native_voice_key')
        native_rows[key] = value
    body = b''.join(struct.pack('<6I', *key, *value)
                    for key, value in sorted(native_rows.items()))
    paths = b''
    for job in jobs:
        expected = f"str/dqxi_voice/V_{job['sound_id']-7452:05d}.bcstm"
        if job['path'] != expected:
            raise ValueError('voice_job_path_mismatch')
        encoded = (expected + '\0').encode('ascii')
        paths += encoded + bytes(32 - len(encoded))
    size = 32 + len(body) + len(paths)
    header = struct.pack('<8I', 0x34565144, 32, len(native_rows), 24,
                         7452, len(jobs), size, 6)
    return template[:end] + header + body + paths, len(native_rows)


def find_file(roots, rel):
    for root in roots:
        path = Path(root) / rel
        if path.is_file() and not path.is_symlink():
            return path
    raise FileNotFoundError('missing_resource:' + str(rel))


def build(original, inputs, output, code_ips, voice_roots=(), movie_root=None,
          resources_only=False, pc_root=None):
    original, inputs, output = Path(original), Path(inputs), Path(output)
    movie_root = Path(movie_root) if movie_root is not None else None
    pc_root = Path(pc_root) if pc_root is not None else None
    if output.exists():
        raise ValueError('output_already_exists')
    if not original.is_dir():
        raise ValueError('missing_original_romfs')
    rows, ui = load(inputs/'dialogue.json'), load(inputs/'ui.json')
    links, jobs = load(inputs/'runtime_links.json'), load(inputs/'jobs.json')
    if (len(rows), len(ui), len(links), len(jobs)) != (5551, 3005, 5095, 5048):
        raise ValueError('incomplete_verified_inputs')
    paths = collections.defaultdict(list)
    for path in original.rglob('*.pack'):
        paths[path.stem.lower()].append(path)
    edits = collections.defaultdict(lambda: collections.defaultdict(list))
    inherited = load(inputs/'inherited-texts.json')
    inherited_members = collections.defaultdict(list)
    for member in load(inputs/'inherited-members.json'):
        rel = relative(member['path'])
        inherited_members[rel].append(member)
        edits[rel]
    for row in inherited:
        rel = relative(row['path'])
        if rel.parts[0] != 'romfs':
            raise ValueError('invalid_inherited_text_root')
        edits[Path(*rel.parts[1:])][row['entry']].append(row)
    scenes = collections.defaultdict(list)
    for row in rows:
        scenes[row['scene']].append(row)
    for scene, mapped in scenes.items():
        matches = []
        for path in paths[scene.lower()]:
            try:
                arc = dq11_pack.read_archive(path)
                members = {e.name: e.data for e in arc.entries}
                records = {name: threeds_textblock.read(members[name])
                           for name in {r['entry'] for r in mapped}}
                if all(records[r['entry']][r['index']]['key'] == r['text_id'] and
                       records[r['entry']][r['index']]['text'] == r['native']
                       for r in mapped):
                    matches.append((path, records))
            except (ValueError, KeyError, IndexError, struct.error):
                continue
        if len(matches) != 1:
            raise ValueError('non_unique_original_dialogue_target:' + scene)
        path, records = matches[0]
        for row in mapped:
            ptr = records[row['entry']][row['index']]['text_pointer']
            edits[path.relative_to(original)][row['entry']].append(row | {'pointer': ptr})
    for row in ui:
        rel = relative(row['path'])
        if rel.parts[0] != 'romfs':
            raise ValueError('invalid_ui_root')
        edits[Path(*rel.parts[1:])][row['entry']].append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=output.name+'.partial-', dir=output.parent))
    try:
        romfs = temp/'romfs'
        for rel, entries in sorted(edits.items()):
            arc = dq11_pack.read_archive(original/rel)
            members = {e.name: e.data for e in arc.entries}
            # Current dialog/UI recipes take precedence over inherited texts.
            replacements = {name: patch_strings(members[name],
                list({r['pointer']: r for r in changed}.values()))
                for name, changed in entries.items()}
            for member in inherited_members[rel]:
                name = member['entry']
                index = member['entry_index']
                if name in replacements or index in replacements:
                    raise ValueError('inherited_binary_text_overlap')
                if arc.entries[index].name != name:
                    raise ValueError('inherited_member_index_mismatch')
                if hashlib.sha256(arc.entries[index].data).hexdigest() != member['source_sha256']:
                    raise ValueError('inherited_member_source_mismatch')
                replacement = inputs/relative(member['file'])
                if digest(replacement) != member['replacement_sha256']:
                    raise ValueError('inherited_member_checksum_mismatch')
                replacements[index] = replacement.read_bytes()
            write_archive(arc, replacements, romfs/rel)
        native_arc = dq11_pack.read_archive(romfs/'syscmn.pack'
            if (romfs/'syscmn.pack').exists() else original/'syscmn.pack')
        template = (inputs/'voice-template.bxon').read_bytes()
        old_se = next(e.data for e in native_arc.entries if e.name == 'sound_se.bxon')
        if old_se[44:44+7452*12] != template[44:44+7452*12]:
            raise ValueError('original_sound_rows_mismatch')
        payload, keys = voice_payload(rows, links, jobs, template)
        write_archive(native_arc, {'sound_se.bxon': payload}, romfs/'syscmn.pack')
        shutil.copytree(inputs/'pool', romfs, dirs_exist_ok=True)
        kenzie_assets_applied, kenzie_assets_skipped = apply_kenzie_area_title_assets(
            original, inputs, romfs)
        report = dict(schema_version=1, release='v18', upstream_kenzie_release='0.7.0',
            dialogue_line_wrap_fixes=58, dialogue_rows_written=len(rows),
            inherited_translation_fields_verified=len(inherited),
            inherited_resource_members_preserved=sum(map(len, inherited_members.values())),
            newly_resolved_voice_cases=sum(r['new_voice_case'] for r in rows),
            voice_runtime_links=len(links), native_lookup_rows=keys,
            voice_jobs_required=len(jobs), voice_files_copied=0,
            pc_ui_rows_written=2920, reviewed_menu_rows_written=85,
            native_map_format='DQV4/32', native_pool_slots=6,
            kenzie_area_title_assets_applied=kenzie_assets_applied,
            kenzie_area_title_assets_skipped=kenzie_assets_skipped,
            movies_copied=0, resources_complete=True, media_complete=False,
            game_tested=False, complete=False)
        if not resources_only:
            for job in jobs:
                rel = Path('sound')/relative(job['path'])
                source = find_file(voice_roots, rel)
                with source.open('rb') as stream:
                    header = stream.read(64)
                if (len(header) < 64 or header[:4] != b'CSTM' or
                    struct.unpack_from('<I', header, 12)[0] != source.stat().st_size):
                    raise ValueError('invalid_voice_bcstm:' + job['path'])
                destination = romfs/rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                generated_media(source, destination)
                report['voice_files_copied'] += 1
            if movie_root is None or pc_root is None:
                raise ValueError('missing_converted_pc_movie_or_source_root')
            movie_report_path = movie_root/'movie-build-report.json'
            if not movie_report_path.is_file():
                raise ValueError('missing_pc_movie_build_report')
            movie_report = load(movie_report_path)
            movie_plan = load(inputs.parent/'pc_movie_build_manifest.json')
            movie_rows = movie_report.get('files', [])
            movie_by_name = {row.get('name'): row for row in movie_rows}
            expected_frames = {f"MOVIE_{row['number']:03d}.moflex": row['frames']
                               for row in movie_plan['movies']}
            expected_frames.update({f"MOVIE_{int(number):03d}.moflex": frames
                                    for number, frames in movie_plan['retrospective_frame_counts'].items()})
            if (movie_report.get('schema_version') != 1 or
                    movie_report.get('complete') is not True or
                    movie_report.get('movie_count') != 10 or len(movie_rows) != 10 or
                    len(movie_by_name) != 10 or set(movie_by_name) != set(expected_frames) or
                    movie_report.get('fps') != '359/12' or
                    (movie_report.get('width'), movie_report.get('height')) != (400, 224)):
                raise ValueError('incomplete_pc_movie_build_report')
            source_files = set()
            for name in sorted(expected_frames):
                source = find_file([movie_root], Path('movie')/relative(name))
                evidence = movie_by_name[name]
                if (not evidence.get('sources_user_supplied') or
                        not evidence.get('stream_readback_verified') or
                        evidence.get('frames') != expected_frames[name] or
                        evidence.get('fps') != '359/12' or
                        (evidence.get('width'), evidence.get('height')) != (400, 224) or
                        source.stat().st_size != evidence.get('bytes') or
                        digest(source) != evidence.get('sha256') or
                        not isinstance(evidence.get('source_sha256'), str) or
                        len(evidence.get('source_sha256', '')) != 64 or
                        not isinstance(evidence.get('source_bytes'), int) or
                        evidence.get('source_bytes', 0) <= 0):
                    raise ValueError('pc_movie_report_or_checksum_mismatch:' + name)
                source_relative = relative(evidence['source'])
                if source_relative.parts[:3] != ('Game', 'Content', 'Movies'):
                    raise ValueError('invalid_pc_movie_source_path:' + name)
                source_file = find_file([pc_root], source_relative)
                if (source_file.stat().st_size != evidence['source_bytes'] or
                        digest(source_file) != evidence['source_sha256']):
                    raise ValueError('pc_movie_source_changed:' + name)
                source_files.add(str(source_relative))
                target = romfs/'movie'/name
                target.parent.mkdir(parents=True, exist_ok=True)
                generated_media(source, target)
                report['movies_copied'] += 1
            report['movie_build_report_sha256'] = digest(movie_report_path)
            report['movie_sources_user_supplied'] = True
            report['movie_source_files_revalidated'] = len(source_files)
            report['media_complete'] = True
            report['complete'] = True
        ips = Path(code_ips)
        if digest(ips) != '41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf':
            raise ValueError('unexpected_code_ips')
        (temp/'exefs').mkdir()
        shutil.copyfile(ips, temp/'exefs/code.ips')
        shutil.copyfile(ips, temp/'code.ips')
        report['code_ips_sha256'] = digest(ips)
        manifest = [dict(path=str(p.relative_to(temp)).replace('\\','/'),
                         bytes=p.stat().st_size, sha256=digest(p))
                    for p in sorted(temp.rglob('*')) if p.is_file()]
        (temp/'files.json').write_text(json.dumps(manifest, indent=2))
        (temp/'build-report.json').write_text(json.dumps(report, indent=2))
        os.replace(temp, output)
        return report
    except Exception:
        shutil.rmtree(temp)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--original-romfs', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--code-ips', type=Path, required=True)
    parser.add_argument('--voice-root', type=Path, action='append', default=[])
    parser.add_argument('--movie-root', type=Path)
    parser.add_argument('--pc-root', type=Path)
    parser.add_argument('--resources-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.original_romfs, args.inputs, args.output,
        args.code_ips, args.voice_root, args.movie_root, args.resources_only, args.pc_root), indent=2))


if __name__ == '__main__':
    main()
