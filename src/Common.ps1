# Shared PowerShell helpers. This file replaces the former native C# helper
# layer with Windows PowerShell/.NET framework functions.
function Assert-DQXIPathNoReparse([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Linked filesystem paths are not permitted: $current"
            }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if (!$parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-DQXISafeName([string]$Name) {
    if ([string]::IsNullOrEmpty($Name) -or $Name.Contains('\') -or $Name.Contains(':') -or
        $Name.StartsWith('/') -or [IO.Path]::IsPathRooted($Name)) {
        throw 'Unsafe package path.'
    }
    foreach ($part in $Name.Split('/')) {
        if (!$part -or $part -in @('.', '..') -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
            $part -match '[\x00-\x1f<>:"|?*]') { throw 'Unsafe package path.' }
        $stem = $part.Split('.')[0].ToUpperInvariant()
        if ($stem -in @('CON','PRN','AUX','NUL','CLOCK$') -or $stem -match '^(COM|LPT)[0-9]$') {
            throw 'Reserved Windows package path.'
        }
    }
}

function Get-DQXISafePath([string]$Root,[string]$Name) {
    Assert-DQXISafeName $Name
    $rootFull = [IO.Path]::GetFullPath($Root)
    $path = [IO.Path]::GetFullPath((Join-Path $rootFull ($Name.Replace('/',[IO.Path]::DirectorySeparatorChar))))
    $prefix = $rootFull.TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Package path escapes its root.' }
    Assert-DQXIPathNoReparse $path
    return $path
}

function Test-DQXIPathWithin([string]$Root,[string]$Path) {
    $r = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    $p = [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    return ($p.Equals($r,[StringComparison]::OrdinalIgnoreCase) -or
        $p.StartsWith($r + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase))
}

function Test-DQXIPathOverlap([string]$First,[string]$Second) {
    return (Test-DQXIPathWithin $First $Second) -or (Test-DQXIPathWithin $Second $First)
}

function New-DQXIExclusiveDirectory([string]$Path) {
    Assert-DQXIPathNoReparse $Path
    if (Test-Path -LiteralPath $Path) { throw "Choose a new output folder: $Path" }
    $parent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path))
    if ($parent -and !(Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null
    Assert-DQXIPathNoReparse $Path
}

function Get-DQXITitleInfo([string]$CiaPath) {
    Assert-DQXIPathNoReparse $CiaPath
    if ([IO.Path]::GetExtension($CiaPath) -ine '.cia') { throw 'Choose the original .CIA file.' }
    $stream = [IO.File]::Open($CiaPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if ($stream.Length -lt 32) { throw 'Truncated CIA header.' }
        $reader = New-Object IO.BinaryReader($stream)
        $header = $reader.ReadBytes(32)
        $headerSize = [BitConverter]::ToUInt32($header,0)
        $certSize = [BitConverter]::ToUInt32($header,8)
        $ticketSize = [BitConverter]::ToUInt32($header,12)
        $tmdSize = [BitConverter]::ToUInt32($header,16)
        if ($headerSize -lt 0x2020 -or $headerSize -gt 1MB -or $tmdSize -lt 4 -or $tmdSize -gt 4MB) {
            throw 'Unsupported CIA header or TMD bounds.'
        }
        $tmdOffset = (([long]$headerSize + 63) -band -64L)
        $tmdOffset = (($tmdOffset + $certSize + 63) -band -64L)
        $tmdOffset = (($tmdOffset + $ticketSize + 63) -band -64L)
        if ($tmdOffset -gt $stream.Length - $tmdSize) { throw 'CIA TMD lies outside the file.' }
        [void]$stream.Seek($tmdOffset,[IO.SeekOrigin]::Begin)
        $tmd = $reader.ReadBytes([int]$tmdSize)
        if ($tmd.Length -ne $tmdSize) { throw 'Truncated CIA TMD.' }
    } finally { $stream.Dispose() }

    $signature = [uint32]([uint64]$tmd[0] * 16777216 + [uint64]$tmd[1] * 65536 + [uint64]$tmd[2] * 256 + $tmd[3])
    # PowerShell stores these hexadecimal literals as Int32 keys. Comparing
    # them with a boxed UInt32 makes Hashtable.ContainsKey return false even
    # for a valid signature. Normalize both sides to the same fixed-width text.
    $signatureKey = $signature.ToString('X8',[Globalization.CultureInfo]::InvariantCulture)
    $bodies = @{ '00010000'=0x240; '00010003'=0x240; '00010001'=0x140; '00010004'=0x140; '00010002'=0x80; '00010005'=0x80 }
    if (!$bodies.ContainsKey($signatureKey)) { throw "Unsupported TMD signature type: 0x$signatureKey." }
    $body = [int]$bodies[$signatureKey]
    if ($tmd.Length -lt $body + 0x9c4) { throw 'Unsupported or truncated CIA content table.' }
    $title = [BitConverter]::ToString($tmd,$body+0x4c,8).Replace('-','')
    if ($title -ine '0004000000199200') { throw 'The CIA TMD is not DQXI Japan (0004000000199200).' }
    $count = ([int]$tmd[$body+0x9e] -shl 8) -bor [int]$tmd[$body+0x9f]
    if ($count -lt 1 -or $count -gt 256 -or $tmd.Length -ne $body + 0x9c4 + $count * 0x30) {
        throw 'Unsupported or truncated CIA content table.'
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[int]'
    $hasGame = $false
    for ($i=0; $i -lt $count; $i++) {
        $index = ([int]$tmd[$body+0x9c4+$i*0x30+4] -shl 8) -bor [int]$tmd[$body+0x9c4+$i*0x30+5]
        if (!$seen.Add($index)) { throw 'Duplicate CIA content index.' }
        if ($index -eq 0) { $hasGame = $true }
    }
    if (!$hasGame) { throw 'CIA has no content zero.' }
    return [pscustomobject]@{ TitleId='0004000000199200'; TitleVersion=(([int]$tmd[$body+0x9c] -shl 8) -bor [int]$tmd[$body+0x9d]); ContentCount=$count }
}

function ConvertTo-DQXICommandArgument([string]$Value) {
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($slashes * 2) + 1)))
            [void]$builder.Append('"')
        } else {
            [void]$builder.Append(('\' * $slashes))
            [void]$builder.Append($character)
        }
        $slashes = 0
    }
    [void]$builder.Append(('\' * ($slashes * 2)))
    [void]$builder.Append('"')
    return $builder.ToString()
}
