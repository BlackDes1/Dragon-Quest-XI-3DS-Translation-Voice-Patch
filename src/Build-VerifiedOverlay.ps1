param(
    [Parameter(Mandatory=$true)][string]$OriginalRomfs,
    [Parameter(Mandatory=$true)][string]$VoiceRoot,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [string]$CodeIps,
    [Parameter(Mandatory=$true)][string]$MovieRoot,
    [Parameter(Mandatory=$true)][string]$PcRoot
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$tools=Get-PCBuildTools -ToolCache $cache
if(!$CodeIps){$CodeIps=Join-Path (Split-Path $PSScriptRoot -Parent) 'code.ips'}
$inputs=Join-Path $PSScriptRoot 'verified-inputs'
if(!(Test-Path -LiteralPath (Join-Path $MovieRoot 'movie-build-report.json') -PathType Leaf)){
    throw 'The converted PC movie set and its verification report are required.'
}
$arguments=@('-I',(Join-Path $PSScriptRoot 'python/verified_overlay.py'),
    '--original-romfs',$OriginalRomfs,'--inputs',$inputs,'--output',$OutputRoot,
    '--code-ips',$CodeIps,'--voice-root',$VoiceRoot,'--movie-root',$MovieRoot,'--pc-root',$PcRoot)
& $tools.python @arguments | Out-Host
if($LASTEXITCODE -ne 0){throw 'The verified build failed. No incomplete mod was released.'}
$report=Get-Content -LiteralPath (Join-Path $OutputRoot 'build-report.json') -Raw | ConvertFrom-Json
if(!$report.complete){throw 'Media or resource validation is incomplete.'}
Write-Output $report
