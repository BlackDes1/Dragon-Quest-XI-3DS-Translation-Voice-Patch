param(
    [string]$WorkFolder,
    [string]$OutputZip
)
$ErrorActionPreference='Stop'
if(!$WorkFolder){$WorkFolder=Read-Host 'Build working folder created by the installer'}
$WorkFolder=[IO.Path]::GetFullPath($WorkFolder.Trim('"'))
if(!(Test-Path -LiteralPath $WorkFolder -PathType Container)){throw 'Build working folder was not found.'}
function Assert-PlainPath([string]$path){
    $cursor=[IO.Path]::GetFullPath($path)
    while($cursor){
        if(Test-Path -LiteralPath $cursor){
            if(((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw "A linked path was found in the diagnostics path: $cursor"}
        }
        $parent=[IO.Path]::GetDirectoryName($cursor)
        if($parent -eq $cursor){break};$cursor=$parent
    }
}
Assert-PlainPath $WorkFolder
if(!$OutputZip){$OutputZip=Join-Path $WorkFolder ('DQXI-Diagnose-'+[Guid]::NewGuid().ToString('N')+'.zip')}
$OutputZip=[IO.Path]::GetFullPath($OutputZip)
Assert-PlainPath $OutputZip
if(Test-Path -LiteralPath $OutputZip){throw 'The diagnostics ZIP already exists.'}
$staging=Join-Path ([IO.Path]::GetTempPath()) ('dqxi-diagnostics-'+[Guid]::NewGuid().ToString('N'))
$partial=$OutputZip+'.'+[Guid]::NewGuid().ToString('N')+'.partial'
New-Item -ItemType Directory -Path $staging | Out-Null
$included=New-Object 'System.Collections.Generic.List[string]'
try{
    $reportPaths=New-Object 'System.Collections.Generic.List[string]'
    foreach($relative in @('source-preparation-report.json','original-3ds/cia-extraction-report.json','original-3ds/cia-extraction-error.json',
                           'original-3ds/extract.log','pc-assets/pc-extraction-report.json',
                           'pc-dialogue/dialogue-build-report.json','storage-cleanup-report.json',
                           'movie-build-failure.log','movie-source-checks.json','movie-voice-decode.log',
                           'reports/cia-extraction-report.json','reports/cia-extraction-error.json','reports/extract.log',
                           'reports/pc-extraction-report.json','reports/component-report.json','reports/text-progress-report.json',
                           'reports/movie-sources-report.json','reports/movie-build-report.json','reports/build-report.json',
                           'reports/container-report.json','cia/container-report.json')){$reportPaths.Add($relative)}
    # Resume folders contain user text exports as well. Only exact metadata
    # report names are permitted; never recursively archive these directories.
    foreach($folder in Get-ChildItem -LiteralPath $WorkFolder -Directory){
        if($folder.Name -eq 'pc-components' -or $folder.Name -match '^pc-components-v6-[0-9a-f]{32}$'){
            Assert-PlainPath $folder.FullName
            foreach($name in @('component-report.json','text-progress-report.json','movie-sources-report.json')){
                $reportPaths.Add($folder.Name+'/'+$name)
            }
        }
    }
    # Explicit allowlist: never archive source CIA, headers, texts, voices or movies.
    foreach($relative in $reportPaths){
        $source=Join-Path $WorkFolder $relative
        Assert-PlainPath $source
        if(Test-Path -LiteralPath $source -PathType Leaf){
            $destination=Join-Path $staging $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            if($relative -in @('original-3ds/extract.log','reports/extract.log')){
                # Older CTRTool logs may print crypto material. Reports never
                # need those lines; new extraction also runs CTRTool quietly.
                $reader=[IO.StreamReader]::new($source)
                $writer=[IO.StreamWriter]::new($destination,$false,[Text.UTF8Encoding]::new($false))
                try{
                    while($null -ne ($line=$reader.ReadLine())){
                        if($line -match '(?i)(title\s*key|key[\s_-]*[xy]\b|seed\s*[:=]|unknown ext key record)'){$writer.WriteLine('[crypto material removed]')}
                        else{$writer.WriteLine($line)}
                    }
                }finally{$writer.Dispose();$reader.Dispose()}
            }else{Copy-Item -LiteralPath $source -Destination $destination}
            $included.Add($relative)
        }
    }
    if($included.Count -eq 0){throw 'No known diagnostic reports were found. Run source preparation first.'}
    $romfs=Join-Path $WorkFolder 'original-3ds/romfs'
    if(Test-Path -LiteralPath $romfs -PathType Container){
        Assert-PlainPath $romfs
        $prefix=[IO.Path]::GetFullPath($romfs).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
        $queue=New-Object 'System.Collections.Generic.Queue[string]';$queue.Enqueue($romfs)
        $files=New-Object 'System.Collections.Generic.List[object]'
        while($queue.Count){
            foreach($entry in Get-ChildItem -LiteralPath ($queue.Dequeue()) -Force){
                if(($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'The ROMFS contains a linked path.'}
                if($entry.PSIsContainer){$queue.Enqueue($entry.FullName)}
                else{$files.Add([ordered]@{path=$entry.FullName.Substring($prefix.Length).Replace('\','/');bytes=$entry.Length})}
            }
        }
        [ordered]@{schema_version=1;file_count=$files.Count;content_read=$false;hash_check=$false;files=$files.ToArray()} |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $staging 'original-romfs-file-list.json') -Encoding UTF8
        $included.Add('original-romfs-file-list.json')
    }
    [ordered]@{schema_version=1;included=$included.ToArray();game_payloads_included=$false;full_build_ready=$false} |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $staging 'diagnostics-index.json') -Encoding UTF8
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($staging,$partial)
    [IO.File]::Move($partial,$OutputZip)
    Write-Output "Diagnostics ZIP created: $OutputZip"
    Write-Output 'The archive contains reports and file sizes. Logs may contain local paths.'
}finally{
    if(Test-Path -LiteralPath $staging){Remove-Item -LiteralPath $staging -Recurse -Force}
    if(Test-Path -LiteralPath $partial){Remove-Item -LiteralPath $partial -Force}
}
