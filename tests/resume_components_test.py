"""Exercise the resume launcher with controlled component/tool backends.

Checks routing and source preservation, not a Windows GUI or tool download.
The real export validation and parsers are checked by pc_component_tests.py.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pwsh', required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='dqxi resume ;C ') as temp:
        root = Path(temp); installer = root/'installer'; installer.mkdir()
        shutil.copy(ROOT/'src/Resume-PCComponents.ps1', installer)
        shutil.copy(ROOT/'src/Common.ps1', installer/'Common.ps1')
        (installer/'Convert-PCComponents.ps1').write_text('''
param($ExtractedPcRoot,$OutputRoot,$ExtractionReport,$PcRoot,$OriginalRomfs,[switch]$ConvertVoices)
New-Item -ItemType Directory -Path $OutputRoot | Out-Null
[ordered]@{source=$ExtractedPcRoot;output=$OutputRoot;extraction_report=$ExtractionReport;pc_root=$PcRoot;romfs=$OriginalRomfs;voices=[bool]$ConvertVoices} |
 ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputRoot 'component-report.json')
''')
        work = root/'existing build ;C'; work.mkdir()
        pc_root = root/'PC installation ;C'; pc_root.mkdir()
        files = {'pc-assets/pc-extracted/chunk/source.uexp': b'KEEP SOURCE',
                 'pc-assets/pc-extraction-report.json': b'{"complete":true}',
                 'original-3ds/romfs/movie/MOVIE_001.moflex': b'KEEP ORIGINAL',
                 'pc-components/pc-text/en/old.json': b'KEEP PARTIAL OUTPUT'}
        for relative, payload in files.items():
            path = work/relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
        command = [args.pwsh, '-NoProfile', '-File', str(installer/'Resume-PCComponents.ps1'),
                   '-WorkFolder', str(work), '-PcRoot', str(pc_root), '-ConvertVoices']
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout+result.stderr)
        reports = list(work.glob('pc-components-v6-*/component-report.json'))
        assert len(reports) == 2
        for path in reports:
            report = json.loads(path.read_text(encoding='utf-8-sig'))
            assert report['source'] == str(work/'pc-assets/pc-extracted')
            assert report['extraction_report'] == str(work/'pc-assets/pc-extraction-report.json')
            assert report['pc_root'] == str(pc_root)
            assert report['romfs'] == str(work/'original-3ds/romfs')
            assert report['voices'] is True
        assert all((work/name).read_bytes() == payload for name, payload in files.items())
        (work/'pc-assets/pc-extraction-report.json').unlink()
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode != 0
        assert len(list(work.glob('pc-components-v6-*'))) == 2
    print('Resume launcher PASS: existing sources and partial output preserved, unique outputs, paths with spaces/semicolon and missing report rejection.')


if __name__ == '__main__':
    main()
