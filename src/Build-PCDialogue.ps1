param(
    [Parameter(Mandatory=$true)][string]$OriginalRomfs,
    [Parameter(Mandatory=$true)][string]$PcTextRoot,
    [Parameter(Mandatory=$true)][string]$OutputRoot
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$tools=Get-PCBuildTools -ToolCache $cache
$script=Join-Path $PSScriptRoot 'python/pc_dialogue_build.py'
$recipe=Join-Path $PSScriptRoot 'recipes/pc_dialogue_map.json'
$arguments=@('-I',$script,'--original-romfs',$OriginalRomfs,'--pc-text-root',$PcTextRoot,
             '--recipe',$recipe,'--output-root',$OutputRoot)
& $tools.python @arguments | Out-Null
$exit=$LASTEXITCODE
$reportPath=Join-Path $OutputRoot 'dialogue-build-report.json'
if($exit -notin @(0,2) -or !(Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw 'Der PC-Dialogaufbau ist technisch fehlgeschlagen; siehe Protokoll.'
}
$report=Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if($exit -eq 0 -and !$report.complete) { throw 'Der unvollstaendige PC-Dialogaufbau wurde unerwartet als vollstaendig gemeldet.' }
Write-Output $report
