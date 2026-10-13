param(
    [string]$WorkFolder,
    [string]$PcRoot = 'C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S',
    [switch]$ConvertVoices
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
if(!$WorkFolder){$WorkFolder=Read-Host 'Existing DQXI build working folder'}
$WorkFolder=[IO.Path]::GetFullPath($WorkFolder.Trim('"'))
Assert-DQXIPathNoReparse $WorkFolder
$source=Join-Path $WorkFolder 'pc-assets/pc-extracted'
$report=Join-Path $WorkFolder 'pc-assets/pc-extraction-report.json'
if(!(Test-Path -LiteralPath $source -PathType Container) -or !(Test-Path -LiteralPath $report -PathType Leaf)){
    throw 'Completed PC extraction was not found. Select the build working folder, not the installer folder.'
}
Assert-DQXIPathNoReparse $source;Assert-DQXIPathNoReparse $report
if(!(Test-Path -LiteralPath $PcRoot -PathType Container)){
    $PcRoot=(Read-Host 'Root folder of the DQXI S PC installation').Trim('"')
}
$romfs=Join-Path $WorkFolder 'original-3ds/romfs'
if(!(Test-Path -LiteralPath $PcRoot -PathType Container) -or !(Test-Path -LiteralPath $romfs -PathType Container)){
    throw 'The PC installation or original ROMFS folder was not found.'
}
Assert-DQXIPathNoReparse $PcRoot;Assert-DQXIPathNoReparse $romfs
# A fresh output preserves both partial old exports and the original sources.
$name='pc-components-v6-'+[Guid]::NewGuid().ToString('N')
$output=Join-Path $WorkFolder $name
Write-Output 'Reusing existing PC exports. The CIA and PAK files will not be extracted again.'
& (Join-Path $PSScriptRoot 'Convert-PCComponents.ps1') -ExtractedPcRoot $source -OutputRoot $output -ExtractionReport $report -PcRoot $PcRoot -OriginalRomfs $romfs -ConvertVoices:$ConvertVoices
Write-Output "Current component report: $(Join-Path $output 'component-report.json')"
Write-Output 'Afterward, run Collect-Diagnostics.cmd with the same build working folder.'
