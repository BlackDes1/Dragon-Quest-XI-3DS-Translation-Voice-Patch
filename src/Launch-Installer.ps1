$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'Installer.ps1'
$logPath = Join-Path $env:TEMP ('DQXI-Mod-Installer-startup-' + [Guid]::NewGuid().ToString('N') + '.log')

try {
    if (!(Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "Installer.ps1 was not found at $installer. Extract the complete release ZIP."
    }
    # Keep the installer's normal PowerShell error behavior unchanged.
    $ErrorActionPreference = 'Continue'
    & $installer
}
catch {
    $details = $_ | Out-String
    try {
        [IO.File]::WriteAllText($logPath, $details, [Text.Encoding]::UTF8)
    }
    catch {
        $logPath = '(the diagnostic log could not be written)'
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(
            "The installer could not start.`r`n`r`n$details`r`nDiagnostic log: $logPath",
            'DQXI Mod Workshop',
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    catch {
        Write-Error $details
    }
    exit 1
}
