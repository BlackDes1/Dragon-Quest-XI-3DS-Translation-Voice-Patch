"""Validate reusable local exports and inventory loose films, without hashes."""
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def local_file(root, relative, verified_paths=None):
    root = Path(root)
    if verified_paths is None or not root.is_absolute():
        root = root.resolve()
    relative = str(relative).replace('\\', '/')
    if relative.startswith('/') or ':' in relative or any(part in ('', '.', '..') for part in relative.split('/')):
        raise ValueError('Unsafe inventory path')
    path = root.joinpath(*relative.split('/'))
    if root not in path.parents:
        raise ValueError('Inventory path escapes source directory')
    if verified_paths is None:
        verified_paths = set()
    for parent in (path, *path.parents):
        if parent == root:
            break
        is_leaf = parent == path
        if not is_leaf and parent in verified_paths:
            continue
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Linked inventory path')
        if not is_leaf:
            verified_paths.add(parent)
    return path


def validate_extraction(source, report_path, manifest_path=None):
    """Do not trust a success flag alone; check every current recipe and size."""
    manifest = read_json(manifest_path or ROOT/'pc_asset_manifest.json')
    expected = {(a['chunk'], a['path']) for a in manifest['assets']}
    report = read_json(report_path)
    recorded = {(a['chunk'], a['path']): a['bytes'] for a in report.get('assets', [])}
    if (report.get('complete') is not True or len(expected) != len(manifest['assets']) or
            len(recorded) != len(report.get('assets', [])) or set(recorded) != expected or
            report.get('required_assets') != len(expected) or report.get('extracted_assets') != len(expected)):
        raise ValueError('Extraction report does not cover the current PC recipes')
    source_root = Path(source).resolve()
    verified_paths = {source_root}
    for (chunk, relative), size in recorded.items():
        path = local_file(source_root, chunk+'/'+relative, verified_paths)
        try:
            metadata = path.stat()
        except OSError as error:
            raise ValueError('Reusable PC export missing, empty or changed size: '+chunk+'/'+relative) from error
        if (not isinstance(size, int) or size <= 0 or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != size):
            raise ValueError('Reusable PC export missing, empty or changed size: '+chunk+'/'+relative)
    return dict(reused=True, verified_files=len(expected), source_hash_check=False,
                verification='Current recipe paths and reported nonzero file sizes; parsers verify contents')


def movie_inventory(pc_root, romfs_root=None, movie_plan_path=None):
    """Inventory only the PC USM files required by the local movie builder."""
    plan = read_json(movie_plan_path or ROOT/'pc_movie_build_manifest.json')
    pc_paths = sorted({row['source'] for row in plan.get('movies', [])})
    report = dict(schema_version=1, content_read=False, source_hash_check=False,
                  pc_files=[], original_3ds_files=[], problems=[],
                  required_movie_sources=len(pc_paths), scene_mapping_verified=False,
                  conversion_complete=False)
    pc_root = Path(pc_root).resolve()
    verified_paths = {pc_root}
    for relative in pc_paths:
        try:
            path = local_file(pc_root, relative, verified_paths)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Missing or empty PC USM movie')
            report['pc_files'].append(dict(path=relative, bytes=path.stat().st_size))
        except (OSError, ValueError) as error:
            report['problems'].append(dict(source='pc_files', path=relative, reason=str(error)))
    report['source_inventory_complete'] = not report['problems']
    return report
