param(
    [Parameter(Mandatory=$true)][string]$PakRoot,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [string]$QuickBmsPath,
    [string]$BmsPath,
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
$expectedQuickBmsSha256 = '3a248ab5f9f1dae7b999b4098cb623372ae29ebaefbb72f8c359cf3b72d2b5a7'
$expectedBmsSha256 = '7cff0ac7058740c3e7873ab35a279702b5c64e78d774f9c8a519d29dfe05f04e'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (!$QuickBmsPath) { $QuickBmsPath = Join-Path $projectRoot 'tools\quickbms_4gb_files.exe' }
if (!$BmsPath) { $BmsPath = Join-Path $projectRoot 'tools\dqxi_pak_extract.bms' }
if (!$ManifestPath) { $ManifestPath = Join-Path $PSScriptRoot 'pc_asset_manifest.json' }

foreach ($file in @($QuickBmsPath,$BmsPath,$ManifestPath)) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required extraction file not found: $file" }
}
if ((Get-FileHash -LiteralPath $QuickBmsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedQuickBmsSha256) {
    throw 'QuickBMS executable hash differs from the bundled version.'
}
if ((Get-FileHash -LiteralPath $BmsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedBmsSha256) {
    throw 'DQXI BMS script hash differs from the audited version.'
}
if (!(Test-Path -LiteralPath $PakRoot -PathType Container)) { throw "PC PAK folder not found: $PakRoot" }

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$expectedAssets = [int]$manifest.voice_banks + [int]$manifest.text_table_files +
    [int]$manifest.additional_voice_files + [int]$manifest.scene_map_files
if ($manifest.schema_version -ne 3 -or !$manifest.assets -or $manifest.assets.Count -ne $expectedAssets) {
    throw 'PC asset manifest is missing, malformed, or has an unexpected asset count.'
}
$kindCounts=@{}
foreach($kind in @('voice','text','voice_extra','scene')){
    $kindCounts[$kind]=@($manifest.assets|Where-Object{$_.kind -eq $kind}).Count
}
if($kindCounts.voice -ne $manifest.voice_banks -or $kindCounts.text -ne $manifest.text_table_files -or
   $kindCounts.voice_extra -ne $manifest.additional_voice_files -or $kindCounts.scene -ne $manifest.scene_map_files -or
   $manifest.additional_voice_files -ne 2*$manifest.additional_voice_banks -or
   $manifest.scene_map_files -ne 2*$manifest.scene_map_pairs){
    throw 'PC asset manifest counts or paired source records do not match.'
}
function Assert-AssetPairs([object[]]$assets,[string]$kind,[string]$firstExtension,[string]$secondExtension,[int]$expectedPairs){
    $pairs=@{}
    foreach($asset in $assets|Where-Object{$_.kind -eq $kind}){
        $path=[string]$asset.path;$extension=[IO.Path]::GetExtension($path).ToLowerInvariant()
        if($extension -notin @($firstExtension,$secondExtension)){throw "Unexpected $kind companion extension: $path"}
        $base=[IO.Path]::ChangeExtension($path,'').ToLowerInvariant()
        if(!$pairs.ContainsKey($base)){$pairs[$base]=@{}}
        if($pairs[$base].ContainsKey($extension)){throw "Duplicate $kind companion: $path"}
        $pairs[$base][$extension]=$true
    }
    if($pairs.Count -ne $expectedPairs){throw "Unexpected $kind pair count."}
    foreach($base in $pairs.Keys){
        if(!$pairs[$base].ContainsKey($firstExtension) -or !$pairs[$base].ContainsKey($secondExtension)){
            throw "Incomplete $kind companion pair: $base"
        }
    }
}
Assert-AssetPairs @($manifest.assets) 'voice_extra' '.uasset' '.uexp' ([int]$manifest.additional_voice_banks)
Assert-AssetPairs @($manifest.assets) 'scene' '.umap' '.uexp' ([int]$manifest.scene_map_pairs)
$seenAssets=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach($asset in $manifest.assets){
    if($asset.chunk -notin @('pakchunk0-WindowsNoEditor','pakchunk1-WindowsNoEditor') -or
       $asset.kind -notin @('voice','text','voice_extra','scene') -or
       [string]$asset.path -notmatch '^[A-Za-z0-9_./-]+$' -or [string]$asset.path -match '(^|/)\.\.(/|$)' -or
       !$seenAssets.Add($asset.chunk+'/'+$asset.path)){throw 'Unsafe or duplicate extraction recipe.'}
}
function Get-CanonicalAssetPath([string]$path){
    $tail=$path.Replace('\','/') -replace '^JackGame/Content/',''
    return 'JackGame/Content/'+$tail
}

$resolvedPakRoot = (Resolve-Path -LiteralPath $PakRoot).Path
$resolvedOutput = [IO.Path]::GetFullPath($OutputRoot)
function Is-PathWithin([string]$child,[string]$parent) {
    $parentFull = [IO.Path]::GetFullPath($parent).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $childFull = [IO.Path]::GetFullPath($child).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    return $childFull.StartsWith($parentFull,[StringComparison]::OrdinalIgnoreCase)
}
if ((Is-PathWithin $resolvedOutput $resolvedPakRoot) -or (Is-PathWithin $resolvedPakRoot $resolvedOutput)) {
    throw 'Choose an extraction output folder that does not overlap the PC installation.'
}
if (!(Test-Path -LiteralPath $resolvedOutput)) { New-Item -ItemType Directory -Path $resolvedOutput | Out-Null }
elseif ((Get-ChildItem -LiteralPath $resolvedOutput -Force | Measure-Object).Count -ne 0) { throw 'Choose an empty extraction output folder.' }
$staging = Join-Path $resolvedOutput ('.pc-extract-'+[guid]::NewGuid().ToString('N'))
$extractRoot = Join-Path $staging 'pc-extracted'
New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

$chunkNames = @('pakchunk0-WindowsNoEditor','pakchunk1-WindowsNoEditor')
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('dqxi_filters_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$results = New-Object 'System.Collections.Generic.List[object]'
try {
    foreach ($chunk in $chunkNames) {
        $pak = Join-Path $resolvedPakRoot ($chunk + '.pak')
        if (!(Test-Path -LiteralPath $pak -PathType Leaf)) { throw "Required PC archive missing: $pak" }
        $assets = @($manifest.assets | Where-Object { $_.chunk -eq $chunk })
        if ($assets.Count -eq 0) { throw "No manifest entries for $chunk" }
        Write-Output ("Scanning {0} PAK layers for {1} selected files..." -f $chunk,$assets.Count)
        $filter = Join-Path $temporary ($chunk + '.txt')
        $filterLines = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $allowedPaths=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($asset in $assets) {
            $path = [string]$asset.path
            if ([IO.Path]::IsPathRooted($path) -or $path -match '(^|[\\/])\.\.([\\/]|$)' -or $path -match '[\r\n]') {
                throw "Unsafe path in asset manifest: $path"
            }
            # Enumerate complete mount variants. No prefix/suffix wildcards:
            # L10N/fr/Scenario/X must never match the Japanese Scenario/X.
            $canonical=Get-CanonicalAssetPath $path
            $tail=$canonical.Substring('JackGame/Content/'.Length)
            [void]$filterLines.Add($canonical);[void]$filterLines.Add($tail)
            [void]$allowedPaths.Add($canonical)
        }
        [IO.File]::WriteAllLines($filter,$filterLines,[Text.Encoding]::ASCII)
        $chunkOutput = Join-Path $extractRoot $chunk
        New-Item -ItemType Directory -Path $chunkOutput | Out-Null

        # Normalise each layer separately, so a patch with a different mount
        # point still overrides its base resource after canonicalisation.
        $layer=0
        foreach($inputPak in @($pak,(Join-Path $resolvedPakRoot ($chunk+'_0_P.pak')))) {
            if (!(Test-Path -LiteralPath $inputPak -PathType Leaf)) { continue }
            $pakOutput=Join-Path $staging ($chunk+'-layer-'+$layer)
            New-Item -ItemType Directory -Path $pakOutput | Out-Null
            & $QuickBmsPath '-o' '-f' $filter $BmsPath $inputPak $pakOutput
            $exit = $LASTEXITCODE
            if ($exit -ne 0) { throw "QuickBMS failed for $inputPak (exit code $exit)." }
            $layerFiles=@(Get-ChildItem -LiteralPath $pakOutput -Recurse -File)
            $layerPrefix=[IO.Path]::GetFullPath($pakOutput).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
            $actualPaths=@{}
            foreach($extracted in $layerFiles){
                if(($extracted.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Link in extracted PC data.'}
                $relative=$extracted.FullName.Substring($layerPrefix.Length).Replace('\','/')
                $canonical=Get-CanonicalAssetPath $relative
                if(!$allowedPaths.Contains($canonical)){throw "QuickBMS exported an unrequested PC file: $relative"}
                if($actualPaths.ContainsKey($canonical)){throw "Extracted PC asset is ambiguous: $canonical"}
                $actualPaths[$canonical]=$extracted.FullName
            }
            foreach($asset in $assets) {
                $canonical=Get-CanonicalAssetPath ([string]$asset.path)
                if(!$actualPaths.ContainsKey($canonical)){continue}
                $candidate=$actualPaths[$canonical]
                $expected=Join-Path $chunkOutput ($asset.path -replace '/', '\')
                New-Item -ItemType Directory -Path (Split-Path -Parent $expected) -Force | Out-Null
                Copy-Item -LiteralPath $candidate -Destination $expected -Force
            }
            $layer++
        }

        foreach ($asset in $assets) {
            $expected = Join-Path $chunkOutput ($asset.path -replace '/', '\')
            if (!(Test-Path -LiteralPath $expected -PathType Leaf)) {
                throw "Extracted PC asset is missing: $($asset.chunk)/$($asset.path)"
            }
            $file = Get-Item -LiteralPath $expected
            if($file.Length -eq 0){throw "Empty PC asset: $($asset.path)"}
            $results.Add([ordered]@{chunk=$asset.chunk;path=$asset.path;bytes=$file.Length})
        }
        Write-Output ("Validated {0}/{1} selected PC files." -f $results.Count,$manifest.assets.Count)
    }
    $report = [ordered]@{
        schema_version=1
        source='User-selected DQXI S PC installation'
        required_assets=$manifest.assets.Count
        extracted_assets=$results.Count
        voice_banks=$manifest.voice_banks
        additional_voice_banks=$manifest.additional_voice_banks
        additional_voice_files=$manifest.additional_voice_files
        text_table_files=$manifest.text_table_files
        scene_map_files=$manifest.scene_map_files
        scene_map_pairs=$manifest.scene_map_pairs
        movie_event_scene_map_pairs=7
        update_paks_override_base=$true
        selective_extraction=$true
        unrequested_files_exported=0
        extraction_scope='Text tables, existing voice banks, supplemental voice-bank pairs and scene-event maps (including seven movie-event maps); movie USMs are loose PC files'
        full_mod_dependency_plan_complete=$false
        complete=($results.Count -eq $manifest.assets.Count)
        extracted_root=$extractRoot
        assets=$results.ToArray()
        created_utc=[DateTime]::UtcNow.ToString('o')
    }
    Move-Item -LiteralPath $extractRoot -Destination (Join-Path $resolvedOutput 'pc-extracted')
    $report.extracted_root = Join-Path $resolvedOutput 'pc-extracted'
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resolvedOutput 'pc-extraction-report.json') -Encoding UTF8
    Write-Output "PC data extraction complete: $($results.Count)/$($manifest.assets.Count) required files."
    Write-Output "Output: $($report.extracted_root)"
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
}
