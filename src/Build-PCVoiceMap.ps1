[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PcTextRoot,
    [Parameter(Mandatory=$true)][string]$OutputFolder
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$tools=Get-PCBuildTools -ToolCache $cache
$script=Join-Path $PSScriptRoot 'python/voice_map_builder.py'
$arguments=@('-I',$script,'--pc-text-root',$PcTextRoot,'--output',$OutputFolder)
& $tools.python @arguments | Out-Null
$exit=$LASTEXITCODE
$reportPath=Join-Path $OutputFolder 'voice-map-report.json'
if($exit -notin @(0,2) -or !(Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw 'Die DQV4-Voice-Zuordnung konnte nicht gebaut werden; siehe Protokoll.'
}
$report=Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if($exit -eq 0 -and !$report.complete) {
    throw 'Der unvollstaendige DQV4-Voice-Map-Build wurde unerwartet als vollstaendig gemeldet.'
}
if($exit -eq 2 -or !$report.complete) {
    Write-Warning "Voice-Map ist unvollstaendig: $($report.assignments_mapped)/$($report.assignments_required) Zuordnungen. Sie ist nur ein Staging-Ergebnis und noch keine Soundbank-Integration."
}
Write-Output $report
