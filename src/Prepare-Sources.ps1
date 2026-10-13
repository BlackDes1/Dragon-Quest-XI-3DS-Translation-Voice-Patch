param(
    [Parameter(Mandatory=$true)][string]$OriginalCia,
    [string]$CodeIps,
    [string]$PcRoot = 'C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S',
    [Parameter(Mandatory=$true)][string]$OutputFolder,
    [ValidateSet('layeredfs','cia')][string]$Format = 'layeredfs',
    [switch]$Resume,
    [switch]$KeepIntermediate
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Test-GameSources.ps1')
. (Join-Path $PSScriptRoot 'CodeIps.ps1')
if (!$CodeIps) { $CodeIps = Join-Path (Split-Path $PSScriptRoot -Parent) 'code.ips' }
function Release-DQXIIntermediate([string]$Phase) {
    if($KeepIntermediate){return}
    . (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
    $storageTools=Get-PCBuildTools -ToolCache (Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools')
    & $storageTools.python '-I' (Join-Path $PSScriptRoot 'python/build_storage.py') '--build-root' $OutputFolder '--phase' $Phase '--format' $Format
    if($LASTEXITCODE -ne 0){throw 'Intermediate storage validation failed. Existing outputs and diagnostics were retained.'}
}
$OutputFolder=[IO.Path]::GetFullPath($OutputFolder)
Assert-DQXIPathNoReparse $OutputFolder
if ((Test-DQXIPathOverlap $PcRoot $OutputFolder) -or (Test-DQXIPathOverlap $OutputFolder $OriginalCia) -or (Test-DQXIPathOverlap $OutputFolder $CodeIps)) {
    throw 'The output folder must be outside the PC installation, original CIA and code patch file.'
}
if ($Resume) {
    if (!(Test-Path -LiteralPath $OutputFolder -PathType Container)) { throw 'Select the existing build folder to resume.' }
} elseif (Test-Path -LiteralPath $OutputFolder) { throw 'Choose a new output folder.' }
$codeIpsInfo=Get-DQXICurrentCodeIpsInfo $CodeIps
Write-Output 'Validating the complete PC file list...'
$pc=Assert-DQXIPcInstallation -PcRoot $PcRoot
Write-Output ("PC validation complete: {0} files and {1} folders checked." -f $pc.required_files,$pc.required_directories)
Write-Output 'Validating the CIA title ID and structure...'
[void](Get-DQXITitleInfo $OriginalCia)
Write-Output 'CIA metadata validation complete.'
# Only after both inputs passed validation are tools fetched and originals extracted.
$ciaRoot=Join-Path $OutputFolder 'original-3ds'
$resumeReport=$null
if ($Resume) {
    Write-Output 'Checking existing sources before resuming movie conversion...'
    . (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
    $tools=Get-PCBuildTools -ToolCache (Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools')
    $resumeReportPath=Join-Path $OutputFolder 'resume-source-checks.json'
    & $tools.python '-I' (Join-Path $PSScriptRoot 'python/resume_build.py') '--build-root' $OutputFolder '--original-cia' $OriginalCia '--pc-root' $PcRoot '--report' $resumeReportPath
    if ($LASTEXITCODE -ne 0) { throw 'The existing sources could not be verified. See the resume log above.' }
    $resumeReport=Get-Content -LiteralPath $resumeReportPath -Raw | ConvertFrom-Json
    $source=[pscustomobject]@{RomFsFileCount=$resumeReport.romfs_files;RomFsTotalBytes=$resumeReport.romfs_bytes}
    Write-Output 'Reusing CIA extraction, PC export and completed gameplay voices.'
} else {
    New-DQXIExclusiveDirectory $OutputFolder
    Write-Output 'Extracting your CIA and preparing headers, ROMFS and ExeFS...'
    $source=& (Join-Path $PSScriptRoot 'Extract-OriginalCIA.ps1') -OriginalCia $OriginalCia -OutputRoot $ciaRoot -KeepIntermediate:$KeepIntermediate
    Release-DQXIIntermediate 'extraction'
    Write-Output 'Extracting selected English PC text and voice assets...'
    & (Join-Path $PSScriptRoot 'Extract-PCAssets.ps1') -PakRoot (Join-Path $PcRoot 'Game/Content/Paks') -OutputRoot (Join-Path $OutputFolder 'pc-assets')
    Write-Output 'Converting all 5,048 verified voice clips from your PC files...'
    & (Join-Path $PSScriptRoot 'Convert-PCComponents.ps1') -ExtractedPcRoot (Join-Path $OutputFolder 'pc-assets/pc-extracted') -OutputRoot (Join-Path $OutputFolder 'pc-components') -PcRoot $PcRoot -OriginalRomfs (Join-Path $ciaRoot 'romfs') -ConvertVoices
}
Write-Output 'Finding and converting the 10 English PC movies from Game/Content/Movies...'
$movieOutput=Join-Path $OutputFolder 'pc-movies'
if ($Resume -and $resumeReport.complete_movie_package) {
    $movieReport=$resumeReport.movie_report
    Write-Output 'Reusing the complete, checksum-verified movie package.'
} else {
    $movieReport=& (Join-Path $PSScriptRoot 'Convert-PCMovies.ps1') -PcRoot $PcRoot -ExtractedPcRoot (Join-Path $OutputFolder 'pc-assets/pc-extracted') -SceneEvents (Join-Path $OutputFolder 'pc-components/pc-scenes/scene-events.json') -OutputRoot $movieOutput -KeepIntermediate:$KeepIntermediate
}
if(!$movieReport.complete){throw 'The PC movie conversion is incomplete.'}
Write-Output 'Building dialogue, 50 additional voice cases, menus and the 10 converted movies...'
$modOutput=Join-Path $OutputFolder 'Mod'
$buildReport=& (Join-Path $PSScriptRoot 'Build-VerifiedOverlay.ps1') -OriginalRomfs (Join-Path $ciaRoot 'romfs') -VoiceRoot (Join-Path $OutputFolder 'pc-components/voice-components') -OutputRoot $modOutput -CodeIps $CodeIps -MovieRoot $movieOutput -PcRoot $PcRoot
if(!$buildReport.complete){throw 'The build is incomplete.'}
Copy-Item -LiteralPath (Join-Path $movieOutput 'movie-build-report.json') -Destination (Join-Path $modOutput 'movie-build-report.json')
Release-DQXIIntermediate 'overlay'
$containerGenerated=$false
if($Format -eq 'cia'){
    & (Join-Path $PSScriptRoot 'Build-3DSContainer.ps1') -OriginalCia $OriginalCia -GeneratedMod $modOutput -OutputFolder (Join-Path $OutputFolder 'cia') -Format cia -PreparedOriginalRoot $ciaRoot -KeepIntermediate:$KeepIntermediate
    $containerGenerated=$true
}
$finalOutput=if($Format -eq 'cia'){Join-Path $OutputFolder 'cia'}else{$modOutput}
Release-DQXIIntermediate 'complete'
$retainedMod=if($Format -eq 'layeredfs' -or $KeepIntermediate){$modOutput}else{$null}
$finalBuildReport=if($KeepIntermediate){Join-Path $modOutput 'build-report.json'}else{Join-Path $OutputFolder 'reports/build-report.json'}
$finalMovieReport=if($KeepIntermediate){Join-Path $movieOutput 'movie-build-report.json'}else{Join-Path $OutputFolder 'reports/movie-build-report.json'}
[ordered]@{
    schema_version=3;release='v18';installer_revision='2026-10-13-compact-storage';pc=$pc;source_cia=[IO.Path]::GetFullPath($OriginalCia)
    resumed_movie_build=[bool]$Resume
    upstream_kenzie='0.7.0';dialogue_line_wrap_fixes=58
    requested_format=$Format;sources_prepared=$true;mod_generated=$true
    build_output_generated=$true;cia_generated=$containerGenerated
    original_romfs=[ordered]@{files=$source.RomFsFileCount;total_bytes=$source.RomFsTotalBytes}
    final_output_directory=$finalOutput;final_output_file=$(if($Format -eq 'cia'){Join-Path $finalOutput 'DQXI-S-3DS.cia'}else{$null})
    intermediate_files_retained=[bool]$KeepIntermediate
    mod_root=$retainedMod;build_report=$finalBuildReport
    movie_build_report=$finalMovieReport
    code_ips_sha256=$codeIpsInfo.Sha256;gameplay_tested=$false
    coverage=[ordered]@{
        dialogue=[ordered]@{known_targets=5551;rows_written=$buildReport.dialogue_rows_written}
        voice=[ordered]@{expected_runtime_links=5095;links=$buildReport.voice_runtime_links;new_cases=50;native_lookup_rows=$buildReport.native_lookup_rows;files=$buildReport.voice_files_copied;format='DQV4/32';pool_slots=6}
        ui=[ordered]@{pc_targets=2920;rows_written=$buildReport.pc_ui_rows_written;reviewed_menu_rows=$buildReport.reviewed_menu_rows_written}
        movies=[ordered]@{known_targets=10;copied=$buildReport.movies_copied;later_movies_gameplay_tested=$false}
        kenzie_area_title_assets=[ordered]@{
            applied=$buildReport.kenzie_area_title_assets_applied
            skipped=$buildReport.kenzie_area_title_assets_skipped
        }
    }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputFolder 'source-preparation-report.json') -Encoding UTF8
Write-Output ("Build complete. Finished output: {0}" -f $finalOutput)
