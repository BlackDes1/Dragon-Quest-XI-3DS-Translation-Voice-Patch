# Paths are relative to the selected PC root. Presence is not a content checksum.
. (Join-Path $PSScriptRoot 'Common.ps1')
$script:DefaultPcRoot = 'C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S'

function Test-DQXIPcInstallation {
    param([string]$PcRoot = $script:DefaultPcRoot)
    $PcRoot = [IO.Path]::GetFullPath($PcRoot)
    if (!(Test-Path -LiteralPath $PcRoot -PathType Container)) {
        throw "PC installation folder not found: $PcRoot"
    }
    Assert-DQXIPathNoReparse $PcRoot
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'pc_installation_manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.game -ne 'DQXI S' -or $manifest.required_files.Count -ne 78 -or $manifest.required_directories.Count -ne 99) {
        throw 'The PC file list is missing or damaged.'
    }
    $rootPrefix = $PcRoot.TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $attributesByPath = New-Object 'System.Collections.Generic.Dictionary[string,System.IO.FileAttributes]' ([StringComparer]::OrdinalIgnoreCase)
    function Get-DQXIPcManifestPath([string]$Relative,[string]$Root,[string]$RootPrefix,$AttributeCache) {
        Assert-DQXISafeName $Relative
        $candidate = [IO.Path]::GetFullPath((Join-Path $Root ($Relative.Replace('/',[IO.Path]::DirectorySeparatorChar))))
        if (!$candidate.StartsWith($RootPrefix,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'PC file manifest path escapes the selected installation.'
        }
        $current = $candidate
        while ($current -and $current.StartsWith($RootPrefix,[StringComparison]::OrdinalIgnoreCase)) {
            if (!$AttributeCache.ContainsKey($current)) {
                try {
                    $attributes = [IO.File]::GetAttributes($current)
                    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                        throw "Linked filesystem paths are not permitted: $current"
                    }
                    $AttributeCache.Add($current,$attributes)
                } catch [IO.FileNotFoundException] {
                    # Keep walking: a higher ancestor may still be a link.
                } catch [IO.DirectoryNotFoundException] {
                    # Keep walking: a higher ancestor may still be a link.
                }
            }
            $parent = [IO.Path]::GetDirectoryName($current)
            if (!$parent -or $parent -eq $current) { break }
            $current = $parent
        }
        return $candidate
    }
    $missing = New-Object 'System.Collections.Generic.List[string]'
    foreach ($relative in $manifest.required_directories) {
        $relativePath = [string]$relative
        $path = Get-DQXIPcManifestPath $relativePath $PcRoot $rootPrefix $attributesByPath
        if (!$attributesByPath.ContainsKey($path) -or
            ($attributesByPath[$path] -band [IO.FileAttributes]::Directory) -eq 0) {
            $missing.Add($relativePath + '/')
        }
    }
    foreach ($relative in $manifest.required_files) {
        $relativePath = [string]$relative
        $path = Get-DQXIPcManifestPath $relativePath $PcRoot $rootPrefix $attributesByPath
        if (!$attributesByPath.ContainsKey($path) -or
            ($attributesByPath[$path] -band [IO.FileAttributes]::Directory) -ne 0 -or
            ([IO.FileInfo]::new($path).Length -eq 0)) {
            $missing.Add($relativePath)
        }
    }
    return [pscustomobject]@{
        root = $PcRoot
        required_files = $manifest.required_files.Count
        required_directories = $manifest.required_directories.Count
        missing_or_empty = @($missing.ToArray())
        valid = ($missing.Count -eq 0)
        verification = 'File and directory presence and nonzero file size; no fixed PC asset hash checks by user request'
    }
}

function Assert-DQXIPcInstallation {
    param([string]$PcRoot = $script:DefaultPcRoot)
    $result = Test-DQXIPcInstallation -PcRoot $PcRoot
    if (!$result.valid) { throw ("PC installation is incomplete. Missing or empty files:`r`n" + ($result.missing_or_empty -join "`r`n")) }
    return $result
}
