"""Test pinned executable downloads and migration of a pre-existing tool cache.

Use official local Windows downloads as network responses; no tools are executed.
Requires PowerShell, but no separately compiled helper assembly.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def literal(value):
    return "'"+str(value).replace("'", "''")+"'"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for option in ('pwsh','3dstool-zip','rom-converto-exe','vclibs-appx'):
        p.add_argument('--'+option, required=True, type=Path)
    a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='dqxi tool cache ;C ') as tmp:
        script=f'''$ErrorActionPreference='Stop'
. {literal(ROOT/'src/Get-3DSBuildTools.ps1')}
$cache={literal(Path(tmp)/'tools')}
$zip={literal(a.__dict__['3dstool_zip'].resolve())}
$rom={literal(a.rom_converto_exe.resolve())}
$runtime={literal(a.vclibs_appx.resolve())}
$script:downloads=0
function Invoke-WebRequest {{
 param([switch]$UseBasicParsing,$Uri,$OutFile,$TimeoutSec)
 $script:downloads++
 if($Uri.EndsWith('3dstool.zip')){{Copy-Item -LiteralPath $zip -Destination $OutFile}}
 elseif($Uri.EndsWith('rom-converto-cli-windows-x64.exe')){{Copy-Item -LiteralPath $rom -Destination $OutFile}}
 elseif($Uri.EndsWith('Microsoft.VCLibs.x64.14.00.Desktop.appx')){{Copy-Item -LiteralPath $runtime -Destination $OutFile}}
 else{{throw 'Unexpected network request'}}
}}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$old=Join-Path $cache '3dstool-1.2.6';New-Item -ItemType Directory -Path $old -Force|Out-Null
$archive=[IO.Compression.ZipFile]::OpenRead($zip)
try{{$entry=@($archive.Entries|Where-Object {{$_.Name -eq '3dstool.exe'}})[0]
 [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,(Join-Path $old '3dstool.exe'))
}}finally{{$archive.Dispose()}}
$tool=Get-3DSBuildTool -Name 3dstool -ToolCache $cache
if(!(Test-Path -LiteralPath (Join-Path $old 'ext_key.txt')) -or $script:downloads -ne 1){{throw 'Old cache companion migration failed'}}
[void](Get-3DSBuildTool -Name 3dstool -ToolCache $cache)
if($script:downloads -ne 1){{throw 'Valid cache downloaded again'}}
[void](Get-3DSBuildTool -Name rom-converto -ToolCache $cache)
[void](Get-3DSBuildTool -Name rom-converto -ToolCache $cache)
if($script:downloads -ne 3){{throw 'Raw executable/runtime cache failed'}}
foreach($name in @('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')){{
 if(!(Test-Path -LiteralPath (Join-Path $cache ('rom-converto-0.23.2/'+$name)))){{throw 'Private runtime DLL missing'}}
}}
[IO.File]::AppendAllText((Join-Path $old 'ext_key.txt'),'corrupt')
$rejected=$false
try{{[void](Get-3DSBuildTool -Name 3dstool -ToolCache $cache)}}catch{{$rejected=$true}}
if(!$rejected){{throw 'Changed companion accepted'}}
Write-Output 'Tool cache PASS: companion migration, pinned standalone rom-converto and private runtime DLLs, valid cache reuse, modified companion rejection.'
'''
        file=Path(tmp)/'test.ps1';file.write_text(script)
        result=subprocess.run([a.pwsh,'-NoLogo','-NoProfile','-File',file],capture_output=True,text=True)
        if result.returncode:
            raise AssertionError(result.stdout+'\n'+result.stderr)
        print(result.stdout.strip())


if __name__=='__main__':
    main()
