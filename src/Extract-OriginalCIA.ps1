param(
    [Parameter(Mandatory=$true)][string]$OriginalCia,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [switch]$KeepIntermediate
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Load-NativeBackend.ps1')
. (Join-Path $PSScriptRoot 'Get-3DSBuildTools.ps1')
Initialize-DQXINativeBackend
$cancel = [Threading.CancellationToken]::None
# Structural title validation precedes downloads and extraction.
Write-Host 'Checking CIA metadata and required 3DS extraction tools...'
[void][CiaSupport]::ValidateOriginal($OriginalCia,$cancel)
$cache = Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$ctrtool = Get-3DSBuildTool -Name ctrtool -ToolCache $cache
$threeDstool = Get-3DSBuildTool -Name 3dstool -ToolCache $cache
$romConverto = Get-3DSBuildTool -Name rom-converto -ToolCache $cache
Write-Host 'Extracting CIA contents and decrypting encrypted game regions...'
try {
    $source = [CiaSupport]::ExtractOriginal($OriginalCia,$OutputRoot,$ctrtool,$threeDstool,$romConverto,$cancel,(!$KeepIntermediate.IsPresent))
} catch {
    $reason=$_.Exception.GetBaseException().Message
    if(Test-Path -LiteralPath $OutputRoot -PathType Container){
        [BuildSupport]::NoReparse($OutputRoot)
        [ordered]@{schema_version=1;stage='cia-extraction';success=$false;input_hash_check=$false
            error=$reason;log=(Join-Path $OutputRoot 'extract.log');ncch_decryption='rom-converto 0.23.2, title seed from official 3dstool companion'
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputRoot 'cia-extraction-error.json') -Encoding UTF8
    }
    throw "CIA extraction failed: $reason Details: $(Join-Path $OutputRoot 'extract.log')"
}
Write-Host ("ROMFS extraction complete: {0} files, {1:N0} bytes." -f $source.RomFsFileCount,$source.RomFsTotalBytes)
[ordered]@{
    schema_version=1;title_id='0004000000199200';source_cia=[IO.Path]::GetFullPath($OriginalCia)
    fixed_input_hash_check=$false;input_hash_check=$false;title_version=$source.TitleVersion
    ncch_regions_decrypted_before_layout_check=$true
    cia_decryption='CTRTool CIA layer; rom-converto NCCH game/manual regions when encrypted'
    headers_from_user_cia=$true
    romfs_file_count=$source.RomFsFileCount;romfs_total_bytes=$source.RomFsTotalBytes
    root=$source.Root;game_path=$source.GamePath;contents=@($source.Contents)
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $source.Root 'cia-extraction-report.json') -Encoding UTF8
return $source
