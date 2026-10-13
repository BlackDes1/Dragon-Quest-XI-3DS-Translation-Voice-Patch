$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'src/Common.ps1')

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('dqxi-tmd-signatures-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $cases = @(
        @{ Signature = 0x00010000; Body = 0x240 },
        @{ Signature = 0x00010001; Body = 0x140 },
        @{ Signature = 0x00010002; Body = 0x80 },
        @{ Signature = 0x00010003; Body = 0x240 },
        @{ Signature = 0x00010004; Body = 0x140 },
        @{ Signature = 0x00010005; Body = 0x80 }
    )
    foreach ($case in $cases) {
        $body = [int]$case.Body
        $tmd = New-Object byte[] ($body + 0x9c4 + 0x30)
        $signature = [int]$case.Signature
        [byte[]]$signatureBytes = @(0, 1, 0, ($signature -band 0xff))
        [Array]::Copy($signatureBytes, 0, $tmd, 0, 4)
        [byte[]]$titleId = @(0, 4, 0, 0, 0, 0x19, 0x92, 0)
        [Array]::Copy($titleId, 0, $tmd, $body + 0x4c, 8)
        $tmd[$body + 0x9d] = 37
        $tmd[$body + 0x9f] = 1
        $tmd[$body + 0x9c4 + 5] = 0

        $headerSize = [uint32]0x2020
        $tmdOffset = [int]$headerSize
        $cia = New-Object byte[] ($tmdOffset + $tmd.Length)
        [Array]::Copy([BitConverter]::GetBytes($headerSize), 0, $cia, 0, 4)
        [Array]::Copy([BitConverter]::GetBytes([uint32]$tmd.Length), 0, $cia, 16, 4)
        [Array]::Copy($tmd, 0, $cia, $tmdOffset, $tmd.Length)
        $path = Join-Path $temporary ('signature-{0:X8}.cia' -f $signature)
        [IO.File]::WriteAllBytes($path, $cia)

        $result = Get-DQXITitleInfo $path
        if ($result.TitleId -ne '0004000000199200' -or $result.TitleVersion -ne 37 -or $result.ContentCount -ne 1) {
            throw ('TMD signature 0x{0:X8} did not parse correctly.' -f $signature)
        }
    }
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
