"""Inventory supplemental PC voice banks and event tracks from selected maps.

This exports identifiers and timing/control metadata only. It does not copy
voice samples or caption strings into the source project, and it does not claim
that a PC event has been matched to a native 3DS dialogue row.
"""
from pathlib import Path
import json
import os
import struct

import sab_reader
import ue4_voice_reader


def safe(root, relative):
    root = Path(root).resolve()
    relative = str(relative).replace('\\', '/')
    if relative.startswith('/') or ':' in relative or '..' in relative.split('/'):
        raise ValueError('Unsafe PC scene asset path')
    result = root.joinpath(*relative.split('/')).resolve()
    if root not in result.parents:
        raise ValueError('PC scene asset escapes extracted root')
    return result


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def _pairs(manifest, kind, expected_files, expected_pairs, extensions):
    groups = {}
    selected = [asset for asset in manifest.get('assets', []) if asset.get('kind') == kind]
    if len(selected) != expected_files or expected_files != expected_pairs * len(extensions):
        raise ValueError('Supplemental PC asset manifest count mismatch: ' + kind)
    for asset in selected:
        path = str(asset['path']).replace('\\', '/')
        suffix = Path(path).suffix.lower()
        if suffix not in extensions:
            raise ValueError('Unexpected supplemental asset extension: ' + path)
        key = (str(asset['chunk']), path.rsplit('.', 1)[0].casefold())
        extensions_found = groups.setdefault(key, {})
        if suffix in extensions_found:
            raise ValueError('Duplicate supplemental asset pair member: ' + path)
        extensions_found[suffix] = asset
    if len(groups) != expected_pairs or any(set(group) != set(extensions) for group in groups.values()):
        raise ValueError('Incomplete supplemental PC asset pairs: ' + kind)
    return groups


def inspect_supplemental_voice_banks(source, output, manifest):
    """Parse extra HCA/SAB stream identity without exporting audio samples."""
    groups = _pairs(manifest, 'voice_extra', int(manifest.get('additional_voice_files', 0)),
                    int(manifest.get('additional_voice_banks', 0)), ('.uasset', '.uexp'))
    banks = []
    problems = []
    for (chunk, _), pair in sorted(groups.items()):
        asset = pair['.uexp']
        relative = chunk + '/' + asset['path']
        try:
            path = safe(source, relative)
            raw = path.read_bytes()
            offset, sab = sab_reader.embedded(raw)
            parsed = sab_reader.read(sab)
            streams = []
            for stream in parsed['streams']:
                streams.append({key: stream.get(key) for key in
                                ('subsong', 'material_index', 'samples', 'sample_rate', 'channels', 'codec', 'assets')})
            banks.append({'chunk': chunk, 'path': asset['path'], 'bytes': len(raw),
                          'embedded_sab_offset': offset, 'streams': streams})
        except (OSError, ValueError, KeyError, IndexError, struct.error, UnicodeError) as error:
            problems.append({'chunk': chunk, 'path': asset['path'], 'reason': str(error)})
    report = {'required_banks': len(groups), 'parsed_banks': len(banks), 'streams': sum(len(x['streams']) for x in banks),
              'complete': len(banks) == len(groups) and not problems, 'source_hash_check': False,
              'problems': problems, 'banks': banks}
    write_json(Path(output) / 'pc-scenes' / 'supplemental-voice-inventory.json', report)
    return {key: value for key, value in report.items() if key != 'banks'}


def export_scene_events(source, output, manifest):
    """Read selected map tracks and export event IDs/timing, not caption text."""
    groups = _pairs(manifest, 'scene', int(manifest.get('scene_map_files', 0)),
                    int(manifest.get('scene_map_pairs', 0)), ('.umap', '.uexp'))
    maps = []
    problems = []
    totals = {'caption_tracks': 0, 'caption_rows': 0, 'sound_tracks': 0, 'sound_rows': 0,
              'synchro_tracks': 0, 'synchro_rows': 0}
    text_ids = set()
    sound_assets = set()
    for (chunk, _), pair in sorted(groups.items()):
        asset = pair['.umap']
        relative = chunk + '/' + asset['path']
        try:
            package_path = safe(source, relative)
            package = ue4_voice_reader.Package.from_path(package_path)
            scene = ue4_voice_reader.read_scene(package)
            record = {'chunk': chunk, 'path': asset['path'], 'package_counts': scene.get('counts', {}),
                      'tracks': {}}
            for track_type, track_key, row_key in (
                    ('caption_tracks', 'caption_tracks', 'caption_rows'),
                    ('sound_tracks', 'sound_tracks', 'sound_rows'),
                    ('synchro_tracks', 'synchro_tracks', 'synchro_rows')):
                selected_tracks = []
                for track in scene.get(track_key, []):
                    fields = track.get('scalar_fields', {})
                    rows = []
                    for row in track.get('rows', []):
                        event_fields = row.get('fields', {})
                        # Scene caption strings are not needed for identity matching;
                        # retain TextID, sound names, timing and control properties.
                        safe_fields = {k: v for k, v in event_fields.items()
                                       if str(k).casefold() not in ('text', 'captiontext', 'displaytext', 'string')}
                        text_id = safe_fields.get('TextID')
                        if text_id is not None:
                            text_ids.add(str(text_id))
                        asset_name = safe_fields.get('AssetPathName')
                        if asset_name is not None:
                            sound_assets.add(str(asset_name))
                        rows.append({'fields': safe_fields})
                    selected_tracks.append({'object_name': track.get('object_name'),
                        'class_name': track.get('class_name'), 'scalar_fields': fields,
                        'evidence_sha256': track.get('evidence_sha256'), 'rows': rows})
                    totals[track_type] += 1
                    totals[row_key] += len(rows)
                record['tracks'][track_type] = selected_tracks
            maps.append(record)
        except (OSError, ValueError, KeyError, IndexError, struct.error, UnicodeError) as error:
            problems.append({'chunk': chunk, 'path': asset['path'], 'reason': str(error)})
    report = {'required_maps': len(groups), 'parsed_maps': len(maps), 'complete': len(maps) == len(groups) and not problems,
              'text_strings_exported': False, 'native_3ds_mapping_verified': False,
              'source_hash_check': False, **totals, 'unique_text_ids': len(text_ids),
              'unique_sound_asset_names': len(sound_assets), 'problems': problems}
    write_json(Path(output) / 'pc-scenes' / 'scene-events.json', {'report': report, 'maps': maps})
    return report
