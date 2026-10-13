"""Check real PowerShell diagnostics: reports only, no game payloads or links."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pwsh', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='dqxi-diagnostics-test-') as temp:
        root = Path(temp)
        work = root/'work'; work.mkdir()
        reports = ['source-preparation-report.json', 'original-3ds/cia-extraction-report.json',
                   'original-3ds/cia-extraction-error.json','pc-assets/pc-extraction-report.json', 'pc-components/component-report.json',
                   'pc-components/text-progress-report.json','pc-components/movie-sources-report.json',
                   'pc-dialogue/dialogue-build-report.json',
                   'pc-components-v6-'+32*'a'+'/component-report.json',
                   'pc-components-v6-'+32*'a'+'/text-progress-report.json']
        for relative in reports:
            path = work/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"fixture":true}')
        log=work/'original-3ds/extract.log'
        log.write_text('Extraction stage completed\nTitle key (dec): PRIVATE-CRYPTO-FIXTURE\nKeyY: PRIVATE-CRYPTO-FIXTURE\nSeed: PRIVATE-CRYPTO-FIXTURE\n')
        reports.append('original-3ds/extract.log')
        for relative in ['original.cia', 'pc-assets/pc-extracted/fixture.uexp',
                         'pc-components/pc-text/en/table.json', 'original-3ds/romfs/movie/Movie001.moflex',
                         'pc-components-v6-'+32*'a'+'/pc-text/en/table.json',
                         'pc-components-v6-'+32*'a'+'/unexpected.json',
                         'original-3ds/romfs/Pack/example.pack']:
            path = work/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'PRIVATE GAME CONTENT; MUST NOT APPEAR IN ARCHIVE')
        output = root/'diagnostics.zip'
        command = [args.pwsh, '-NoProfile', '-File', str(ROOT/'src/Collect-Diagnostics.ps1'),
                   '-WorkFolder', str(work), '-OutputZip', str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout+result.stderr)
        with zipfile.ZipFile(output) as archive:
            assert set(archive.namelist()) == set(reports+['diagnostics-index.json', 'original-romfs-file-list.json'])
            assert all(b'PRIVATE GAME CONTENT' not in archive.read(n) for n in archive.namelist())
            assert all(b'PRIVATE-CRYPTO-FIXTURE' not in archive.read(n) for n in archive.namelist())
            assert b'Extraction stage completed' in archive.read('original-3ds/extract.log')
            inventory = json.loads(archive.read('original-romfs-file-list.json').decode('utf-8-sig'))
            assert inventory['file_count'] == 2 and inventory['content_read'] is False
            assert {p['path'] for p in inventory['files']} == {'movie/Movie001.moflex', 'Pack/example.pack'}
        original_zip = output.read_bytes()
        assert subprocess.run(command, capture_output=True).returncode != 0
        assert output.read_bytes() == original_zip
        outside = root/'outside.pack'; outside.write_bytes(b'PRIVATE OUTSIDE FILE')
        (work/'original-3ds/romfs/link.pack').symlink_to(outside)
        linked_output = root/'linked.zip'
        linked_command = command[:-1]+[str(linked_output)]
        assert subprocess.run(linked_command, capture_output=True).returncode != 0
        assert not linked_output.exists()
    print('Diagnostics test passed: resume/progress/movie metadata only, user texts excluded, crypto log lines removed, existing ZIP preserved, symlinks rejected.')


if __name__ == '__main__':
    main()
