param(
    [Parameter(Mandatory=$true)][string]$ExtractedPcRoot,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [switch]$ConvertVoices,
    [string]$ExtractionReport,
    [string]$PcRoot,
    [string]$OriginalRomfs
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$tools=Get-PCBuildTools -ToolCache $cache
$arguments=@('-I',(Join-Path $PSScriptRoot 'python/pc_components.py'),'--source',$ExtractedPcRoot,'--output',$OutputRoot)
$arguments+=@('--asset-manifest',(Join-Path $PSScriptRoot 'pc_asset_manifest.json'))
if($ExtractionReport){$arguments+=@('--extraction-report',$ExtractionReport)}
if($PcRoot -or $OriginalRomfs){
    if(!$PcRoot -or !$OriginalRomfs){throw 'PcRoot and OriginalRomfs must be provided together.'}
    $arguments+=@('--pc-root',$PcRoot,'--romfs',$OriginalRomfs)
}
if($ConvertVoices){$arguments+=@('--convert-voices','--decoder',$tools.vgmstream)}
& $tools.python @arguments
if($LASTEXITCODE -ne 0){throw 'PC component conversion failed. See the log for details.'}
