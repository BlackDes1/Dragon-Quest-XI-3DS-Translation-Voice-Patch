# Fetch pinned tools and the official companion used for seeded NCCH decryption.
. (Join-Path $PSScriptRoot 'Common.ps1')
function Install-3DSPrivateRuntime {
    param($Row,[string]$Folder,[string]$ToolCache,$Manifest)
    if(!$Row.PSObject.Properties['runtime_tool']){return}
    $runtimeExe=Get-3DSBuildTool -Name $Row.runtime_tool -ToolCache $ToolCache
    $runtimeRows=@($Manifest.tools | Where-Object {$_.name -eq $Row.runtime_tool})
    if($runtimeRows.Count -ne 1){throw 'Invalid runtime manifest.'}
    $runtimeRow=$runtimeRows[0]
    $runtimeFiles=@([pscustomobject]@{filename=$runtimeRow.executable;sha256=$runtimeRow.exe_sha256})+@($runtimeRow.companion_files)
    foreach($file in $runtimeFiles){
        $source=Join-Path (Split-Path -Parent $runtimeExe) $file.filename
        $target=Join-Path $Folder $file.filename
        Assert-DQXIPathNoReparse $source;Assert-DQXIPathNoReparse $target
        if(!(Test-Path -LiteralPath $target)){[IO.File]::Copy($source,$target,$false)}
        if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256){throw 'The private tool runtime was modified.'}
    }
}
function Get-3DSBuildTool {
    param([Parameter(Mandatory=$true)][ValidateSet('ctrtool','3dstool','makerom','rom-converto','vcruntime')][string]$Name,
          [Parameter(Mandatory=$true)][string]$ToolCache)
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot '3ds_tool_manifest.json') -Raw | ConvertFrom-Json
    $rows = @($manifest.tools | Where-Object { $_.name -eq $Name })
    if ($rows.Count -ne 1) { throw 'Tool manifest is invalid.' }
    $row = $rows[0]
    $folder = Join-Path $ToolCache ($row.name + '-' + $row.version)
    Assert-DQXIPathNoReparse $folder
    $companions=@()
    if($row.PSObject.Properties['companion_files']){$companions=@($row.companion_files)}
    $companionsPresent=$true
    foreach($companion in $companions){
        Assert-DQXISafeName ([string]$companion.filename)
        if([IO.Path]::GetFileName([string]$companion.filename) -cne $companion.filename){throw 'Invalid tool file name.'}
        $path=Join-Path $folder $companion.filename
        Assert-DQXIPathNoReparse $path
        if(!(Test-Path -LiteralPath $path -PathType Leaf)){$companionsPresent=$false}
        elseif((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $companion.sha256){throw "Tool companion file was modified: $path"}
    }
    $destination = Join-Path $folder $row.executable
    Assert-DQXIPathNoReparse $destination
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.exe_sha256) {
            throw "Tool checksum does not match: $destination"
        }
        if($companionsPresent){Install-3DSPrivateRuntime -Row $row -Folder $folder -ToolCache $ToolCache -Manifest $manifest;return $destination}
    }
    Add-Type -AssemblyName System.IO.Compression
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('dqxi-tool-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        $archive = Join-Path $temporary 'tool.zip'
        Invoke-WebRequest -UseBasicParsing -Uri $row.url -OutFile $archive -TimeoutSec 60
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.archive_sha256) {
            throw "Download checksum does not match: $Name"
        }
        if($row.PSObject.Properties['download_format'] -and $row.download_format -eq 'executable') {
            $candidate=Join-Path $temporary $row.executable
            if((Get-Item -LiteralPath $archive).Length -gt 64MB){throw 'Tool file size is unexpected.'}
            [IO.File]::Move($archive,$candidate)
        } else {
        $stream = [IO.File]::OpenRead($archive)
        try {
            $zip = [IO.Compression.ZipArchive]::new($stream,[IO.Compression.ZipArchiveMode]::Read)
            try {
                $entries = @($zip.Entries | Where-Object { [IO.Path]::GetFileName($_.FullName) -ceq $row.executable })
                if ($entries.Count -ne 1 -or $entries[0].Length -gt 32MB) { throw 'Tool archive is unexpected.' }
                $candidate = Join-Path $temporary $row.executable
                $inputStream = $entries[0].Open()
                $outputStream = [IO.File]::Create($candidate)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose(); $inputStream.Dispose() }
                foreach($companion in $companions){
                    $matches=@($zip.Entries | Where-Object { [IO.Path]::GetFileName($_.FullName) -ceq $companion.filename })
                    if($matches.Count -ne 1 -or $matches[0].Length -le 0 -or $matches[0].Length -gt 32MB){throw 'Tool companion file is unexpected.'}
                    $inputStream=$matches[0].Open();$outputStream=[IO.File]::Create((Join-Path $temporary $companion.filename))
                    try{$inputStream.CopyTo($outputStream)}finally{$outputStream.Dispose();$inputStream.Dispose()}
                }
            } finally { $zip.Dispose() }
        } finally { $stream.Dispose() }
        }
        if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.exe_sha256) {
            throw "Executable checksum does not match: $Name"
        }
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        foreach($companion in $companions){
            $path=Join-Path $temporary $companion.filename
            if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $companion.sha256){throw 'Tool companion file does not match the official archive.'}
            $target=Join-Path $folder $companion.filename
            Assert-DQXIPathNoReparse $target
            if(!(Test-Path -LiteralPath $target)){[IO.File]::Move($path,$target)}
            elseif((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $companion.sha256){throw 'The tool cache changed during the download.'}
        }
        if(!(Test-Path -LiteralPath $destination)){[IO.File]::Move($candidate,$destination)}
        elseif((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.exe_sha256){throw 'The tool cache changed during the download.'}
        Install-3DSPrivateRuntime -Row $row -Folder $folder -ToolCache $ToolCache -Manifest $manifest
        return $destination
    } finally { Remove-Item -LiteralPath $temporary -Force -Recurse }
}
