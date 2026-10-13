"""Build PC-derived components without a previous mod or source hash whitelist.

This is a component converter, not a complete playable-mod publisher. Reports
explicitly retain missing English sources, text schemas and runtime integration.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import argparse
import array
import collections
import json
import os
import struct
import subprocess
import tempfile
import wave
import sab_reader
import textserifu_reader
import ue4_voice_reader
from wav_to_bcstm_pcm16 import convert
import dialog_layout
import pc_source_inventory
import pc_scene_events

RECIPES = Path(__file__).resolve().parent.parent / 'recipes'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, path)


def safe(root, relative):
    root = Path(root).resolve()
    relative = str(relative).replace('\\', '/')
    if relative.startswith('/') or ':' in relative or '..' in relative.split('/'):
        raise ValueError('Unsafe resource path: ' + relative)
    candidate = root.joinpath(*relative.split('/')).resolve()
    if root not in candidate.parents:
        raise ValueError('Resource escapes source directory: ' + relative)
    return candidate


def select_stream(parsed, job):
    # Resolve the actual reference chain. Do not assume sound order == subsong.
    matches = [r for r in parsed['streams'] if job['asset'] in r['assets']]
    if not matches:
        raise ValueError('Asset reference missing: ' + job['asset'])
    # UE banks can expose one alias for multiple materials. Select only when
    # the measured stream profile uniquely identifies the referenced clip.
    profile = ('sample_rate', 'samples', 'channels', 'codec')
    exact = [stream for stream in matches
             if all(stream.get(key) == job.get(key) for key in profile)]
    if len(exact) != 1:
        reason = 'ambiguous' if len(exact) > 1 else 'profile mismatch'
        raise ValueError('Asset reference ' + reason + ': ' + job['asset'])
    return exact[0]


def normalize_wav(source, dest, start=0, end=None):
    with wave.open(str(source), 'rb') as w:
        channels, rate, count = w.getnchannels(), w.getframerate(), w.getnframes()
        if w.getsampwidth() != 2 or w.getcomptype() != 'NONE' or not 1 <= channels <= 8 or rate <= 0:
            raise ValueError('Decoder must produce PCM16 WAV')
        raw = w.readframes(count)
    if not count or len(raw) != count * channels * 2:
        raise ValueError('Empty or truncated decoded voice')
    pcm = array.array('h')
    pcm.frombytes(raw)
    if sys.byteorder != 'little':
        pcm.byteswap()
    mono = pcm if channels == 1 else array.array('h', (
        sum(pcm[i*channels:(i+1)*channels]) // channels for i in range(count)))
    target_count = max(1, (count * 22050 + rate // 2) // rate)
    end = target_count if end is None else end
    if not 0 <= start < end <= target_count:
        raise ValueError('Voice segment lies outside decoded material')
    result = array.array('h')
    for j in range(start, end):
        point = j * rate
        left, fraction = min(point // 22050, count - 1), point % 22050
        right = min(left + 1, count - 1)
        result.append((mono[left]*(22050-fraction) + mono[right]*fraction) // 22050)
    if sys.byteorder != 'little':
        result.byteswap()
    with wave.open(str(dest), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(result.tobytes())
    return count, rate, end-start


def verify_bcstm(path, expected_samples):
    b = Path(path).read_bytes()
    if len(b) < 288 or b[:4] != b'CSTM':
        raise ValueError('Invalid BCSTM header')
    if struct.unpack_from('<HHIIHH', b, 4) != (0xfeff, 64, 0x02030100, len(b), 2, 0):
        raise ValueError('Invalid BCSTM size/version')
    if struct.unpack_from('<HHII', b, 20) != (0x4000, 0, 64, 192):
        raise ValueError('BCSTM INFO reference changed')
    if struct.unpack_from('<HHII', b, 32) != (0x4002, 0, 256, len(b)-256):
        raise ValueError('BCSTM DATA reference changed')
    if b[64:68] != b'INFO' or b[256:260] != b'DATA' or b[96:100] != bytes((1, 0, 1, 0)):
        raise ValueError('BCSTM is not non-looping mono PCM16')
    values = struct.unpack_from('<11I', b, 100)
    rate, loop, samples, blocks, block_bytes, block_samples, last_bytes, last_samples, last_padded, _, _ = values
    if rate != 22050 or loop != 0 or samples != expected_samples or block_bytes != 8192 or block_samples != 4096:
        raise ValueError('BCSTM playback profile changed')
    if blocks != (samples+4095)//4096 or last_samples != samples-(blocks-1)*4096:
        raise ValueError('BCSTM block count mismatch')
    if last_bytes != last_samples*2 or last_padded != (last_bytes+31)//32*32:
        raise ValueError('BCSTM final block mismatch')
    if len(b) != 288+(blocks-1)*8192+last_padded:
        raise ValueError('BCSTM payload length mismatch')
    return samples


def inspect_voices(source, jobs):
    grouped = collections.defaultdict(list)
    for job in jobs:
        grouped[(job['bank_chunk'], job['bank_path'])].append(job)
    problems = []
    validated = 0
    for index, ((chunk, relative), members) in enumerate(grouped.items()):
        try:
            path = safe(source, chunk+'/'+relative)
            _, bank = sab_reader.embedded(path.read_bytes())
            parsed = sab_reader.read(bank)
        except (ValueError, OSError) as error:
            problems.append(dict(bank_chunk=chunk, bank_path=relative,
                                 jobs=[j['index'] for j in members], scope='bank', reason=str(error)))
        else:
            # An absent alias blocks its own clip, not every other reference
            # in the same bank. Never compensate by guessing a subsong.
            for job in members:
                try:
                    select_stream(parsed, job)
                    if job['language'] != 'en':
                        raise ValueError('English Voice_NE source absent; language cannot be inferred from a bank filename')
                    validated += 1
                except ValueError as error:
                    problems.append(dict(bank_chunk=chunk, bank_path=relative,
                                         jobs=[job['index']], asset=job['asset'], scope='clip', reason=str(error)))
        if (index+1) % 25 == 0 or index+1 == len(grouped):
            print('Voice-bank inspection: %d/%d' % (index+1, len(grouped)), flush=True)
    return dict(required_clips=len(jobs), required_banks=len(grouped),
                structurally_validated_clips=validated, source_hash_check=False,
                problems=problems, complete=not problems)


def convert_voices(source, output, decoder, jobs, inspection):
    blocked = {i for p in inspection['problems'] for i in p['jobs']}
    grouped = collections.defaultdict(list)
    for job in jobs:
        if job['index'] not in blocked:
            grouped[(job['bank_chunk'], job['bank_path'])].append(job)
    files = []
    with tempfile.TemporaryDirectory(prefix='dqxi-voice-') as temp:
        temp = Path(temp)
        sab, decoded, normalized = (temp/n for n in ('bank.sab', 'decoded.wav', 'normalized.wav'))
        for (chunk, relative), members in grouped.items():
            _, bank = sab_reader.embedded(safe(source, chunk+'/'+relative).read_bytes())
            parsed = sab_reader.read(bank)
            sab.write_bytes(bank)
            previous_subsong = None
            for job in members:
                stream = select_stream(parsed, job)
                if stream['subsong'] != previous_subsong:
                    decoded.unlink(missing_ok=True)
                    result = subprocess.run([str(decoder), '-i', '-s', str(stream['subsong']),
                                             '-o', str(decoded), str(sab)],
                                            capture_output=True, text=True, errors='replace')
                    if result.returncode or not decoded.is_file():
                        raise ValueError('Decoder failed for '+job['asset']+': '+result.stderr[-1200:])
                    previous_subsong = stream['subsong']
                count, rate, samples = normalize_wav(decoded, normalized,
                    job.get('segment_start_sample_22050', 0), job.get('segment_end_sample_22050'))
                if rate != job['sample_rate'] or abs(count-job['samples']) > 1:
                    raise ValueError('Decoded duration differs from voice reference')
                target = safe(output, 'sound/'+job['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix('.partial')
                temporary.unlink(missing_ok=True)
                convert(normalized, temporary)
                verify_bcstm(temporary, samples)
                os.replace(temporary, target)
                files.append(dict(index=job['index'], sound_id=job['sound_id'], path='sound/'+job['path'],
                                  samples=samples, sample_rate=22050, decoder_subsong=stream['subsong']))
                if len(files) % 25 == 0:
                    print('Converted voices: %d/%d' % (len(files), len(jobs)), flush=True)
    return dict(required=len(jobs), converted=len(files), missing_indices=sorted(blocked),
                complete=len(files)==len(jobs), files=files)


def export_texts(source, output, tables):
    report = dict(required_tables=len(tables)*2, parsed_tables=0, rows=0,
                  layout_ready_rows=0, layout_unresolved_rows=0, problems=[], tables=[])
    for table in tables:
        for language, field in (('en', 'english'), ('ja', 'japanese')):
            profile = None
            layout_problems = {}
            try:
                path = safe(source, table['chunk']+'/'+table[field])
                package = ue4_voice_reader.Package.from_path(path)
                profile = textserifu_reader.describe(package)
                parsed = textserifu_reader.read(package)
                # Keep exact source-row anchors so a later build stage can
                # verify a PC translation against this user's extracted PAK.
                # The JSON is generated locally and is not part of the release.
                source_path = (table['chunk']+'/'+table[field]).replace('\\', '/')
                rows = [dict(source=source_path, index=r['index'], offset=r['offset'],
                             size=r['size'], row_sha256=r['row_sha256'],
                             label=r['label'], **r['fields']) for r in parsed['rows']]
                if language == 'en':
                    for row in rows:
                        try:
                            row['dialog_layout'] = dialog_layout.from_pc(row['Text'])
                            report['layout_ready_rows'] += 1
                        except ValueError as error:
                            row['dialog_layout_unresolved'] = str(error)
                            report['layout_unresolved_rows'] += 1
                            problem = layout_problems.setdefault(str(error), dict(count=0, example_labels=[]))
                            problem['count'] += 1
                            if len(problem['example_labels']) < 5:
                                problem['example_labels'].append(row['label'])
                        row['menu_label'] = dialog_layout.menu_label(row['Text'])
                dest = safe(output, 'pc-text/'+language+'/'+table['name']+'.json')
                write_json(dest, dict(schema=parsed['schema'], rows=rows))
                report['tables'].append(dict(name=table['name'], language=language, rows=len(rows),
                                            profile=profile, layout_problems=layout_problems))
                report['rows'] += len(rows)
                report['parsed_tables'] += 1
            except (ValueError, OSError) as error:
                report['problems'].append(dict(name=table['name'], language=language, reason=str(error),
                    chunk=table['chunk'], uasset=table[field],
                    uexp=str(Path(table[field]).with_suffix('.uexp')).replace('\\', '/'), profile=profile))
            # A later failure must not erase the diagnostics for earlier tables.
            write_json(output/'text-progress-report.json', report)
    report['complete'] = not report['problems']
    report['layout_complete'] = report['complete'] and not report['layout_unresolved_rows']
    write_json(output/'text-progress-report.json', report)
    return report


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--source', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--decoder', type=Path)
    a.add_argument('--convert-voices', action='store_true')
    a.add_argument('--recipes', type=Path, default=RECIPES)
    a.add_argument('--extraction-report', type=Path)
    a.add_argument('--asset-manifest', type=Path)
    a.add_argument('--pc-root', type=Path)
    a.add_argument('--romfs', type=Path)
    args = a.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents or output in source.parents:
        a.error('Input and output directories overlap')
    if bool(args.pc_root) != bool(args.romfs):
        a.error('--pc-root and --romfs must be supplied together')
    reused = None
    if args.extraction_report:
        reused = pc_source_inventory.validate_extraction(source, args.extraction_report)
    manifest = read_json(args.asset_manifest) if args.asset_manifest else None
    output.mkdir(parents=True, exist_ok=False)
    films = None
    if args.pc_root:
        films = pc_source_inventory.movie_inventory(args.pc_root, args.romfs)
        write_json(output/'movie-sources-report.json', films)
    jobs = read_json(args.recipes/'voice_jobs.json')['jobs']
    tables = read_json(args.recipes/'text_tables.json')['tables']
    text_report = export_texts(source, output, tables)
    voice_report = inspect_voices(source, jobs)
    supplemental_voice_report = None
    scene_event_report = None
    if manifest:
        supplemental_voice_report = pc_scene_events.inspect_supplemental_voice_banks(source, output, manifest)
        scene_event_report = pc_scene_events.export_scene_events(source, output, manifest)
    report = dict(schema_version=1, component_conversion=True, source_hash_check=False,
        texts=text_report, voices=voice_report, mod_generated=False, cia_generated=False,
        full_build_ready=False, pending=['Complete typed PC-to-3DS field translation',
            'Current native voice/code patch integration', 'English USM-to-MOFLEX movie conversion',
            'Azahar and physical 3DS runtime validation'])
    if reused:
        report['reused_extraction'] = reused
    if films is not None:
        report['movies'] = films
    if supplemental_voice_report is not None:
        report['supplemental_voice_inventory'] = supplemental_voice_report
    if scene_event_report is not None:
        report['scene_events'] = scene_event_report
    write_json(output/'component-report.json', report)
    if args.convert_voices:
        if not args.decoder or not args.decoder.is_file():
            raise ValueError('Automatic decoder installation did not provide vgmstream-cli')
        report['voice_conversion'] = convert_voices(source, output/'voice-components', args.decoder, jobs, voice_report)
        write_json(output/'component-report.json', report)
    print('PC components prepared; this is not a complete playable mod.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
