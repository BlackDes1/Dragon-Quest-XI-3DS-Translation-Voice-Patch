"""Compare user-created extracted-PAK lists with the active PC recipes.

Uses filenames only. Does not hash or read game assets. The lists can contain
absolute Windows paths; only paths below the named chunk are retained.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_paths(filename, chunk):
    with Path(filename).open('rb') as stream:
        bom = stream.read(2)
    encoding = 'utf-16' if bom in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    result, skipped, duplicates = {}, 0, 0
    with Path(filename).open(encoding=encoding) as stream:
        for line in stream:
            line = line.strip().replace('\\', '/')
            marker = chunk+'/'
            at = line.casefold().find(marker.casefold())
            if at < 0:
                skipped += 1
                continue
            relative = line[at+len(marker):]
            if not relative or '..' in relative.split('/') or ':' in relative:
                raise ValueError('Unsafe relative path in file list')
            key = relative.casefold()
            if key in result:
                duplicates += 1
            result[key] = relative
    if not result:
        raise ValueError('No paths for '+chunk)
    return result, dict(unique_paths=len(result), skipped_lines=skipped, duplicate_paths=duplicates)


def compare(lists, manifest, jobs, tables):
    missing = [a for a in manifest['assets'] if a['path'].casefold() not in lists[a['chunk']]]
    missing_jobs = [j['index'] for j in jobs if j['bank_path'].casefold() not in lists[j['bank_chunk']]]
    non_english = [j['index'] for j in jobs if j['language'] != 'en' or '/Voice_NE/' not in j['bank_path']]
    pairs = {(a['chunk'], a['path'].casefold()) for a in manifest['assets']}
    recipe_gaps = [j['index'] for j in jobs if (j['bank_chunk'], j['bank_path'].casefold()) not in pairs]
    table_gaps = []
    for table in tables:
        for language, field in (('en', 'english'), ('ja', 'japanese')):
            for extension in ('.uasset', '.uexp'):
                path = str(Path(table[field]).with_suffix(extension)).replace('\\', '/')
                if (table['chunk'], path.casefold()) not in pairs:
                    table_gaps.append(dict(name=table['name'], language=language, path=path))
    untracked = []
    for chunk, paths in lists.items():
        for path in paths.values():
            if ('/L10N/en/' in '/'+path and Path(path).name.startswith('DT_Text')
                    and path.endswith('.uasset') and (chunk, path.casefold()) not in pairs):
                untracked.append(dict(chunk=chunk, path=path))
    return dict(schema_version=1, filename_comparison_only=True, input_hash_check=False,
                required_assets=len(manifest['assets']), matched_assets=len(manifest['assets'])-len(missing),
                required_voice_banks=manifest['voice_banks'], required_voice_clips=len(jobs),
                explicit_english_voice_banks=len({(j['bank_chunk'], j['bank_path']) for j in jobs
                                                if j['language']=='en' and '/Voice_NE/' in j['bank_path']}),
                required_text_table_pairs=len(tables), missing_assets=missing,
                missing_voice_job_indices=missing_jobs, non_english_voice_job_indices=non_english,
                voice_recipe_manifest_gaps=recipe_gaps, text_recipe_manifest_gaps=table_gaps,
                untracked_english_text_tables=sorted(untracked, key=lambda a:(a['chunk'], a['path'])),
                complete=not any((missing, missing_jobs, non_english, recipe_gaps, table_gaps, untracked)),
                proves_game_content_or_playability=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunk0-list', type=Path, required=True)
    parser.add_argument('--chunk1-list', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lists, inventory = {}, {}
    for n in (0, 1):
        chunk = f'pakchunk{n}-WindowsNoEditor'
        lists[chunk], inventory[chunk] = read_paths(getattr(args, f'chunk{n}_list'), chunk)
    load = lambda p: json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
    result = compare(lists, load('src/pc_asset_manifest.json'),
                     load('src/recipes/voice_jobs.json')['jobs'], load('src/recipes/text_tables.json')['tables'])
    result['inventories'] = inventory
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"Matched {result['matched_assets']}/{result['required_assets']} assets; "
          f"{result['explicit_english_voice_banks']} explicit English banks; complete={result['complete']}")
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
