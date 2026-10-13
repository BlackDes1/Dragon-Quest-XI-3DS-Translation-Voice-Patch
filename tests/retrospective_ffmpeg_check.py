"""Exercise the production retrospective filters with real FFmpeg.

This checks cuts, decoded frame counts and audio duration using an FFV1/PCM
intermediate. It does not test the Windows Mobipeg encoder or game playback.
Supply a synthetic source with >= 760 seconds and four audio streams.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
import pc_movie_builder as builder


def check(source, ffmpeg='ffmpeg', ffprobe='ffprobe', include_title=False):
    plan = builder.read_json(ROOT/'src/pc_movie_build_manifest.json')
    results = []
    with tempfile.TemporaryDirectory(prefix='dqxi-retrospective-check-') as temporary:
        root = Path(temporary)
        work, movies = root/'work', root/'package/movie'
        work.mkdir()
        movies.mkdir(parents=True)

        def encode_intermediate(ffmpeg, ffprobe, inputs, filters, maps, destination,
                                frames, duration, *logs):
            command = [ffmpeg, '-v', 'error', '-y'] + [str(i) for i in inputs] + filters
            for stream in maps:
                command += ['-map', stream]
            command += ['-t', '%.9f' % duration,
                        '-fps_mode', 'passthrough', '-c:v', 'ffv1', '-threads:v', '1',
                        '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2',
                        '-f', 'matroska', str(destination)]
            subprocess.run(command, check=True)
            profile = json.loads(subprocess.check_output([
                ffprobe, '-v', 'error', '-count_frames', '-show_streams',
                '-of', 'json', str(destination)]))
            video = next(s for s in profile['streams'] if s['codec_type'] == 'video')
            audio = next(s for s in profile['streams'] if s['codec_type'] == 'audio')
            pcm = root/'audio.raw'
            with pcm.open('wb') as stream:
                subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(destination),
                                '-map', '0:a:0', '-f', 's16le', '-'], stdout=stream, check=True)
            samples = pcm.stat().st_size//4
            assert int(video['nb_read_frames']) == frames, video
            assert (video['width'], video['height']) == (400, 224), video
            assert video['r_frame_rate'] == '359/12', video
            assert (audio['sample_rate'], audio['channels']) == ('48000', 2), audio
            assert abs(samples - round(duration*48000)) <= 1024, (samples, duration)
            results.append(dict(movie=destination.name, decoded_frames=int(video['nb_read_frames']),
                                fps=video['r_frame_rate'], audio_samples=samples,
                                audio_sample_rate=48000, audio_channels=2,
                                expected_seconds=duration, passed=True))

        with patch.object(builder, 'encode_moflex', side_effect=encode_intermediate):
            for number in (7, 8, 9):
                builder.convert_retrospective(number, plan['retrospectives'], source,
                    ffmpeg, ffprobe, work, movies, 400, 224,
                    plan['credits_suffix_start_seconds'], plan['retrospective_frame_counts'][str(number)])
            if include_title:
                row = dict(next(r for r in plan['movies'] if r['number'] == 1))
                row['source'] = source.name
                builder.convert_direct_movie(row, source.parent, {}, root, None,
                    ffmpeg, ffprobe, None, None, work, movies, 400, 224, voice_cache=({}, set()))
    return dict(test='production retrospective filter graphs and optional retimed title', source='synthetic video/audio',
                intermediate='FFV1 / PCM stereo; not MOFLEX', windows_mobipeg_tested=False,
                complete=True, results=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--include-title', action='store_true', help='Also check the retimed title video/audio filters.')
    args = parser.parse_args()
    result = check(args.source, include_title=args.include_title)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
