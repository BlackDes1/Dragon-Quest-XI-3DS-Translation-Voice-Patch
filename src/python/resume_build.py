"""Check a previous source workspace before resuming movie conversion."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pc_components
import pc_movie_builder
import pc_source_inventory


def validate_resume(build_root, original_cia, pc_root, manifest_path=None, jobs_path=None, plan_path=None):
    root = Path(build_root).resolve()
    verified_paths = {root}

    def local(relative):
        return pc_source_inventory.local_file(root, relative, verified_paths)

    def read(relative):
        return pc_source_inventory.read_json(local(relative))

    if local('Mod').exists() or local('cia').exists():
        raise ValueError('This workspace already reached mod/container assembly. Movie resume requires a build stopped before Mod was created.')
    cia = read('original-3ds/cia-extraction-report.json')
    if (cia.get('title_id') != '0004000000199200' or
            Path(cia.get('source_cia', '')).resolve() != Path(original_cia).resolve()):
        raise ValueError('The selected CIA does not match the original extraction report.')
    romfs = local('original-3ds/romfs')
    count, total = 0, 0
    for candidate in romfs.rglob('*'):
        candidate = local(candidate.relative_to(root).as_posix())
        if candidate.is_file():
            count += 1
            total += candidate.stat().st_size
    if (count <= 0 or total <= 0 or count != cia.get('romfs_file_count') or
            total != cia.get('romfs_total_bytes')):
        raise ValueError('The original ROMFS export is missing, incomplete or changed size.')
    code = local('original-3ds/exefs/code.bin')
    if not code.is_file() or code.stat().st_size == 0:
        raise ValueError('The original ExeFS code export is missing or empty.')
    extraction = pc_source_inventory.validate_extraction(local('pc-assets/pc-extracted'),
        local('pc-assets/pc-extraction-report.json'), manifest_path)
    components = read('pc-components/component-report.json')
    voices = components.get('voice_conversion', {})
    jobs = pc_source_inventory.read_json(jobs_path or HERE.parent/'recipes/voice_jobs.json')['jobs']
    by_index = {row.get('index'): row for row in voices.get('files', [])}
    if (voices.get('complete') is not True or voices.get('required') != len(jobs) or
            voices.get('converted') != len(jobs) or len(by_index) != len(jobs) or
            len(voices.get('files', [])) != len(jobs) or voices.get('missing_indices')):
        raise ValueError('The completed gameplay voice conversion is missing or incomplete.')
    for job in jobs:
        evidence = by_index.get(job['index'], {})
        expected_path = 'sound/'+job['path']
        full_samples = max(1, (job['samples']*22050+job['sample_rate']//2)//job['sample_rate'])
        start = job.get('segment_start_sample_22050', 0) or 0
        end = job.get('segment_end_sample_22050')
        expected_samples = (end if end is not None else full_samples) - start
        if (evidence.get('path') != expected_path or evidence.get('sample_rate') != 22050 or
                abs(evidence.get('samples', -100)-expected_samples) > 1):
            raise ValueError('Reusable gameplay voice differs from its recipe: '+str(job['index']))
        pc_components.verify_bcstm(local('pc-components/voice-components/'+expected_path), evidence['samples'])
    scenes = read('pc-components/pc-scenes/scene-events.json')
    if scenes.get('report', {}).get('complete') is not True:
        raise ValueError('The previous scene event export is incomplete.')
    plan = pc_source_inventory.read_json(plan_path or HERE.parent/'pc_movie_build_manifest.json')
    for row in plan['movies']:
        if row['scene_map']:
            pc_movie_builder.event_rows(scenes, row['scene_map'], row.get('skip_caption_ids', []))
    movie_report = None
    if local('pc-movies').exists():
        movie_report = read('pc-movies/movie-build-report.json')
        records = movie_report.get('files', [])
        expected = {'MOVIE_%03d.moflex' % r['number']: r['frames'] for r in plan['movies']}
        expected.update({'MOVIE_%03d.moflex' % int(n): f for n, f in plan['retrospective_frame_counts'].items()})
        if (movie_report.get('complete') is not True or movie_report.get('movie_count') != 10 or
                len(records) != 10 or {r.get('name') for r in records} != set(expected)):
            raise ValueError('The existing movie package is incomplete; it cannot be reused.')
        source_hashes = {}
        for record in records:
            name = record['name']
            if not pc_movie_builder.verified_movie(record, local('pc-movies/movie/'+name), expected[name], 400, 224):
                raise ValueError('A completed movie failed checkpoint validation: '+name)
            source = pc_movie_builder.safe(pc_root, record['source'])
            if source not in source_hashes:
                source_hashes[source] = pc_movie_builder.sha256(source)
            if source_hashes[source] != record.get('source_sha256') or source.stat().st_size != record.get('source_bytes'):
                raise ValueError('The PC movie source changed: '+name)
    return dict(schema_version=1, sources_reusable=True, romfs_files=count, romfs_bytes=total,
                pc_files_checked=extraction['verified_files'], gameplay_voices_checked=len(jobs),
                complete_movie_package=movie_report is not None, movie_report=movie_report,
                verification='Recipe paths, original export counts/sizes, voice PCM layout, movie decode evidence and checksums')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--original-cia', type=Path, required=True)
    parser.add_argument('--pc-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_resume(args.build_root, args.original_cia, args.pc_root)
        args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('Existing sources verified: %d ROMFS files, %d PC assets, %d gameplay voices.' %
              (result['romfs_files'], result['pc_files_checked'], result['gameplay_voices_checked']), flush=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Cannot resume this build: '+str(error), file=sys.stderr)
        raise SystemExit(1)
