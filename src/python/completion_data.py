"""Collect exact parser metadata; never place dialogue or media in the ZIP."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import argparse
import collections
import json
import re
import unicodedata
import zipfile
import pc_components as pc
import pc_source_inventory as inventory


def collect(work):
    reports = list(work.glob('pc-components*/component-report.json'))
    if not reports:
        # Successful compact builds retain metadata, but release source exports.
        retained = inventory.local_file(work, 'reports/component-report.json')
        report = pc.read_json(retained)
        tables = []
        for table in report['texts']['tables']:
            if table['language'] != 'en':
                continue
            problems = table.get('layout_problems', {})
            tables.append(dict(name=table['name'],
                unresolved_rows=sum(p['count'] for p in problems.values()),
                reasons={k: p['count'] for k, p in problems.items()},
                reason_examples={k: p.get('example_labels', []) for k, p in problems.items()}))
        return dict(schema_version=2, game_payloads_included=False, source_hash_check=False,
                    tables=tables, voice_banks=[], full_build_ready=False,
                    source_exports_released=True, detailed_source_inspection_available=False,
                    voice_problem_count=len(report['voices']['problems']))
    path = max(reports, key=lambda p: p.stat().st_mtime_ns)
    path = inventory.local_file(work, path.relative_to(work))
    report = pc.read_json(path)
    tables = []
    for table in report['texts']['tables']:
        if table['language'] != 'en':
            continue
        source = inventory.local_file(path.parent, 'pc-text/en/'+table['name']+'.json')
        tags = collections.Counter(); markers = collections.Counter()
        marker_examples = {}; fullwidth = collections.Counter()
        examples = {}; reasons = collections.Counter(); reason_examples = {}
        for row in pc.read_json(source)['rows']:
            if 'dialog_layout_unresolved' not in row:
                continue
            reason = row['dialog_layout_unresolved']
            reasons[reason] += 1
            labels = reason_examples.setdefault(reason, [])
            if len(labels) < 5 and row['label'] not in labels:
                labels.append(row['label'])
            for tag in re.findall(r'<[^>]*>', row['Text']):
                tags[tag] += 1
                samples = examples.setdefault(tag, [])
                if len(samples) < 3 and row['label'] not in samples:
                    samples.append(row['label'])
            for c in row['Text']:
                codepoint = ord(c)
                if (0xe000 <= codepoint <= 0xf8ff or
                        0xf0000 <= codepoint <= 0xffffd or
                        0x100000 <= codepoint <= 0x10fffd):
                    marker = 'U+%04X' % codepoint
                    markers[marker] += 1
                    labels = marker_examples.setdefault(marker, [])
                    if len(labels) < 5 and row['label'] not in labels:
                        labels.append(row['label'])
                elif unicodedata.east_asian_width(c) == 'F':
                    fullwidth['U+%04X' % codepoint] += 1
        tables.append(dict(name=table['name'], unresolved_rows=sum(reasons.values()), reasons=dict(reasons),
                           reason_examples=reason_examples, tags=dict(tags),
                           private_use_markers=dict(markers), marker_example_labels=marker_examples,
                           fullwidth_characters=dict(fullwidth), example_labels=examples))
    source = inventory.local_file(work, 'pc-assets/pc-extracted')
    manifest = pc.read_json(pc.RECIPES.parent/'pc_asset_manifest.json')
    allowed = {(a['chunk'], a['path']) for a in manifest['assets'] if a['kind'] == 'voice'}
    jobs = pc.read_json(pc.RECIPES/'voice_jobs.json')['jobs']
    pairs = {(p['bank_chunk'], p['bank_path']) for p in report['voices']['problems']}
    banks = []
    for chunk, relative in sorted(pairs):
        if (chunk, relative) not in allowed:
            raise ValueError('Diagnose verweist auf keine Bank aus dem aktuellen Rezept')
        bank_path = inventory.local_file(source, chunk+'/'+relative)
        _, blob = pc.sab_reader.embedded(bank_path.read_bytes())
        parsed = pc.sab_reader.read(blob)
        members = [j for j in jobs if (j['bank_chunk'], j['bank_path']) == (chunk, relative)]
        keys = ('assets', 'subsong', 'material_index', 'samples', 'sample_rate', 'channels', 'codec')
        streams = [{k: s[k] for k in keys if k in s} for s in parsed['streams']]
        banks.append(dict(chunk=chunk, path=relative, bytes=bank_path.stat().st_size, streams=streams,
                          current_inspection=pc.inspect_voices(source, members)))
    return dict(schema_version=2, game_payloads_included=False, source_hash_check=False,
                tables=tables, voice_banks=banks, full_build_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.work.resolve())
    with args.output.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('completion-metadata.json', json.dumps(report, ensure_ascii=False, indent=2))
    print('Completion data created: '+str(args.output), flush=True)
    print('No dialogue, CIA, PAK, audio or movie content is included.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
