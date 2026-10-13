# Shared loader for Windows PowerShell 5.1; no additional runtime installation.
function Initialize-DQXINativeBackend {
    if ('CiaSupport' -as [type]) { return }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $nativeRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'third_party/kenzie/native'
    $paths = @('BuildSupport.cs','Codecs.cs','RomBuilder.cs','CiaSupport.cs') | ForEach-Object { Join-Path $nativeRoot $_ }
    Add-Type -Path $paths -ReferencedAssemblies @('System.dll','System.Core.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll')
}
