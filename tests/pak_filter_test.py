"""Exercise selective extraction with real QuickBMS and the bundled DQXI BMS.

Synthetic uncompressed UE4 v1 PAKs contain no game data. The test checks exact
path filters, DQXI byte inversion, and patch precedence across mount variants.
It does not substitute for all compression/index versions of real DQXI S PAKs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def fstring(value):
    raw=value.encode('ascii')+b'\0'
    return struct.pack('<i',len(raw))+raw


def make_pak(path, files):
    content=bytearray();records=[]
    for name, payload in files.items():
        offset=len(content)
        entry=struct.pack('<QQIQ',len(payload),len(payload),0,0)+bytes(20)
        metadata=struct.pack('<Q',offset)+entry
        assert len(metadata)==56
        content.extend(metadata)
        content.extend(bytes(x^0xff for x in payload))
        records.append(fstring(name)+metadata)
    index=fstring('../../../JackGame/Content/')+struct.pack('<I',len(records))+b''.join(records)
    footer=struct.pack('<IIQQ20s',0x5a6f12e1,1,len(content),len(index),bytes(20))
    path.write_bytes(content+index+footer)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pwsh',type=Path,required=True)
    p.add_argument('--quickbms',type=Path,required=True)
    p.add_argument('--qemu',type=Path)
    a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='dqxi real PAK ;C ') as tmp:
        work=Path(tmp);pak=work/'Paks';pak.mkdir()
        chunk0='pakchunk0-WindowsNoEditor';chunk1='pakchunk1-WindowsNoEditor'
        make_pak(pak/(chunk0+'.pak'),{
            'JackGame/Content/Scenario/DT_A.uexp':b'JP-BASE',
            'JackGame/Content/L10N/en/Scenario/DT_A.uexp':b'EN-BASE',
            'JackGame/Content/L10N/fr/Scenario/DT_A.uexp':b'UNREQUESTED-FRENCH',
            'Other/JackGame/Content/Scenario/DT_A.uexp':b'UNREQUESTED-PREFIX',
            'JackGame/Content/Textures/Big.uasset':b'UNREQUESTED-TEXTURE'})
        make_pak(pak/(chunk0+'_0_P.pak'),{'Scenario/DT_A.uexp':b'JP-PATCH'})
        make_pak(pak/(chunk1+'.pak'),{'JackGame/Content/Sounds/Voice_NE/CS/Test.uexp':b'VOICE-BASE',
            'Sounds/Voice/CS/Test.uexp':b'UNREQUESTED-JAPANESE'})
        make_pak(pak/(chunk1+'_0_P.pak'),{'Sounds/Voice_NE/CS/Test.uexp':b'VOICE-PATCH'})
        assets=[dict(chunk=chunk0,path='JackGame/Content/Scenario/DT_A.uexp',kind='text',language='ja'),
                dict(chunk=chunk0,path='JackGame/Content/L10N/en/Scenario/DT_A.uexp',kind='text',language='en'),
                dict(chunk=chunk1,path='Sounds/Voice_NE/CS/Test.uexp',kind='voice',language='en')]
        manifest=work/'assets.json';manifest.write_text(json.dumps(dict(schema_version=3,voice_banks=1,text_table_files=2,
            additional_voice_files=0,additional_voice_banks=0,scene_map_files=0,scene_map_pairs=0,assets=assets)))
        command=([str(a.qemu.resolve())] if a.qemu else [])+[str(a.quickbms.resolve())]
        wrapper=work/'quickbms';wrapper.write_text('#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n');wrapper.chmod(0o700)
        script=(ROOT/'src/Extract-PCAssets.ps1').read_text(encoding='utf-8-sig')
        script=script.replace('3a248ab5f9f1dae7b999b4098cb623372ae29ebaefbb72f8c359cf3b72d2b5a7',hashlib.sha256(wrapper.read_bytes()).hexdigest())
        entry=work/'Extract-PCAssets.ps1';entry.write_text(script)
        out=work/'output'
        result=subprocess.run([a.pwsh,'-NoLogo','-NoProfile','-File',entry,'-PakRoot',pak,'-OutputRoot',out,
            '-QuickBmsPath',wrapper,'-BmsPath',ROOT/'tools/dqxi_pak_extract.bms','-ManifestPath',manifest],capture_output=True,text=True)
        if result.returncode:
            raise AssertionError(result.stdout+'\n'+result.stderr)
        extracted=out/'pc-extracted'
        for asset, expected in zip(assets,(b'JP-PATCH',b'EN-BASE',b'VOICE-PATCH')):
            assert (extracted/asset['chunk']/asset['path']).read_bytes()==expected
        assert len([p for p in extracted.rglob('*') if p.is_file()])==3
        report=json.loads((out/'pc-extraction-report.json').read_text(encoding='utf-8-sig'))
        assert report['selective_extraction'] and report['complete'] and report['unrequested_files_exported']==0
        # A valid, empty v3 update PAK is exactly 55 bytes, as in the user's
        # diagnostic. Zero exported files must preserve the base voice bank.
        index = fstring('/')+struct.pack('<I', 0)
        empty_patch = b'\0'+struct.pack('<IIQQ20s', 0x5a6f12e1, 3, 0, len(index), bytes(20))
        patch_path = pak/(chunk1+'_0_P.pak')
        patch_path.write_bytes(index+empty_patch)
        assert patch_path.stat().st_size == 55
        empty_out = work/'output-empty-patch'
        result=subprocess.run([a.pwsh,'-NoLogo','-NoProfile','-File',entry,'-PakRoot',pak,'-OutputRoot',empty_out,
            '-QuickBmsPath',wrapper,'-BmsPath',ROOT/'tools/dqxi_pak_extract.bms','-ManifestPath',manifest],capture_output=True,text=True)
        if result.returncode:
            raise AssertionError(result.stdout+'\n'+result.stderr)
        assert '0 files found' in result.stdout+result.stderr
        voice = empty_out/'pc-extracted'/chunk1/assets[2]['path']
        assert voice.read_bytes() == b'VOICE-BASE'
        report = json.loads((empty_out/'pc-extraction-report.json').read_text(encoding='utf-8-sig'))
        assert report['complete'] and report['extracted_assets'] == 3
        print('Real QuickBMS + DQXI BMS selective PAK test PASS: exact filters, language/prefix/texture exclusions, DQXI inversion, chunk mount variants and update precedence.')
        print('Empty 55-byte update PAK PASS: zero files is accepted and the required base voice is preserved.')


if __name__=='__main__':
    main()
