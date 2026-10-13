param(
    [Parameter(Mandatory=$true)][string]$PcRoot,
    [Parameter(Mandatory=$true)][string]$ExtractedPcRoot,
    [Parameter(Mandatory=$true)][string]$SceneEvents,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [switch]$KeepIntermediate
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$tools=Get-PCBuildTools -ToolCache $cache
$arguments=@('-I',(Join-Path $PSScriptRoot 'python/pc_movie_builder.py'),
    '--pc-root',$PcRoot,'--extracted-root',$ExtractedPcRoot,'--scene-events',$SceneEvents,
    '--output',$OutputRoot,'--decoder',$tools.vgmstream,'--ffmpeg',$tools.mobipeg,
    '--ffprobe',$tools.mobipeg_probe)
if($KeepIntermediate){$arguments+='--keep-intermediate'}
& $tools.python @arguments
if($LASTEXITCODE -ne 0){throw 'PC movie conversion failed. The installer did not create a complete mod.'}
$reportPath=Join-Path $OutputRoot 'movie-build-report.json'
if(!(Test-Path -LiteralPath $reportPath -PathType Leaf)){throw 'The PC movie conversion report was not created.'}
$report=Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if(!$report.complete -or $report.movie_count -ne 10){throw 'PC movie conversion did not produce all 10 verified MOFLEX files.'}
return $report
