"""Create the ten native MOFLEX slots from the user's PC USM movies.

The source videos and English voice banks are read from the selected Steam
installation and extracted PC assets. No movie payload is bundled here.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
import wave

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pc_components
import sab_reader
from build_storage import plain_path


FPS_NUM, FPS_DEN = 359, 12
RATE = 48000
EXCLUDE_CAPTION_IDS = set()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe(root, relative):
    root = Path(root).resolve()
    relative = str(relative).replace('\\', '/')
    if relative.startswith('/') or ':' in relative or '..' in relative.split('/'):
        raise ValueError('Unsafe source path: ' + relative)
    result = root.joinpath(*relative.split('/')).resolve()
    if root not in result.parents:
        raise ValueError('Source path escapes its root: ' + relative)
    return result


def run(command, label, log_path=None, progress_frames=None):
    command = [str(x) for x in command]
    if progress_frames is None:
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors='replace')
    else:
        # FFmpeg's progress protocol is line-oriented. Merge its informational
        # log with the progress stream so a slow encode never looks idle in the
        # installer, and keep an on-disk copy while the process is running.
        log_path = Path(log_path) if log_path is not None else None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        log = log_path.open('a', encoding='utf-8', errors='replace') if log_path else None
        process = None
        if log:
            log.write('\n=== ' + label + ' ===\n')
            log.write('COMMAND: ' + json.dumps(command, ensure_ascii=False) + '\n')
            log.flush()
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors='replace', bufsize=1)
            last_frame = None
            for line in process.stdout:
                lines.append(line)
                if log:
                    log.write(line)
                    log.flush()
                match = re.match(r'^frame=(\d+)\s*$', line.strip())
                if match:
                    frame = int(match.group(1))
                    if frame != last_frame:
                        percent = min(100, int(frame * 100 / max(1, progress_frames)))
                        print('%s: %d/%d frames (%d%%)' %
                              (label, frame, progress_frames, percent), flush=True)
                        last_frame = frame
            returncode = process.wait()
        finally:
            if log:
                exit_code = process.returncode if process is not None and process.poll() is not None else 'unknown'
                log.write('EXIT CODE: ' + str(exit_code) + '\n')
                log.close()
        result = subprocess.CompletedProcess(command, returncode, ''.join(lines), '')

    if log_path is not None and progress_frames is None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8', errors='replace') as log:
            log.write('\n=== ' + label + ' ===\n')
            log.write('COMMAND: ' + json.dumps(command, ensure_ascii=False) + '\n')
            log.write('EXIT CODE: ' + str(result.returncode) + '\n')
            if result.stdout:
                log.write('--- stdout ---\n' + result.stdout + '\n')
            if result.stderr:
                log.write('--- stderr ---\n' + result.stderr + '\n')
    if result.returncode:
        detail = (result.stderr or result.stdout)[-2400:]
        suffix = ('\nFull diagnostic log: ' + str(log_path)) if log_path is not None else ''
        raise RuntimeError(label + ' failed (' + str(result.returncode) + '):\n' + detail + suffix)
    return result


def duration_for(frames):
    return frames * FPS_DEN / FPS_NUM


def event_rows(scene_report, scene_name, skip_caption_ids=()):
    maps = scene_report.get('maps', [])
    candidates = [m for m in maps if Path(m.get('path', '')).name.casefold() == scene_name.casefold()]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one parsed PC event map: ' + scene_name)
    source = candidates[0]
    events = []
    for kind in ('sound_tracks', 'caption_tracks'):
        for track in source.get('tracks', {}).get(kind, []):
            flags = track.get('scalar_fields', {})
            if flags.get('EnableByEn') is False:
                continue
            if kind == 'caption_tracks' and flags.get('EnableByJp') is not False:
                raise ValueError('English captions are not isolated from Japanese captions: ' + scene_name)
            for row in track.get('rows', []):
                fields = row.get('fields', {})
                if kind == 'caption_tracks' and fields.get('bCloseFlag'):
                    continue
                if kind == 'sound_tracks':
                    path = fields.get('AssetPathName')
                    if not isinstance(path, str) or not path:
                        raise ValueError('Movie sound row has no asset path: ' + scene_name)
                    asset = path.rsplit('.', 1)[-1].removeprefix('SWAV_')
                    when = fields.get('Time')
                    volume = fields.get('Volume', 1.0)
                    if fields.get('Pitch', 1.0) != 1.0:
                        raise ValueError('A movie voice event uses a non-native pitch: ' + asset)
                else:
                    asset = str(fields.get('TextID', '')).lstrip(':')
                    when = fields.get('TimeVar')
                    volume = 1.0
                    if asset in skip_caption_ids:
                        continue
                if not asset or not isinstance(when, (int, float)) or when < 0:
                    raise ValueError('Invalid English movie voice event in ' + scene_name)
                if not math.isfinite(float(when)) or not math.isfinite(float(volume)):
                    raise ValueError('Non-finite English movie voice event in ' + scene_name)
                events.append({'asset': asset, 'time': float(when), 'volume': float(volume),
                               'kind': kind, 'track': flags.get('TrackTitle', '')})
    return sorted(events, key=lambda row: (row['time'], row['asset']))


def decode_bank(decoder, sab_path, subsong, output, profile=None, log_path=None):
    output = Path(output)
    output.unlink(missing_ok=True)
    run([decoder, '-i', '-s', str(subsong), '-o', output, sab_path],
        'English voice decode for subsong ' + str(subsong), log_path=log_path)
    if not output.is_file() or output.stat().st_size < 48:
        raise ValueError('Voice decoder did not produce a WAV file.')
    with wave.open(str(output), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getnframes() < 1:
            raise ValueError('Voice decoder output is not non-empty PCM16 WAV.')
        if profile is not None:
            expected = (profile['samples'], profile['sample_rate'], profile['channels'])
            measured = (wav.getnframes(), wav.getframerate(), wav.getnchannels())
            if measured != expected:
                raise ValueError('Decoded movie voice profile differs from its PC bank: '
                                 '%s; expected %s.' % (measured, expected))


def wave_profile(path):
    with wave.open(str(path), 'rb') as wav:
        if wav.getnframes() < 1 or wav.getframerate() <= 0:
            raise ValueError('Empty movie voice asset: ' + Path(path).name)
        return wav.getnframes(), wav.getframerate()


def wave_is_silent(path):
    with wave.open(str(path), 'rb') as wav:
        while True:
            data = wav.readframes(65536)
            if not data:
                return True
            if any(data):
                return False


def movie_voice_jobs(references, jobs):
    """Resolve referenced movie assets to their complete PC source streams.

    The game dialogue recipes can contain several sliced jobs for one asset.
    Movie event maps refer to the original asset, so those slices are not
    separate movie voices. Ignore unreferenced recipe collisions and collapse
    referenced slices only when they point at the same underlying stream.
    """
    source_fields = ('bank_chunk', 'bank_path', 'subsong', 'material_index',
                     'samples', 'sample_rate', 'channels', 'codec')
    grouped = {}
    for job in jobs:
        asset = str(job['asset']).lstrip(':')
        if asset in references:
            grouped.setdefault(asset, []).append(job)

    resolved = {}
    for asset, matches in grouped.items():
        profiles = {}
        for job in matches:
            profile = tuple(job.get(field) for field in source_fields)
            profiles.setdefault(profile, job)
        if len(profiles) != 1:
            raise ValueError('Ambiguous PC voice job asset: ' + asset)
        job = dict(next(iter(profiles.values())))
        # A movie event names the full PC asset. Segmentation in the game
        # dialogue recipe only aligns text/runtime links and must not truncate
        # the source voice used for the movie mix.
        job['segment_start_sample_22050'] = 0
        job['segment_end_sample_22050'] = None
        resolved[asset] = job
    return resolved


def index_movie_voices(references, extracted_root, jobs_path, asset_manifest_path):
    """Find complete movie streams in both regular and supplemental PC banks."""
    jobs = read_json(jobs_path)['jobs']
    jobs_by_asset = movie_voice_jobs(references, jobs)
    indexed, bank_data, bank_metadata = {}, {}, {}
    main_jobs = [jobs_by_asset[name] for name in sorted(references & set(jobs_by_asset))]
    grouped = {}
    for job in main_jobs:
        grouped.setdefault((job['bank_chunk'], job['bank_path']), []).append(job)
    for (chunk, bank_relative), bank_jobs in sorted(grouped.items()):
        raw_bank = safe(extracted_root, chunk + '/' + bank_relative).read_bytes()
        _, sab = sab_reader.embedded(raw_bank)
        parsed = sab_reader.read(sab)
        key = (chunk, bank_relative)
        bank_data[key], bank_metadata[key] = sab, parsed
        for job in bank_jobs:
            stream = pc_components.select_stream(parsed, job)
            name = str(job['asset']).lstrip(':')
            indexed[name] = dict(stream, bank_chunk=chunk, bank_path=bank_relative,
                                 bank_sha256=hashlib.sha256(sab).hexdigest())

    remaining = references - set(indexed)
    if remaining:
        manifest = read_json(asset_manifest_path)
        pairs = {}
        for item in manifest.get('assets', []):
            # Movie-only aliases also live in regular gameplay voice banks.
            # The voice-job recipe names only their gameplay dialogue clips.
            if item.get('kind') not in ('voice', 'voice_extra') or Path(item['path']).suffix.lower() != '.uexp':
                continue
            key = (item['chunk'], item['path'])
            pairs[key] = item
        extra_index = {}
        print('Checking %d regular and supplemental PC voice banks for %d movie assets...' %
              (len(pairs), len(remaining)), flush=True)
        for bank_number, (chunk, relative) in enumerate(sorted(pairs), 1):
            key = (chunk, relative)
            if key in bank_metadata:
                sab, parsed = bank_data[key], bank_metadata[key]
            else:
                raw = safe(extracted_root, chunk + '/' + relative).read_bytes()
                _, sab = sab_reader.embedded(raw)
                parsed = sab_reader.read(sab)
            for stream in parsed['streams']:
                for asset in stream['assets']:
                    if asset not in remaining:
                        continue
                    candidate = dict(stream, bank_chunk=chunk, bank_path=relative,
                                     bank_sha256=hashlib.sha256(sab).hexdigest())
                    if asset in extra_index:
                        previous = extra_index[asset]
                        if (previous['bank_sha256'], previous['subsong']) != \
                                (candidate['bank_sha256'], candidate['subsong']):
                            raise ValueError('Ambiguous English movie voice asset: %s (%s; %s)' %
                                             (asset, previous['bank_path'], relative))
                        continue
                    extra_index[asset] = candidate
                    bank_data[key] = sab
            if bank_number % 50 == 0 or bank_number == len(pairs):
                print('PC movie voice bank check: %d/%d' % (bank_number, len(pairs)), flush=True)
        if remaining - set(extra_index):
            missing = ', '.join(sorted(remaining-set(extra_index))[:25])
            raise ValueError('English movie voice assets were not found in the selected PC files: ' + missing)
        indexed.update(extra_index)
    return indexed, bank_data


def resolve_movie_voices(events, extracted_root, decoder, jobs_path, asset_manifest_path, work,
                         source_report_path=None):
    """Decode each full PC movie voice stream once, preserving its native PCM."""
    references = {event['asset'] for event in events}
    indexed, bank_data = index_movie_voices(references, extracted_root, jobs_path, asset_manifest_path)
    fields = ('bank_chunk', 'bank_path', 'bank_sha256', 'subsong', 'material_index',
              'samples', 'sample_rate', 'channels', 'codec')
    report = dict(voice_index_complete=True, decoded=False, voice_count=len(indexed),
                  bank_count=len(bank_data),
                  sources=[dict(asset=asset, **{k: row.get(k) for k in fields})
                           for asset, row in sorted(indexed.items())])
    log_path = None
    if source_report_path is not None:
        source_report_path = Path(source_report_path)
        source_report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        log_path = source_report_path.parent/'movie-voice-decode.log'
    bank_files, bank_numbers = {}, {}
    for bank_number, (key, sab) in enumerate(sorted(bank_data.items())):
        bank_file = work / ('movie-bank-%03d.sab' % bank_number)
        bank_file.write_bytes(sab)
        bank_files[key], bank_numbers[key] = bank_file, bank_number
    resolved, decoded = {}, {}
    for asset, stream in sorted(indexed.items()):
        key = (stream['bank_chunk'], stream['bank_path'])
        stream_key = (key, stream['subsong'])
        if stream_key not in decoded:
            output = work / ('movie-voice-%03d-%05d.wav' %
                             (bank_numbers[key], stream['subsong']))
            decode_bank(decoder, bank_files[key], stream['subsong'], output,
                        profile=stream, log_path=log_path)
            decoded[stream_key] = output
            print('Decoded PC movie voice streams: %d' % len(decoded), flush=True)
        resolved[asset] = decoded[stream_key]
    silent = {name for name, path in resolved.items() if wave_is_silent(path)}
    if source_report_path is not None:
        report.update(decoded=True, decoded_streams=len(decoded), silent_assets=sorted(silent))
        source_report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return resolved, silent


def create_mixed_audio(ffmpeg, base_tracks, events, voice_paths, silent, output,
                       duration, atempo=None):
    inputs = list(base_tracks)
    active_events = [event for event in events if event['asset'] not in silent]
    inputs.extend(voice_paths[event['asset']] for event in active_events)
    filters = []
    tags = []
    for i in range(len(base_tracks)):
        tempo = ('atempo=%.12f,' % atempo) if atempo else ''
        filters.append('[%d:a:0]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,%s'
                       'apad=pad_dur=1,atrim=duration=%.9f,asetpts=PTS-STARTPTS[b%d]' %
                       (i, RATE, tempo, duration, i))
        tags.append('[b%d]' % i)
    base_count = len(base_tracks)
    for index, event in enumerate(active_events):
        input_index = base_count + index
        start_samples = round(event['time'] * RATE)
        filters.append('[%d:a:0]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                       'volume=%.9f,adelay=%dS:all=1,apad=pad_dur=1,atrim=duration=%.9f,'
                       'asetpts=PTS-STARTPTS[v%d]' %
                       (input_index, RATE, event['volume'], start_samples, duration, index))
        tags.append('[v%d]' % index)
    if not tags:
        raise ValueError('No movie audio tracks were selected.')
    filters.append(''.join(tags) + 'amix=inputs=%d:duration=longest:dropout_transition=0:normalize=0,'
                   'alimiter=limit=0.97,atrim=duration=%.9f[aout]' % (len(tags), duration))
    graph = ';\n'.join(filters)
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y']
    for path in inputs:
        command.extend(['-i', path])
    command.extend(['-filter_complex', graph, '-map', '[aout]', '-t', '%.9f' % duration,
                    '-ar', str(RATE), '-ac', '2', '-c:a', 'pcm_s16le', output])
    run(command, 'English movie audio mix')
    return len(active_events)


def encode_moflex(ffmpeg, ffprobe, inputs, filters, maps, destination, frames, duration,
                  log_path=None, failure_log_path=None):
    """Encode MOFLEX and verify every output frame with the bundled FFmpeg decoder."""
    destination = Path(destination)
    destination.unlink(missing_ok=True)
    command = [ffmpeg, '-hide_banner', '-v', 'info', '-progress', 'pipe:1',
               '-stats_period', '5', '-nostats', '-y']
    command.extend(inputs)
    command.extend(filters)
    for stream in maps:
        command.extend(['-map', stream])
    # The exact duration and filter frame map bound video; decoded frame count
    # is checked below. A separate -frames:v limit stops the muxer before the
    # final audio packets on some FFmpeg builds, clipping the end of the mix.
    command.extend(['-t', '%.9f' % duration,
         '-c:v', 'mobiclip', '-mobiclip', '1', '-moflex', '1', '-pix_fmt', 'yuv420p',
         '-threads:v', '1', '-qp', '20', '-g', '90', '-c:a', 'pcm_s16le', '-mo_audio', 'adpcm',
         '-ar', str(RATE), '-ac', '2', '-flush_packets', '1', '-f', 'moflex', destination])
    try:
        run(command, 'MOFLEX encoding', log_path=log_path, progress_frames=frames)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ValueError('MOFLEX encoder exited successfully but produced a zero-byte output file.')
        profile = json.loads(run([ffprobe, '-v', 'error', '-show_streams',
                                  '-of', 'json', destination], 'MOFLEX stream readback',
                                 log_path=log_path).stdout)
        video = [row for row in profile.get('streams', []) if row.get('codec_type') == 'video']
        audio = [row for row in profile.get('streams', []) if row.get('codec_type') == 'audio']
        if len(video) != 1 or video[0].get('codec_name') != 'mobiclip' or \
                (video[0].get('width'), video[0].get('height')) != (400, 224):
            raise ValueError('MOFLEX video stream failed codec or dimension readback.')
        if len(audio) != 1 or audio[0].get('codec_name') != 'adpcm_ima_moflex' or \
                int(audio[0].get('sample_rate', 0)) != RATE:
            raise ValueError('MOFLEX audio stream failed codec or sample-rate readback.')
        # This is a real decode pass, using the same FFmpeg/Mobiclip decoder
        # used for the earlier successful MOFLEX probe.  ffprobe packet counts
        # alone can accept a file whose MobiClip packets do not decode.
        decoded = run([ffmpeg, '-hide_banner', '-v', 'error', '-xerror',
                       '-i', destination, '-map', '0:v:0', '-map', '0:a:0',
                       '-fps_mode', 'passthrough', '-progress', 'pipe:1',
                       '-stats_period', '5', '-nostats', '-f', 'null', '-'],
                      'MOFLEX full decode', log_path=log_path, progress_frames=frames)
        frame_counts = re.findall(r'(?m)^frame=(\d+)\s*$', decoded.stdout)
        if not frame_counts or int(frame_counts[-1]) != frames:
            found = frame_counts[-1] if frame_counts else 'unknown'
            raise ValueError('MOFLEX decoder read %s video frames; expected %d.' % (found, frames))
    except Exception as error:
        destination.unlink(missing_ok=True)
        if log_path is not None and failure_log_path is not None and Path(log_path).is_file():
            failure_log_path = Path(failure_log_path)
            failure_log_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(log_path, failure_log_path)
            raise RuntimeError(str(error) + '\nMOFLEX diagnostic log: ' + str(failure_log_path)) from error
        raise


def validate_movie_voice_timing(number, events, voices, silent, duration):
    for event in events:
        if event['asset'] in silent:
            continue
        samples, rate = wave_profile(voices[event['asset']])
        if event['time'] + samples / rate > duration + (FPS_DEN / FPS_NUM):
            raise ValueError('English voice event extends past MOVIE_%03d: %s' %
                             (number, event['asset']))


def convert_direct_movie(row, movie_by_number, scene_report, extracted_root, decoder,
                         ffmpeg, ffprobe, jobs_path, asset_manifest_path, work, output_dir,
                         width, height, voice_cache=None, source_hash=None):
    number = row['number']
    source = safe(movie_by_number, row['source'])
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError('Required PC movie is missing: ' + str(source))
    frames = row['frames']
    duration = duration_for(frames)
    events = event_rows(scene_report, row['scene_map'], row.get('skip_caption_ids', [])) if row['scene_map'] else []
    if events:
        voices, silent = voice_cache if voice_cache is not None else resolve_movie_voices(
            events, extracted_root, decoder, jobs_path, asset_manifest_path, work)
        silent = silent & {event['asset'] for event in events}
    else:
        voices, silent = {}, set()
    validate_movie_voice_timing(number, events, voices, silent, duration)
    movie_work = work / ('movie-%03d' % number)
    movie_work.mkdir(exist_ok=True)
    base_tracks = []
    # The retimed title uses the complete PC edit. Do not first truncate its
    # background audio to the shorter native duration before applying atempo.
    source_audio_duration = row['pc_seconds'] if row.get('retime') else duration
    for index in (2, 3):
        track = movie_work / ('track-%d.wav' % index)
        run([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', source,
             '-map', '0:a:%d' % index, '-vn', '-t', '%.9f' % source_audio_duration,
             '-ar', str(RATE), '-ac', '2', '-c:a', 'pcm_s16le', track],
            'PC USM audio track extraction')
        if not track.is_file() or track.stat().st_size < 48:
            raise ValueError('PC movie audio track %d is empty: MOVIE_%03d' % (index, number))
        base_tracks.append(track)
    scale = duration / row['pc_seconds'] if row.get('retime') else None
    active_count = create_mixed_audio(ffmpeg, base_tracks, events, voices, silent,
                                      movie_work/'english-mix.wav', duration, scale and 1.0/scale)
    vf = 'scale=%d:%d:flags=lanczos,' % (width, height)
    if scale:
        vf += 'setpts=PTS*%.12f,' % scale
    vf += 'fps=%d/%d,tpad=stop_mode=clone:stop_duration=1' % (FPS_NUM, FPS_DEN)
    target = output_dir / ('MOVIE_%03d.moflex' % number)
    encode_moflex(ffmpeg, ffprobe,
        ['-i', source, '-i', movie_work/'english-mix.wav'], ['-vf', vf],
        ['0:v:0', '1:a:0'], target, frames, duration,
        movie_work/'moflex-encode-decode.log',
        output_dir.parents[2]/(target.stem+'-encode-failure.log'))
    return dict(name=target.name, frames=frames, fps='%d/%d' % (FPS_NUM, FPS_DEN),
                seconds=duration, bytes=target.stat().st_size, sha256=sha256(target),
                source=row['source'].replace('\\', '/'), source_sha256=source_hash or sha256(source),
                source_bytes=source.stat().st_size, event_count=len(events),
                mixed_voice_events=active_count, silent_voice_assets_skipped=len(silent),
                scene_map=row.get('scene_map'), retimed=bool(row.get('retime')),
                width=width, height=height, stream_readback_verified=True,
                decoded_frames_verified=frames,
                sources_user_supplied=True)


def retrospective_segments(number, games, expected_frames):
    """Validate the edit before encoding and return its exact native frame map."""
    if type(expected_frames) is not int or expected_frames <= 0 or not games:
        raise ValueError('Invalid retrospective frame count: MOVIE_%03d.' % number)
    segment_rows = []
    out_frame = 0
    for game, title_at, title_frames, action_at, action_frames in games:
        for kind, start_sec, frames in (('title', title_at, title_frames),
                                       ('action', action_at, action_frames)):
            if (type(frames) is not int or frames <= 0 or
                    not isinstance(start_sec, (int, float)) or
                    not math.isfinite(start_sec) or start_sec < 0):
                raise ValueError('Invalid retrospective segment: MOVIE_%03d.' % number)
            start_frame = round(start_sec * FPS_NUM / FPS_DEN)
            if segment_rows and start_frame < segment_rows[-1]['start_frame'] + segment_rows[-1]['frames']:
                raise ValueError('Overlapping or unordered retrospective cuts: MOVIE_%03d.' % number)
            segment_rows.append(dict(game=game, kind=kind, start_frame=start_frame,
                                     frames=frames, output_start_frame=out_frame))
            out_frame += frames
    if out_frame != expected_frames:
        raise ValueError('Retrospective edit frame map failed validation: MOVIE_%03d has %d frames; expected %d.' %
                         (number, out_frame, expected_frames))
    return segment_rows


def convert_retrospective(number, plan, source, ffmpeg, ffprobe, work, output_dir,
                          width, height, suffix_start, expected_frames, source_hash=None):
    segment_rows = retrospective_segments(number, plan[str(number)], expected_frames)
    frames = expected_frames
    duration = duration_for(frames)
    movie_work = work / ('movie-%03d' % number)
    movie_work.mkdir(exist_ok=True)
    cuts = len(segment_rows)
    filters = []
    frame_expr = '+'.join('between(n,%d,%d)' %
                          (s['start_frame'], s['start_frame']+s['frames']-1)
                          for s in segment_rows)
    filters.append('[0:v:0]fps=%d/%d,trim=start=%.9f,setpts=PTS-STARTPTS,'
                   'select=\'%s\',setpts=N*%d/%d/TB,scale=%d:%d:flags=lanczos,format=yuv420p[vout]' %
                   (FPS_NUM, FPS_DEN, suffix_start, frame_expr, FPS_DEN, FPS_NUM, width, height))
    audio_inputs = ''.join('[a%d]' % i for i in range(cuts))
    filters.append('[0:a:3]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                   'asplit=%d%s' % (RATE, cuts, audio_inputs))
    for i, segment in enumerate(segment_rows):
        start = suffix_start + segment['start_frame'] * FPS_DEN / FPS_NUM
        segment_duration = duration_for(segment['frames'])
        fade_out = max(0, segment_duration - 0.005)
        filters.append('[a%d]atrim=start=%.9f:duration=%.9f,asetpts=PTS-STARTPTS,'
                       'afade=t=in:st=0:d=0.005,afade=t=out:st=%.9f:d=0.005[s%d]' %
                       (i, start, segment_duration, fade_out, i))
    concat_inputs = ''.join('[s%d]' % i for i in range(cuts))
    filters.append('%sconcat=n=%d:v=0:a=1,apad=pad_dur=1,atrim=duration=%.9f,'
                   'alimiter=limit=0.97[aout]' % (concat_inputs, cuts, duration))
    graph = ';\n'.join(filters)
    target = output_dir / ('MOVIE_%03d.moflex' % number)
    encode_moflex(ffmpeg, ffprobe, ['-i', source],
        ['-filter_complex', graph], ['[vout]', '[aout]'],
        target, frames, duration, movie_work/'moflex-encode-decode.log',
        output_dir.parents[2]/(target.stem+'-encode-failure.log'))
    return dict(name=target.name, frames=frames, fps='%d/%d' % (FPS_NUM, FPS_DEN),
                seconds=duration, bytes=target.stat().st_size, sha256=sha256(target),
                source='Game/Content/Movies/C_300/CS_030/MT_Cs_C300030_C01x_E.usm',
                source_sha256=source_hash or sha256(source), source_bytes=source.stat().st_size,
                event_count=0, mixed_voice_events=0, silent_voice_assets_skipped=0,
                edit_segments=segment_rows, width=width, height=height,
                stream_readback_verified=True, decoded_frames_verified=frames,
                sources_user_supplied=True)


def verify_mobipeg(ffmpeg, ffprobe):
    encoders = run([ffmpeg, '-hide_banner', '-encoders'], 'Mobipeg encoder check').stdout
    muxers = run([ffmpeg, '-hide_banner', '-muxers'], 'Mobipeg muxer check').stdout
    demuxers = run([ffmpeg, '-hide_banner', '-demuxers'], 'Mobipeg USM demuxer check').stdout
    if (not re.search(r'\bmobiclip\b', encoders) or
            not re.search(r'\bmoflex\b', muxers) or
            not re.search(r'\busm\b', demuxers)):
        raise ValueError('The selected Mobipeg build lacks the required USM demuxer or MobiClip/MOFLEX support.')
    if not Path(ffprobe).is_file():
        raise FileNotFoundError('Mobipeg ffprobe.exe was not found.')


def pipeline_fingerprint(kind):
    """Invalidate only the slots affected by a converter code change."""
    common = {'run', 'duration_for', 'encode_moflex', 'sha256'}
    specific = ({'convert_direct_movie', 'create_mixed_audio', 'event_rows',
                 'validate_movie_voice_timing', 'wave_profile', 'wave_is_silent'}
                if kind == 'direct' else {'convert_retrospective', 'retrospective_segments'})
    source = Path(__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    definitions = [ast.dump(node, include_attributes=False) for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name in common | specific]
    return hashlib.sha256('\n'.join(definitions).encode()).hexdigest()


def movie_signature(kind, recipe, source_hash, events, voice_hashes, silent, tool_hashes, plan):
    payload = dict(pipeline=pipeline_fingerprint(kind), recipe=recipe,
                   source_sha256=source_hash, events=events,
                   voices={asset: voice_hashes[asset] for asset in sorted({e['asset'] for e in events} - silent)},
                   silent=sorted({e['asset'] for e in events} & silent), tools=tool_hashes,
                   fps=plan['fps'], width=plan['width'], height=plan['height'])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verified_movie(record, target, frames, width, height):
    """A checkpoint is usable only with the original successful decode evidence."""
    return (record.get('name') == target.name and record.get('frames') == frames and
            record.get('decoded_frames_verified') == frames and
            record.get('stream_readback_verified') is True and
            record.get('sources_user_supplied') is True and
            record.get('fps') == '%d/%d' % (FPS_NUM, FPS_DEN) and
            (record.get('width'), record.get('height')) == (width, height) and
            target.is_file() and target.stat().st_size > 0 and
            target.stat().st_size == record.get('bytes') and sha256(target) == record.get('sha256'))


def load_movie_checkpoint(receipt, target, signature, frames, width, height):
    try:
        data = read_json(receipt)
        record = data['record']
        if (data.get('schema_version') == 1 and data.get('input_sha256') == signature and
                verified_movie(record, target, frames, width, height)):
            return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def save_movie_checkpoint(receipt, record, signature, target, frames, width, height):
    if not verified_movie(record, target, frames, width, height):
        raise ValueError('Cannot save an unverified movie checkpoint: ' + target.name)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(dict(schema_version=1, input_sha256=signature,
                                         record=record), indent=2), encoding='utf-8')
    os.replace(temporary, receipt)


def release_movie_work(work, number, logs_root):
    """Keep the verified movie/receipt and its log, release obsolete mix WAVs."""
    movie_work = plain_path(work / ('movie-%03d' % number))
    if not movie_work.exists():
        return
    try:
        log = plain_path(movie_work/'moflex-encode-decode.log')
        if log.is_file():
            logs_root = plain_path(logs_root)
            logs_root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(log, logs_root/('MOVIE_%03d.log' % number))
        # Do not follow a link planted inside an intermediate directory.
        for path in movie_work.rglob('*'):
            plain_path(path)
        shutil.rmtree(movie_work)
    except (OSError, ValueError) as error:
        print('Movie work cleanup skipped: '+str(error), flush=True)


def build(pc_root, extracted_root, scene_events, output, decoder, ffmpeg, ffprobe,
          jobs_path, asset_manifest_path, plan_path, keep_intermediate=False):
    pc_root, extracted_root = Path(pc_root).resolve(), Path(extracted_root).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('movie_output_already_exists')
    if not pc_root.is_dir() or not extracted_root.is_dir():
        raise ValueError('missing_pc_install_or_extracted_pc_assets')
    plan = read_json(plan_path)
    rows = plan['movies']
    if len(rows) != 7 or {r['number'] for r in rows} != {1, 2, 3, 4, 5, 6, 10}:
        raise ValueError('invalid_pc_movie_manifest')
    if plan.get('fps') != '359/12' or (plan.get('width'), plan.get('height')) != (400, 224):
        raise ValueError('invalid_native_movie_profile')
    # The frame-count table belongs to the full manifest, not the nested
    # retrospective cut map. Check all three edits before the first long encode.
    for number in (7, 8, 9):
        retrospective_segments(number, plan['retrospectives'][str(number)],
                                plan['retrospective_frame_counts'][str(number)])
    verify_mobipeg(ffmpeg, ffprobe)
    scene_report = read_json(scene_events)
    if not scene_report.get('report', {}).get('complete'):
        raise ValueError('pc_scene_event_extraction_incomplete')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage_root = output.with_name(output.name+'.partial')
    stage = stage_root/'package'
    work = stage_root/'work'
    checkpoints = stage_root/'checkpoints'
    movies = stage/'movie'
    movies.mkdir(parents=True, exist_ok=True)
    work.mkdir(exist_ok=True)
    try:
        # Validate every voice bank and event before the first long encode.
        # The same decoded PC clips are shared by all ten movie slots.
        events_by_movie = {}
        all_events = []
        for row in rows:
            source = safe(pc_root, row['source'])
            if not source.is_file() or source.stat().st_size == 0:
                raise FileNotFoundError('Required PC movie is missing: ' + str(source))
            events = event_rows(scene_report, row['scene_map'], row.get('skip_caption_ids', [])) \
                if row['scene_map'] else []
            events_by_movie[row['number']] = events
            all_events.extend(events)
        print('Validating English voice sources for all movie scenes before encoding...', flush=True)
        voice_cache = resolve_movie_voices(all_events, extracted_root, decoder, jobs_path,
                                          asset_manifest_path, work,
                                          output.parent/'movie-source-checks.json')
        for row in rows:
            validate_movie_voice_timing(row['number'], events_by_movie[row['number']],
                                        voice_cache[0], voice_cache[1], duration_for(row['frames']))
        print('All movie voice sources and event timing validated.', flush=True)
        print('Checking source fingerprints and saved movie checkpoints...', flush=True)
        source_hashes = {row['number']: sha256(safe(pc_root, row['source'])) for row in rows}
        tool_hashes = {name: sha256(path) for name, path in (('ffmpeg', ffmpeg), ('ffprobe', ffprobe))}
        voice_hashes = {asset: sha256(path) for asset, path in voice_cache[0].items()
                        if asset not in voice_cache[1]}
        records = []
        for row in rows:
            name = 'MOVIE_%03d.moflex' % row['number']
            signature = movie_signature('direct', row, source_hashes[row['number']],
                                        events_by_movie[row['number']], voice_hashes,
                                        voice_cache[1], tool_hashes, plan)
            receipt, target = checkpoints/(name+'.json'), movies/name
            record = load_movie_checkpoint(receipt, target, signature, row['frames'], plan['width'], plan['height'])
            if record is None:
                print('Converting PC movie source for %s...' % name, flush=True)
                record = convert_direct_movie(row, pc_root, scene_report, extracted_root,
                    decoder, ffmpeg, ffprobe, jobs_path, asset_manifest_path, work, movies,
                    plan['width'], plan['height'], voice_cache=voice_cache,
                    source_hash=source_hashes[row['number']])
                save_movie_checkpoint(receipt, record, signature, target, row['frames'], plan['width'], plan['height'])
            else:
                print('Reusing fully decoded and checksum-verified %s.' % name, flush=True)
            records.append(record)
            if not keep_intermediate:
                release_movie_work(work, row['number'], output.parent/'movie-logs')
        source6 = safe(pc_root, next(r['source'] for r in rows if r['number'] == 6))
        if not source6.is_file():
            raise FileNotFoundError('The PC ending movie required for retrospective slots is missing.')
        for number in (7, 8, 9):
            name = 'MOVIE_%03d.moflex' % number
            frames = plan['retrospective_frame_counts'][str(number)]
            recipe = dict(cuts=plan['retrospectives'][str(number)], frames=frames,
                          suffix_start=plan['credits_suffix_start_seconds'])
            signature = movie_signature('retrospective', recipe, source_hashes[6], [],
                                        voice_hashes, voice_cache[1], tool_hashes, plan)
            receipt, target = checkpoints/(name+'.json'), movies/name
            record = load_movie_checkpoint(receipt, target, signature, frames, plan['width'], plan['height'])
            if record is None:
                print('Building PC ending retrospective %s...' % name, flush=True)
                record = convert_retrospective(number, plan['retrospectives'], source6,
                    ffmpeg, ffprobe, work, movies, plan['width'], plan['height'],
                    plan['credits_suffix_start_seconds'], frames, source_hash=source_hashes[6])
                save_movie_checkpoint(receipt, record, signature, target, frames, plan['width'], plan['height'])
            else:
                print('Reusing fully decoded and checksum-verified %s.' % name, flush=True)
            records.append(record)
            if not keep_intermediate:
                release_movie_work(work, number, output.parent/'movie-logs')
        records.sort(key=lambda row: row['name'])
        expected = ['MOVIE_%03d.moflex' % i for i in range(1, 11)]
        if [record['name'] for record in records] != expected:
            raise ValueError('generated_movie_set_incomplete')
        report = dict(schema_version=1, release='v18', installer_revision='2026-10-13-compact-storage', complete=True,
            source_kind='user-supplied DRAGON QUEST XI S PC USM movies and PC English voice assets',
            tool='Mobipeg v2.3 FFmpeg build', fps='%d/%d' % (FPS_NUM, FPS_DEN),
            movie_validation='full Mobipeg FFmpeg decode; decoded frame count checked',
            width=plan['width'], height=plan['height'], movie_count=len(records),
            files=records, movie_source_directory=str((pc_root/'Game/Content/Movies')))
        (stage/'movie-build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        os.replace(stage, output)
        if not keep_intermediate:
            shutil.rmtree(stage_root, ignore_errors=True)
        (output.parent/'movie-build-failure.log').unlink(missing_ok=True)
        return report
    except Exception:
        print('Movie checkpoints and diagnostics retained at: ' + str(stage_root), flush=True)
        raise


def write_movie_failure_log(output, error, traceback_text):
    """Save a full diagnostic log in the build root, including pre-encode failures."""
    output = Path(output).resolve()
    log_path = output.parent / 'movie-build-failure.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        'Movie build failed\n'
        'Reason: %s\n'
        'Requested output: %s\n\n'
        'Traceback:\n%s' % (error, output, traceback_text),
        encoding='utf-8', errors='replace')
    return log_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pc-root', type=Path, required=True)
    parser.add_argument('--extracted-root', type=Path, required=True)
    parser.add_argument('--scene-events', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--decoder', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--ffprobe', type=Path, required=True)
    parser.add_argument('--jobs', type=Path, default=HERE.parent/'recipes'/'voice_jobs.json')
    parser.add_argument('--asset-manifest', type=Path, default=HERE.parent/'pc_asset_manifest.json')
    parser.add_argument('--plan', type=Path, default=HERE.parent/'pc_movie_build_manifest.json')
    parser.add_argument('--keep-intermediate', action='store_true')
    args = parser.parse_args()
    try:
        report = build(args.pc_root, args.extracted_root, args.scene_events, args.output,
                       args.decoder, args.ffmpeg, args.ffprobe, args.jobs,
                       args.asset_manifest, args.plan, keep_intermediate=args.keep_intermediate)
    except Exception as error:
        try:
            log_path = write_movie_failure_log(args.output, error, traceback.format_exc())
        except OSError as log_error:
            raise RuntimeError('%s\nCould not write movie diagnostic log: %s' %
                               (error, log_error)) from error
        raise RuntimeError('%s\nFull movie build log: %s' % (error, log_path)) from error
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, IndexError) as error:
        print('Movie build failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
