from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
prepare = (root/'src/Prepare-Sources.ps1').read_text(encoding='utf-8-sig')
overlay = (root/'src/Build-VerifiedOverlay.ps1').read_text(encoding='utf-8-sig')
movie = (root/'src/python/pc_movie_builder.py').read_text(encoding='utf-8')
plan = json.loads((root/'src/pc_movie_build_manifest.json').read_text(encoding='utf-8'))

assert 'Convert-PCMovies.ps1' in prepare and 'Convert-PCComponents.ps1' in prepare
assert 'Game/Content/Movies/' in json.dumps(plan)
assert len(plan['movies']) == 7
assert {row['number'] for row in plan['movies']} == {1, 2, 3, 4, 5, 6, 10}
assert set(plan['retrospective_frame_counts']) == {'7', '8', '9'}
assert 'movie-build-report.json' in overlay
assert 'Mod/romfs' not in overlay
assert 'seven mod parts' not in overlay
assert 'Game/Content/Movies' not in movie or 'source' in movie
assert not (root/'src/verified-inputs/movies.json').exists()
assert not (root/'Start.cmd').exists()
assert (root/'DQXI-Mod-Installer.vbs').is_file()
assert not (root/'DQXI-Mod-Installer.exe').exists()
assert not (root/'src/InstallerLauncher.c').exists()
assert not (root/'tools/Build-InstallerLauncher.ps1').exists()
assert not (root/'Legacy-Mod-Installer.cmd').exists()
assert not list(root.rglob('*.cia')) and not list(root.rglob('*.3ds'))
assert not list(root.rglob('*.pak')) and not list(root.rglob('*.moflex'))
runtime_cs = {path.relative_to(root).as_posix() for path in (root/'third_party/kenzie/native').glob('*.cs')}
assert runtime_cs == {f'third_party/kenzie/native/{name}' for name in
                      ('BuildSupport.cs','Codecs.cs','RomBuilder.cs','CiaSupport.cs')}
assert (root/'src/Load-NativeBackend.ps1').is_file()
assert all((root/'tests/native'/name).is_file() for name in ('CiaSourceTests.cs','CodecTests.cs','CodecEntry.cs'))
assert not (root/'src/python/project_ctr_backend.py').exists()
assert not (root/'tests/project_ctr_backend_tests.py').exists()
assert not (root/'tests/encrypted_cia_test.py').exists()
assert not list(root.rglob('*.pdb')) and not list(root.rglob('*.obj'))
assert not list(root.rglob('*.pyc')) and not list(root.rglob('__pycache__'))
assert not any(path.name == 'AENDERUNG.md' for path in root.rglob('*'))
for path in root.rglob('*'):
    if path.is_file() and path.suffix.lower() not in ('.json', '.pyc'):
        assert '__pycache__' not in path.parts

print('Source audit passed: no separate mod/movie payloads, retail game archives, legacy folder-based launcher, or build-history markdown in the release tree.')
