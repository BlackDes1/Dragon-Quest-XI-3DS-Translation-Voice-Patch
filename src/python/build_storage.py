"""Release owned build intermediates only after their verified successor exists."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def plain_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Linked cleanup path: '+str(part))
        if part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse cleanup path: '+str(part))
    return path


def local(root, relative):
    if (Path(relative).is_absolute() or ':' in relative or
            any(p in ('', '.', '..') for p in relative.replace('\\', '/').split('/'))):
        raise ValueError('Unsafe build cleanup path.')
    path = plain_path(root/relative)
    if root not in path.parents:
        raise ValueError('Build cleanup path escapes its root.')
    return path


def generated_media(source, destination):
    """Share immutable, generated media on the same volume; copy elsewhere."""
    source, destination = plain_path(source), plain_path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('Generated media is missing or empty: '+str(source))
    if destination.exists():
        raise ValueError('Generated media destination already exists.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return 'hardlink'
    except OSError:
        shutil.copyfile(source, destination)
        if destination.stat().st_size != source.stat().st_size or digest(destination) != digest(source):
            destination.unlink(missing_ok=True)
            raise ValueError('Generated media copy failed checksum verification.')
        return 'copy'


def verify_mod(root):
    report = read_json(local(root, 'Mod/build-report.json'))
    if report.get('complete') is not True:
        raise ValueError('The mod must be complete before intermediate cleanup.')
    rows = read_json(local(root, 'Mod/files.json'))
    if not rows:
        raise ValueError('The generated mod manifest is empty.')
    seen = set()
    for row in rows:
        relative = row['path']
        path = local(root, 'Mod/'+relative)
        if relative in seen or not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError('Generated mod changed before cleanup: '+relative)
        seen.add(relative)


def inventory(path):
    result = []
    if not path.exists():
        return result
    for current in ([path] if path.is_file() else path.rglob('*')):
        current = plain_path(current)
        if current.is_file():
            metadata = current.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError('Unsupported cleanup file: '+str(current))
            result.append((current, metadata.st_size))
    return result


REPORTS = {
    'original-3ds/cia-extraction-report.json': 'cia-extraction-report.json',
    'original-3ds/cia-extraction-error.json': 'cia-extraction-error.json',
    'original-3ds/extract.log': 'extract.log',
    'pc-assets/pc-extraction-report.json': 'pc-extraction-report.json',
    'pc-components/component-report.json': 'component-report.json',
    'pc-components/text-progress-report.json': 'text-progress-report.json',
    'pc-components/movie-sources-report.json': 'movie-sources-report.json',
    'pc-movies/movie-build-report.json': 'movie-build-report.json',
    'Mod/build-report.json': 'build-report.json',
    'Mod/files.json': 'mod-files.json',
    'cia/container-report.json': 'container-report.json',
}


def preserve_reports(root):
    for relative, name in REPORTS.items():
        source = local(root, relative)
        if source.is_file():
            destination = local(root, 'reports/'+name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    private = local(root, 'cia/.dqxi-private')
    if private.exists():
        for source in private.rglob('*.log'):
            source = plain_path(source)
            relative = source.relative_to(private).as_posix()
            destination = local(root, 'reports/cia-logs/'+relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def cleanup(build_root, phase, output_format):
    root = plain_path(build_root)
    if not root.is_dir() or root.parent == root:
        raise ValueError('A build folder is required for cleanup.')
    candidates = []
    if phase == 'extraction':
        report = read_json(local(root, 'original-3ds/cia-extraction-report.json'))
        if report.get('title_id') != '0004000000199200' or report.get('romfs_file_count', 0) <= 0:
            raise ValueError('Original extraction is not complete.')
        source_root = local(root, 'original-3ds')
        active = {plain_path(row['Path']) for row in report['contents']}
        if any(source_root not in path.parents for path in active):
            raise ValueError('Extracted content path escapes the owned source folder.')
        for path in source_root.iterdir():
            if re.fullmatch(r'(?:decrypted-)?content\.[0-9a-f]{4}\.[0-9a-f]{8}(?:\.cxi)?', path.name, re.I):
                if output_format == 'layeredfs' or path not in active:
                    candidates.append(plain_path(path))
        if output_format == 'layeredfs':
            candidates.extend(local(root, 'original-3ds/'+name) for name in ('romfs.bin', 'exefs.bin'))
    elif phase in ('overlay', 'complete'):
        verify_mod(root)
        candidates.extend(local(root, name) for name in ('pc-assets', 'pc-components', 'pc-movies'))
        if phase == 'complete':
            if output_format == 'cia':
                container = read_json(local(root, 'cia/container-report.json'))
                cia = local(root, 'cia/DQXI-S-3DS.cia')
                if (container.get('container_content_readback_verified') is not True or
                        not cia.is_file() or cia.stat().st_size <= 0 or
                        container.get('output_sha256') != digest(cia) or
                        cia.stat().st_size != container.get('output_bytes')):
                    raise ValueError('Verified final CIA evidence is required for cleanup.')
                candidates.append(local(root, 'Mod'))
            candidates.extend(local(root, name) for name in ('original-3ds', 'cia/.dqxi-private'))
    else:
        raise ValueError('Unknown cleanup phase.')
    # Validate all paths and descendants before deleting the first item.
    inventories = {path: inventory(path) for path in candidates}
    preserve_reports(root)
    errors, removed, removed_bytes = [], 0, 0
    for path in candidates:
        if not path.exists():
            continue
        count = inventories[path]
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += len(count)
            removed_bytes += sum(size for _, size in count)
        except OSError as error:
            errors.append(str(error))
    run = dict(phase=phase, output_format=output_format, files_removed=removed,
               file_bytes_unlinked=removed_bytes, complete=not errors, warnings=errors)
    report_path = local(root, 'storage-cleanup-report.json')
    previous = read_json(report_path) if report_path.exists() else {'schema_version': 1, 'runs': []}
    previous['runs'].append(run)
    report_path.write_text(json.dumps(previous, indent=2), encoding='utf-8')
    return run


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--phase', choices=('extraction', 'overlay', 'complete'), required=True)
    parser.add_argument('--format', choices=('cia', 'layeredfs'), required=True)
    args = parser.parse_args()
    try:
        result = cleanup(args.build_root, args.phase, args.format)
        print('Storage cleanup (%s): %d temporary files released.' % (args.phase, result['files_removed']), flush=True)
        for warning in result['warnings']:
            print('Cleanup warning: '+warning, flush=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Storage cleanup stopped: '+str(error), file=sys.stderr)
        raise SystemExit(1)
