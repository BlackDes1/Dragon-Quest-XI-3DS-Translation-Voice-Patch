"""Build the native DQV4 voice lookup from local PC text/audio sources.

The checked-in recipes contain identifiers and audio asset references only.
Dialog text is read from this user's extracted PC tables, then reduced to the
same two fingerprints used by the native code patch. No text or audio is
written into the installer source.
"""
import argparse
import collections
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pc_dialogue_build


SOUND_FIRST = 7452
CURRENT_BUILD_ASSIGNMENTS = 5095
MAGIC = 0x34565144
MAP_VERSION = 20
ROW_SIZE = 24
IGNORED = {32, 10, 13, 9, 0x3000, 0xE100}


def fingerprint(text):
    """Mirror native_voice.c's UTF-16 fingerprint, including page-marker skip."""
    if not isinstance(text, str) or not text:
        raise ValueError('empty_voice_text')
    if '\0' in text:
        raise ValueError('embedded_nul')
    h1, h2, length = 2166136261, 5381, 0
    for unit in struct.unpack('<' + 'H' * (len(text.encode('utf-16le')) // 2),
                              text.encode('utf-16le')):
        if unit == 0:
            break
        if unit in IGNORED:
            continue
        h1 = ((h1 ^ unit) * 16777619) & 0xFFFFFFFF
        h2 = (h2 * 33 + unit) & 0xFFFFFFFF
        length += 1
    if not length:
        raise ValueError('empty_voice_fingerprint')
    return h1, h2, length


def _job_key(job):
    return (job.get('subsong'), job.get('material_index'), job.get('samples'),
            job.get('sample_rate'))


def _is_segment(job):
    return (job.get('segment_start_sample_22050') is not None or
            job.get('segment_end_sample_22050') is not None)


def resolve_sound(stream, jobs_by_asset):
    """Resolve aliases and repeated segment recipes without guessing a clip."""
    assets = stream.get('assets')
    if not isinstance(assets, list) or not assets:
        raise ValueError('voice_asset_missing')
    candidates = []
    for asset in assets:
        if not isinstance(asset, str) or not asset:
            raise ValueError('invalid_voice_asset')
        candidates.extend(jobs_by_asset.get(asset, []))
    key = _job_key(stream)
    candidates = [job for job in candidates if _job_key(job) == key]
    full = [job for job in candidates if not _is_segment(job)]
    if full:
        candidates = full
    sound_ids = {job.get('sound_id') for job in candidates
                 if isinstance(job.get('sound_id'), int)}
    if not sound_ids:
        raise ValueError('voice_asset_job_not_found')
    if len(sound_ids) != 1:
        raise ValueError('voice_asset_sound_id_ambiguous')
    sound_id = sound_ids.pop()
    if sound_id < SOUND_FIRST:
        raise ValueError('voice_sound_id_below_native_range')
    durations = []
    for job in candidates:
        rate = job.get('sample_rate')
        samples = job.get('samples')
        if rate and samples:
            durations.append(samples / rate)
    if not durations or max(durations) - min(durations) > 0.0001:
        raise ValueError('voice_duration_missing_or_ambiguous')
    return sound_id, durations[0]


def page_rate(duration_seconds, fingerprint_length):
    """Convert clip duration to the native tick-per-visible-character scale."""
    if duration_seconds <= 0 or fingerprint_length <= 0:
        raise ValueError('invalid_voice_timing')
    # GetSystemTick() >> 20 advances at about 256 units per second. The native
    # callback multiplies consumed characters by rate and shifts by 8.
    value = round(duration_seconds * 65536 / fingerprint_length)
    return min(0xFFFFFFFF, max(1, value))


def encode_map(entries, sound_count):
    if not isinstance(sound_count, int) or not 0 <= sound_count <= 30000:
        raise ValueError('invalid_voice_sound_count')
    for row in entries:
        if any(not isinstance(row.get(key), int) or not 0 <= row[key] <= 0xFFFFFFFF
               for key in ('h1', 'h2', 'length', 'text_id', 'sound_id', 'page_rate')):
            raise ValueError('invalid_voice_map_entry')
        if row['length'] == 0 or row['page_rate'] == 0:
            raise ValueError('empty_voice_map_entry')
        if not SOUND_FIRST <= row['sound_id'] < SOUND_FIRST + sound_count:
            raise ValueError('voice_map_sound_id_out_of_range')
    ordered = sorted(entries, key=lambda row: (row['h1'], row['h2'], row['length'], row['text_id']))
    seen = {}
    for row in ordered:
        key = (row['h1'], row['h2'], row['length'], row['text_id'])
        if key in seen and seen[key] != (row['sound_id'], row['page_rate']):
            raise ValueError('conflicting_voice_fingerprint')
        seen[key] = (row['sound_id'], row['page_rate'])
    ordered = [dict(h1=k[0], h2=k[1], length=k[2], text_id=k[3],
                    sound_id=v[0], page_rate=v[1]) for k, v in seen.items()]
    ordered.sort(key=lambda row: (row['h1'], row['h2'], row['length'], row['text_id']))
    size = 32 + len(ordered) * ROW_SIZE
    header = struct.pack('<8I', MAGIC, MAP_VERSION, len(ordered), ROW_SIZE,
                         SOUND_FIRST, sound_count, size, 0)
    body = b''.join(struct.pack('<6I', row['h1'], row['h2'], row['length'],
                                row['text_id'], row['sound_id'], row['page_rate'])
                    for row in ordered)
    return header + body, ordered


def build(pc_text_root, dialogue_recipe_path, voice_recipe_path, jobs_path, output):
    voice_recipe = pc_dialogue_build.load_json(voice_recipe_path)
    if voice_recipe.get('schema_version') != 1 or not isinstance(voice_recipe.get('assignments'), list):
        raise ValueError('unsupported_voice_assignment_recipe')
    summary = voice_recipe.get('summary', {})
    expected_assignments = summary.get('expected_current_build_assignments',
                                       CURRENT_BUILD_ASSIGNMENTS)
    if (not isinstance(expected_assignments, int) or
            expected_assignments < len(voice_recipe['assignments'])):
        raise ValueError('invalid_expected_voice_assignment_count')
    jobs_data = pc_dialogue_build.load_json(jobs_path)
    jobs = jobs_data.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('voice_jobs_missing')
    jobs_by_asset = collections.defaultdict(list)
    for job in jobs:
        if not isinstance(job.get('asset'), str) or not isinstance(job.get('sound_id'), int):
            raise ValueError('invalid_voice_job')
        jobs_by_asset[job['asset']].append(job)
    ids = sorted({job['sound_id'] for job in jobs})
    if ids != list(range(SOUND_FIRST, SOUND_FIRST + len(ids))):
        raise ValueError('voice_sound_id_range_not_contiguous')
    if len(ids) != len(jobs):
        raise ValueError('duplicate_voice_job_sound_id')

    _, dialogue_rows = pc_dialogue_build.read_recipe(dialogue_recipe_path)
    targets = {(row['scene'].lower(), row['target_id'], row['target_index']): row
               for row in dialogue_rows}
    source_index, source_report = pc_dialogue_build.load_source_rows(pc_text_root, dialogue_rows)
    result, held = [], collections.Counter()
    for assignment in voice_recipe['assignments']:
        key = (str(assignment.get('scene', '')).lower(), assignment.get('text_id'),
               assignment.get('target_index'))
        target = targets.get(key)
        if target is None:
            held['dialogue_target_not_in_pc_recipe'] += 1
            continue
        anchor = (target['source'], target['source_index'], target['source_offset'],
                  target['source_row_sha256'])
        source_row = source_index.get(anchor)
        if source_row is None:
            held['pc_source_anchor_missing'] += 1
            continue
        try:
            text, _, _ = pc_dialogue_build.layout_text(source_row)
            sound_options = []
            for stream in assignment.get('streams', []):
                sound_options.append(resolve_sound(stream, jobs_by_asset))
            sound_ids = {item[0] for item in sound_options}
            if len(sound_ids) != 1:
                raise ValueError('voice_stream_sound_id_ambiguous')
            h1, h2, length = fingerprint(text)
            sound_id = sound_ids.pop()
            duration = max(item[1] for item in sound_options)
            result.append(dict(h1=h1, h2=h2, length=length, text_id=key[1],
                               sound_id=sound_id, page_rate=page_rate(duration, length),
                               scene=key[0], target_index=key[2]))
        except ValueError as error:
            held[str(error)] += 1
    if source_report['source_tables_missing']:
        held['pc_source_tables_missing'] += len(source_report['source_tables_missing'])
    if held:
        # A partial map is useful for diagnostics, but must not be promoted as
        # a complete voice build. Keep the exact unresolved count in the report.
        pass

    fingerprint_index = collections.defaultdict(list)
    for row in result:
        key = (row['h1'], row['h2'], row['length'], row['text_id'])
        fingerprint_index[key].append(row)
    conflict_keys = {
        key for key, rows in fingerprint_index.items()
        if len({(row['sound_id'], row['page_rate']) for row in rows}) > 1
    }
    fingerprint_conflicts = []
    if conflict_keys:
        for key in sorted(conflict_keys):
            rows = fingerprint_index[key]
            fingerprint_conflicts.append({
                'fingerprint': list(key[:3]),
                'text_id': key[3],
                'sound_ids': sorted({row['sound_id'] for row in rows}),
                'page_rates': sorted({row['page_rate'] for row in rows}),
                'assignments': [
                    {'scene': row['scene'], 'target_index': row['target_index']}
                    for row in rows
                ],
            })
        conflict_assignments = sum(
            len(fingerprint_index[key]) for key in conflict_keys
        )
        held['conflicting_voice_fingerprint'] += conflict_assignments
        result = [row for row in result
                  if (row['h1'], row['h2'], row['length'], row['text_id']) not in conflict_keys]

    data, ordered = encode_map(result, len(ids))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    map_path = output / 'map.bin'
    temp = map_path.with_suffix('.partial')
    temp.write_bytes(data)
    os.replace(temp, map_path)
    recipe_complete = len(result) == len(voice_recipe['assignments']) and not held
    runtime_assignment_count = sum(assignment.get('runtime_verified') is True
                                   for assignment in voice_recipe['assignments'])
    page_rate_validated = summary.get('page_rate_runtime_validated') is True
    report = {
        'schema_version': 1,
        'source_game_text_in_recipe': False,
        'assignments_required': expected_assignments,
        'assignments_in_recipe': len(voice_recipe['assignments']),
        'assignments_mapped': len(result),
        'unique_map_rows': len(ordered),
        'assignments_missing_from_recipe': max(0, expected_assignments - len(voice_recipe['assignments'])),
        'assignments_runtime_verified': runtime_assignment_count,
        'fingerprint_conflict_groups': len(fingerprint_conflicts),
        'fingerprint_conflict_assignments': sum(
            len(item['assignments']) for item in fingerprint_conflicts
        ),
        'fingerprint_conflicts': fingerprint_conflicts,
        'recipe_complete': recipe_complete,
        'assignment_count_matches_current_build': len(voice_recipe['assignments']) == expected_assignments,
        'unique_voice_jobs': len(jobs),
        'sound_id_first': SOUND_FIRST,
        'sound_id_count': len(ids),
        'map_bytes': len(data),
        'map_sha256': __import__('hashlib').sha256(data).hexdigest(),
        'page_rate_algorithm': 'round(clip_seconds * 65536 / non_whitespace_utf16_units)',
        'page_rate_requires_runtime_validation': True,
        'source_tables_missing': source_report['source_tables_missing'],
        'held': dict(held),
        'page_rate_runtime_validated': page_rate_validated,
        'complete': (recipe_complete and
                     len(voice_recipe['assignments']) == expected_assignments and
                     runtime_assignment_count == expected_assignments and
                     page_rate_validated),
    }
    (output / 'voice-map-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pc-text-root', type=Path, required=True)
    parser.add_argument('--dialogue-recipe', type=Path,
                        default=Path(__file__).resolve().parents[1]/'recipes/pc_dialogue_map.json')
    parser.add_argument('--voice-recipe', type=Path,
                        default=Path(__file__).resolve().parents[1]/'recipes/voice_assignments.json')
    parser.add_argument('--voice-jobs', type=Path,
                        default=Path(__file__).resolve().parents[1]/'recipes/voice_jobs.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.pc_text_root, args.dialogue_recipe, args.voice_recipe,
                   args.voice_jobs, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['complete'] else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
