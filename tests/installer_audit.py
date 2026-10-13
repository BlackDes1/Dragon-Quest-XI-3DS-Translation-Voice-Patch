from pathlib import Path
import json

project = Path(__file__).resolve().parents[1]
installer = (project/'src/Installer.ps1').read_text(encoding='utf-8-sig')
prepare = (project/'src/Prepare-Sources.ps1').read_text(encoding='utf-8-sig')
overlay = (project/'src/Build-VerifiedOverlay.ps1').read_text(encoding='utf-8-sig')
movie_script = (project/'src/Convert-PCMovies.ps1').read_text(encoding='utf-8-sig')
movie_builder = (project/'src/python/pc_movie_builder.py').read_text(encoding='utf-8')
common = (project/'src/Common.ps1').read_text(encoding='utf-8-sig')
source_validator = (project/'src/Test-GameSources.ps1').read_text(encoding='utf-8-sig')
inventory = (project/'src/python/pc_source_inventory.py').read_text(encoding='utf-8')
pc_tools = json.loads((project/'src/pc_tool_manifest.json').read_text(encoding='utf-8'))
three_ds_tools = json.loads((project/'src/3ds_tool_manifest.json').read_text(encoding='utf-8'))

assert 'DRAGON QUEST XI — Mod Installer' in installer
assert "'Build mod'" in installer and "'Open build folder'" in installer
assert "'Open finished output'" in installer and 'final_output_directory' in installer
assert 'Assert-DQXIPathNoReparse $expectedFinal' in installer
assert 'Original Japanese CIA' in installer and 'Full PC installation' in installer
assert 'seven-part mod archive is not required' not in installer.lower()
assert 'Windows.Forms.ProgressBar' in installer
assert '[Windows.Forms.ProgressBarStyle]::Marquee' in installer
assert '$progressStatus.Text=$progressLine[0].Trim()' in installer
assert '$progress.Value=100' in installer
assert "'Resume build'" in installer and "$arguments+='-Resume'" in installer
assert '[switch]$Resume' in prepare and 'python/resume_build.py' in prepare
assert 'Reusing CIA extraction, PC export and completed gameplay voices.' in prepare
assert "output.name+'.partial'" in movie_builder
assert 'load_movie_checkpoint' in movie_builder and 'save_movie_checkpoint' in movie_builder
assert "plan['retrospective_frame_counts'][str(number)]" in movie_builder
assert 'Builds 5,551 dialogue targets' not in installer
assert '5,095 voice links' not in installer
assert 'Wähle' not in installer and 'Prüfe' not in installer
assert 'Validating the complete PC file list' in prepare
assert 'Convert-PCMovies.ps1' in prepare and 'movie-build-report.json' in prepare
assert '-MovieRoot $movieOutput' in prepare and '-PcRoot $PcRoot' in prepare
assert "'mobipeg'" in (project/'src/Get-PCBuildTools.ps1').read_text(encoding='utf-8-sig')
assert '--ffmpeg' in movie_script and '--ffprobe' in movie_script
assert 'mobiclip' in movie_builder and 'adpcm' in movie_builder
assert 'MOFLEX full decode' in movie_builder and "'-progress', 'pipe:1'" in movie_builder
assert "'-f', 'moflex'" in movie_builder and "'-threads:v', '1'" in movie_builder
assert "-encode-failure.log" in movie_builder
assert 'movie-build-report.json' in overlay and '--pc-root' in overlay
assert 'Unsupported TMD signature type: 0x$signatureKey.' in common
assert (project/'tests/tmd_signature_regression.ps1').is_file()
assert 'Get-DQXIPcManifestPath' in source_validator
assert 'Dictionary[string,System.IO.FileAttributes]' in source_validator
assert 'Get-DQXISafePath $PcRoot' not in source_validator
assert 'verified_paths' in inventory and 'stat.S_ISREG(metadata.st_mode)' in inventory

mobipeg = pc_tools['mobipeg']
assert mobipeg['version'] == '2.3'
assert mobipeg['url'].startswith('https://github.com/quatric/mobipeg/releases/')
assert len(mobipeg['archive_sha256']) == 64
assert {entry['path'] for entry in mobipeg['files']} == {'ffmpeg.exe', 'ffprobe.exe'}

ctr_tools = {row['name'] for row in three_ds_tools['tools']}
assert {'ctrtool', 'makerom'}.issubset(ctr_tools)
extractor = (project/'src/Extract-OriginalCIA.ps1').read_text(encoding='utf-8-sig')
container = (project/'src/Build-3DSContainer.ps1').read_text(encoding='utf-8-sig')
native_loader = (project/'src/Load-NativeBackend.ps1').read_text(encoding='utf-8-sig')
native_cia = (project/'third_party/kenzie/native/CiaSupport.cs').read_text(encoding='utf-8')
assert 'Initialize-DQXINativeBackend' in extractor and 'CiaSupport]::ExtractOriginal' in extractor
assert "new string[]{\"-q\",\"--contents=\"+prefix,\"--tmd=\"+tmd,cia}" in native_cia
assert 'ExtractRomfsDirectory(threeDstool' in native_cia
assert 'ROMFS extraction completed:' in native_cia and '3dstool produced an empty ROMFS directory.' in native_cia
assert 'BuildSupport.NoReparse(file)' not in native_cia
assert 'entry.Attributes' in native_cia
assert 'new DirectoryInfo(current).EnumerateFileSystemInfos()' in native_cia and 'entry.FullName' in native_cia
native_build_support = (project/'third_party/kenzie/native/BuildSupport.cs').read_text(encoding='utf-8')
assert 'pendingLines>=128' in native_build_support and 'flushClock.ElapsedMilliseconds>=500' in native_build_support
assert 'romfs_file_count=$source.RomFsFileCount' in extractor
assert 'RomBuilder]::BuildGameFromNcch' in container and 'CiaSupport]::PackCia' in container
assert 'original_romfs_file_count=$source.RomFsFileCount' in container
assert 'CiaSupport]::ReuseExtracted' in container and '-PreparedOriginalRoot $ciaRoot' in prepare
assert "Release-DQXIIntermediate 'complete'" in prepare
assert 'VerifyTreeSnapshot(expectedRomfs,verifyRomfs,cancel)' in (project/'third_party/kenzie/native/RomBuilder.cs').read_text()
assert all((project/'third_party/kenzie/native'/name).is_file() for name in
           ('BuildSupport.cs','Codecs.cs','RomBuilder.cs','CiaSupport.cs'))
assert (project/'tests/native/CodecTests.cs').is_file()
assert all(name in native_loader for name in ('BuildSupport.cs','Codecs.cs','RomBuilder.cs','CiaSupport.cs'))
assert not (project/'src/python/project_ctr_backend.py').exists()
assert not (project/'tests/project_ctr_backend_tests.py').exists()

launcher = project/'DQXI-Mod-Installer.vbs'
launcher_text = launcher.read_text(encoding='ascii')
assert 'WScript.Shell' in launcher_text and 'shell.Run(command, 0, True)' in launcher_text
assert 'Launch-Installer.ps1' in launcher_text and 'powershell.exe' in launcher_text
assert 'cmd.exe' not in launcher_text.lower()
assert not (project/'Start.cmd').exists()
launch_script = (project/'src/Launch-Installer.ps1').read_text(encoding='utf-8-sig')
assert '$ErrorActionPreference = \'Stop\'' in launch_script
assert 'DQXI-Mod-Installer-startup-' in launch_script and 'MessageBox]::Show' in launch_script
assert not (project/'DQXI-Mod-Installer.exe').exists()
assert not (project/'src/InstallerLauncher.c').exists()
assert not (project/'tools/Build-InstallerLauncher.ps1').exists()
runtime_cs = {p.relative_to(project).as_posix() for p in (project/'third_party/kenzie/native').glob('*.cs')}
assert runtime_cs == {f'third_party/kenzie/native/{name}' for name in
                      ('BuildSupport.cs','Codecs.cs','RomBuilder.cs','CiaSupport.cs')}
assert all((project/'tests/native'/name).is_file() for name in ('CiaSourceTests.cs','CodecTests.cs','CodecEntry.cs'))
assert not (project/'src/Installer-Legacy.ps1').exists()
assert not (project/'Legacy-Mod-Installer.cmd').exists()

print('Installer audit passed: hidden VBS launcher, English UI, restored native CIA backend, complete 3dstool ROMFS extraction checks, pinned Mobipeg pipeline, and TMD signature coverage.')
