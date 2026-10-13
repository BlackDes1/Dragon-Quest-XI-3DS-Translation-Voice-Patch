# Portable, private runtimes; users do not install Python or vgmstream.
. (Join-Path $PSScriptRoot 'Common.ps1')
function Get-PCBuildTools {
    param([Parameter(Mandatory=$true)][string]$ToolCache)
    Add-Type -AssemblyName System.IO.Compression
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'pc_tool_manifest.json') -Raw | ConvertFrom-Json
    $paths=@{}
    foreach($name in @('python','vgmstream','mobipeg')) {
        $row=$manifest.$name
        $folder=Join-Path $ToolCache ($name+'-'+$row.version)
        Assert-DQXIPathNoReparse $folder
        if(!(Test-Path -LiteralPath $folder -PathType Container)) {
            $stage=Join-Path $ToolCache ('.'+$name+'-'+[Guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $stage -Force | Out-Null
            try {
                $archive=Join-Path $stage 'download.zip'
                Invoke-WebRequest -UseBasicParsing -Uri $row.url -OutFile $archive -TimeoutSec 60
                if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.archive_sha256){throw 'Tool download is damaged.'}
                $f=[IO.File]::OpenRead($archive)
                try {
                    $zip=[IO.Compression.ZipArchive]::new($f,[IO.Compression.ZipArchiveMode]::Read)
                    try {
                        foreach($entry in $zip.Entries) {
                            if($entry.FullName.EndsWith('/')){continue}
                            if($entry.Length -gt 64MB){throw 'Tool file is unexpectedly large.'}
                            $dest=Get-DQXISafePath $stage $entry.FullName
                            New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
                            $inputStream=$entry.Open();$outputStream=[IO.File]::Create($dest)
                            try{$inputStream.CopyTo($outputStream)}finally{$outputStream.Dispose();$inputStream.Dispose()}
                        }
                    }finally{$zip.Dispose()}
                }finally{$f.Dispose()}
                Remove-Item -LiteralPath $archive
                if($name -eq 'python') {
                    # -I plus an explicit script directory keeps host site-packages out.
                    [IO.File]::WriteAllText((Join-Path $stage 'python313._pth'),"python313.zip`r`n.`r`n",[Text.Encoding]::ASCII)
                }
                Move-Item -LiteralPath $stage -Destination $folder
            }finally{if(Test-Path -LiteralPath $stage){Remove-Item -LiteralPath $stage -Recurse -Force}}
        }
        $exe=switch($name){
            'python' {'python.exe'}
            'vgmstream' {'vgmstream-cli.exe'}
            'mobipeg' {'ffmpeg.exe'}
        }
        $paths[$name]=Join-Path $folder $exe
        if($name -eq 'mobipeg'){$paths['mobipeg_probe']=Join-Path $folder 'ffprobe.exe'}
        if(!(Test-Path -LiteralPath $paths[$name] -PathType Leaf)){throw "Tool is missing: $name"}
        foreach($file in $row.files) {
            $local=Get-DQXISafePath $folder $file.path
            if(!(Test-Path -LiteralPath $local -PathType Leaf) -or (Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256){throw "Tool file is missing or was modified: $($file.path)"}
        }
        if($name -eq 'mobipeg') {
            $encoders=(& $paths.mobipeg -hide_banner -encoders 2>&1 | Out-String)
            $muxers=(& $paths.mobipeg -hide_banner -muxers 2>&1 | Out-String)
            $demuxers=(& $paths.mobipeg -hide_banner -demuxers 2>&1 | Out-String)
            if($LASTEXITCODE -ne 0 -or $encoders -notmatch '(?m)\bmobiclip\b' -or $muxers -notmatch '(?m)\bmoflex\b' -or $demuxers -notmatch '(?m)\busm\b') {
                throw 'The downloaded Mobipeg build does not provide the required USM demuxer and MobiClip/MOFLEX support.'
            }
        }
    }
    return $paths
}
