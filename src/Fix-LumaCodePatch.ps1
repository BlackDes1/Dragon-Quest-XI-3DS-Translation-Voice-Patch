$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
$expectedSha256 = '41c57f46acaac44679a22ac1bf3fdfceb70a2a11c35bf287b3930c9da664bcbf'
$titleId = '0004000000199200'

function Select-Folder([string]$description) {
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description = $description
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return $null }
    return $dialog.SelectedPath
}
function Get-Sha256([string]$path) {
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

try {
    $sourceDialog = New-Object Windows.Forms.OpenFileDialog
    $sourceDialog.Title = 'Select the current code.ips from the installer output folder.'
    $sourceDialog.Filter = 'IPS-Codepatch (*.ips)|*.ips'
    $sourceDialog.CheckFileExists = $true
    if ($sourceDialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { $sourceDialog.Dispose(); exit 0 }
    $source = $sourceDialog.FileName
    $sourceDialog.Dispose()
    $sourceHash = Get-Sha256 $source
    if ($sourceHash -ne $expectedSha256) { throw "The code patch does not match the verified v39.1 build. SHA-256: $sourceHash" }

    $target = Select-Folder 'Select SD:\luma\titles\0004000000199200 (the folder that contains the mod romfs folder).'
    if (!$target) { exit 0 }
    if ((Split-Path -Leaf $target) -ne $titleId) { throw 'The destination folder must be named 0004000000199200.' }
    if (!(Test-Path -LiteralPath (Join-Path $target 'romfs') -PathType Container)) { throw 'The Luma title folder does not contain romfs. The helper stopped to avoid placing the patch in the wrong location.' }

    $destination = Join-Path $target 'code.ips'
    if ((Test-Path -LiteralPath $destination -PathType Leaf) -and (Get-Sha256 $destination) -eq $expectedSha256) {
        [Windows.Forms.MessageBox]::Show('The matching v39.1 patch is already in the Luma load folder. No changes were made.','Luma Code Patch','OK','Information') | Out-Null
        exit 0
    }
    if (Test-Path -LiteralPath $destination) {
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $backup = Join-Path $target ("code.ips.before_luma_fix_" + $stamp)
        Copy-Item -LiteralPath $destination -Destination $backup
    }
    $temporary = Join-Path $target 'code.ips.installing'
    Copy-Item -LiteralPath $source -Destination $temporary -Force
    if ((Get-Sha256 $temporary) -ne $expectedSha256) { Remove-Item -LiteralPath $temporary -Force; throw 'The copied file failed its checksum check; the active file was not replaced.' }
    Move-Item -LiteralPath $temporary -Destination $destination -Force
    if ((Get-Sha256 $destination) -ne $expectedSha256) { throw 'The final checksum verification failed.' }
    [Windows.Forms.MessageBox]::Show("The verified code patch is now here:`n$destination`n`nLuma setting: Enable game patching must be on. Fully power off the 3DS and restart it.",'Luma Code Patch Installed','OK','Information') | Out-Null
} catch {
    [Windows.Forms.MessageBox]::Show($_.Exception.Message,'Luma Code Patch Not Installed','OK','Error') | Out-Null
    exit 1
}
