$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$script:CurrentDQXICodeIpsSha256 = '41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf'

function Get-DQXICurrentCodeIpsInfo([string]$Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'The current code.ips was not found.'
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    Assert-DQXIPathNoReparse $fullPath
    $bytes = [IO.File]::ReadAllBytes($fullPath)
    if ($bytes.Length -lt 8) { throw 'The code.ips file is too short.' }
    if ([Text.Encoding]::ASCII.GetString($bytes, 0, 5) -ne 'PATCH') {
        throw 'The selected file does not have an IPS header.'
    }
    if ([Text.Encoding]::ASCII.GetString($bytes, $bytes.Length - 3, 3) -ne 'EOF') {
        throw 'The IPS end marker EOF is missing.'
    }
    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $script:CurrentDQXICodeIpsSha256) {
        throw "This is not the approved mod code patch. Expected SHA-256: $script:CurrentDQXICodeIpsSha256"
    }

    $position = 5
    $endMarker = $bytes.Length - 3
    $recordCount = 0
    [long]$patchedBytes = 0
    [long]$highestOffset = 0
    while ($position -lt $endMarker) {
        if (($endMarker - $position) -lt 5) { throw 'An IPS record is incomplete.' }
        $offset = ([long]$bytes[$position] -shl 16) -bor ([long]$bytes[$position + 1] -shl 8) -bor [long]$bytes[$position + 2]
        $size = ([int]$bytes[$position + 3] -shl 8) -bor [int]$bytes[$position + 4]
        $position += 5
        if ($size -eq 0) {
            if (($endMarker - $position) -lt 3) { throw 'An IPS RLE record is incomplete.' }
            $runLength = ([int]$bytes[$position] -shl 8) -bor [int]$bytes[$position + 1]
            if ($runLength -le 0) { throw 'An IPS RLE record has a zero length.' }
            $position += 3
            $payloadLength = $runLength
        } else {
            if (($endMarker - $position) -lt $size) { throw 'An IPS record exceeds the file bounds.' }
            $position += $size
            $payloadLength = $size
        }
        $recordCount++
        $patchedBytes += $payloadLength
        $endOffsetExclusive = $offset + $payloadLength
        if ($endOffsetExclusive -gt $highestOffset) { $highestOffset = $endOffsetExclusive }
    }
    if ($position -ne $endMarker) { throw 'The IPS file does not end at a record boundary.' }
    if ($recordCount -ne 194 -or $patchedBytes -ne 6704 -or $highestOffset -ne 0x6bfb58) {
        throw 'The code.ips structure does not match the approved mod patch.'
    }
    return [pscustomobject]@{
        Path = $fullPath
        Sha256 = $hash
        FileBytes = $bytes.Length
        RecordCount = $recordCount
        PatchedBytes = $patchedBytes
        MaxEndOffsetExclusive = ('0x{0:X}' -f $highestOffset)
    }
}

function Copy-DQXICodeIpsForTargets([string]$Source, [string]$ModRoot) {
    $info = Get-DQXICurrentCodeIpsInfo $Source
    if (!(Test-Path -LiteralPath (Join-Path $ModRoot 'romfs') -PathType Container)) {
        throw 'The Mod/romfs folder is missing from the code patch output.'
    }
    $emulatorFolder = Join-Path $ModRoot 'exefs'
    New-DQXIExclusiveDirectory $emulatorFolder
    $targets = @(
        (Join-Path $ModRoot 'code.ips'),
        (Join-Path $emulatorFolder 'code.ips')
    )
    foreach ($target in $targets) {
        $temporary = $target + '.installing'
        Copy-Item -LiteralPath $info.Path -Destination $temporary -Force
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $info.Sha256) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw 'The copied code patch failed verification.'
        }
        Move-Item -LiteralPath $temporary -Destination $target -Force
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $info.Sha256) {
            throw 'Final code patch verification failed.'
        }
    }
    return $info
}
