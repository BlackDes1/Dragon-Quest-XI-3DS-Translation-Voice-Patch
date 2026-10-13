"""Exercise real PowerShell extraction orchestration with a controlled decoder.

Linux developer test: requires a PowerShell binary (--pwsh). It tests path and
patch precedence, not Unreal PAK decoding or Windows GUI behaviour.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--pwsh',required=True)
    args=a.parse_args()
    with tempfile.TemporaryDirectory(prefix='dqxi-extraction-test-') as tmp:
        temp=Path(tmp)
        pak=temp/'PC';pak.mkdir()
        for chunk in ('pakchunk0-WindowsNoEditor','pakchunk1-WindowsNoEditor'):
            for suffix in ('.pak','_0_P.pak'):
                (pak/(chunk+suffix)).write_bytes(b'fixture, not a PAK')
        fake=temp/'fixture-decoder'
        fake.write_text('''#!/usr/bin/env python3
import sys, fnmatch
from pathlib import Path
pak=Path(sys.argv[-2]).name
out=Path(sys.argv[-1]);patch='_0_P' in pak
if 'pakchunk0' in pak:
    files={'Scenario/DT_A.uexp':b'JP-PATCH'} if patch else {
      'JackGame/Content/Scenario/DT_A.uexp':b'JP-BASE',
      'JackGame/Content/L10N/en/Scenario/DT_A.uexp':b'EN-BASE',
      'JackGame/Content/L10N/fr/Scenario/DT_A.uexp':b'EXCLUDED-FRENCH',
      'Unrelated/Scenario/DT_A.uexp':b'EXCLUDED-SUFFIX',
      'JackGame/Content/Textures/HugeTexture.uasset':b'EXCLUDED-TEXTURE'}
else:
    files={'Sounds/Voice_NE/CS/fixture.uexp':b'VOICE-PATCH'} if patch else {
      'JackGame/Content/Sounds/Voice_NE/CS/fixture.uexp':b'VOICE-BASE'}
patterns=Path(sys.argv[sys.argv.index('-f')+1]).read_text().splitlines()
assert all('*' not in p and '?' not in p for p in patterns), 'broad extraction filter'
for relative,data in files.items():
    if not any(fnmatch.fnmatchcase(relative,p) for p in patterns):continue
    p=out/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
''')
        fake.chmod(0o700)
        bms=temp/'fixture.bms';bms.write_text('fixture only')
        script=(ROOT/'src/Extract-PCAssets.ps1').read_text(encoding='utf-8-sig')
        # Only the tool integrity pins are replaced in this private test copy.
        # Production script and bundled-tool checks remain intact.
        script=script.replace('3a248ab5f9f1dae7b999b4098cb623372ae29ebaefbb72f8c359cf3b72d2b5a7',hashlib.sha256(fake.read_bytes()).hexdigest())
        script=script.replace('7cff0ac7058740c3e7873ab35a279702b5c64e78d774f9c8a519d29dfe05f04e',hashlib.sha256(bms.read_bytes()).hexdigest())
        script_path=temp/'Extract-PCAssets.ps1';script_path.write_text(script)
        manifest=temp/'manifest.json'
        assets=[dict(chunk='pakchunk0-WindowsNoEditor',path='JackGame/Content/Scenario/DT_A.uexp',kind='text',language='ja'),
                dict(chunk='pakchunk0-WindowsNoEditor',path='JackGame/Content/L10N/en/Scenario/DT_A.uexp',kind='text',language='en'),
                dict(chunk='pakchunk1-WindowsNoEditor',path='Sounds/Voice_NE/CS/fixture.uexp',kind='voice',language='en')]
        manifest.write_text(json.dumps(dict(schema_version=3,voice_banks=1,text_table_files=2,
            additional_voice_files=0,additional_voice_banks=0,scene_map_files=0,scene_map_pairs=0,assets=assets)))
        output=temp/'output'
        result=subprocess.run([args.pwsh,'-NoLogo','-NoProfile','-File',str(script_path),'-PakRoot',str(pak),
            '-OutputRoot',str(output),'-QuickBmsPath',str(fake),'-BmsPath',str(bms),'-ManifestPath',str(manifest)],
            text=True,capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout+'\n'+result.stderr)
        root=output/'pc-extracted'
        assert (root/assets[0]['chunk']/assets[0]['path']).read_bytes()==b'JP-PATCH'
        assert (root/assets[1]['chunk']/assets[1]['path']).read_bytes()==b'EN-BASE'
        assert (root/assets[2]['chunk']/assets[2]['path']).read_bytes()==b'VOICE-PATCH'
        report=json.loads((output/'pc-extraction-report.json').read_text(encoding='utf-8-sig'))
        assert report['complete'] and report['extracted_assets']==3 and report['update_paks_override_base']
        assert report['selective_extraction'] and report['unrequested_files_exported']==0
        assert len(list(root.rglob('*.uexp')))==3
        assert Path(report['extracted_root'])==root
        assert not list(output.glob('.pc-extract-*'))
        # A decoder that ignores the allowlist must stop the stage, without
        # promoting unrelated content into the public extraction output.
        original_pin=hashlib.sha256(fake.read_bytes()).hexdigest()
        assert original_pin in script
        fake.write_text(fake.read_text()+"\np=out/'JackGame/Content/Textures/Unrequested.uasset';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'unrequested')\n")
        script_path.write_text(script.replace(original_pin,hashlib.sha256(fake.read_bytes()).hexdigest()))
        failed_output=temp/'failed output'
        failed=subprocess.run([args.pwsh,'-NoLogo','-NoProfile','-File',str(script_path),'-PakRoot',str(pak),
            '-OutputRoot',str(failed_output),'-QuickBmsPath',str(fake),'-BmsPath',str(bms),'-ManifestPath',str(manifest)],
            text=True,capture_output=True)
        assert failed.returncode and 'unrequested PC file' in failed.stderr
        assert not (failed_output/'pc-extracted').exists() and not list(failed_output.glob('.pc-extract-*'))
        print('PowerShell selective extraction PASS: excludes other languages/textures/suffix lookalikes; preserves patch precedence across mount variants; report and cleanup.')


if __name__=='__main__':
    main()
