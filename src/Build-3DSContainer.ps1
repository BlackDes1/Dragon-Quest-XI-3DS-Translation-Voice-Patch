[CmdletBinding(DefaultParameterSetName='CIA')]
param(
    [Parameter(Mandatory=$true,ParameterSetName='CIA')][string]$OriginalCia,
    [Parameter(Mandatory=$true,ParameterSetName='Cartridge')][string]$OriginalRom,
    [Parameter(Mandatory=$true)][string]$GeneratedMod,
    [Parameter(Mandatory=$true)][string]$OutputFolder,
    [ValidateSet('3ds','cia')][string]$Format = 'cia',
    [string]$PreparedOriginalRoot,
    [switch]$KeepIntermediate
)
# Internal backend. GeneratedMod is produced by the PC-to-3DS conversion stage.
# It is not a finished-mod prerequisite for the final installer.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-3DSBuildTools.ps1')
if ($PSCmdlet.ParameterSetName -eq 'Cartridge') { $OriginalRom = (Resolve-Path -LiteralPath $OriginalRom).Path }
$GeneratedMod = (Resolve-Path -LiteralPath $GeneratedMod).Path
$OutputFolder = [IO.Path]::GetFullPath($OutputFolder)
if ($PSCmdlet.ParameterSetName -eq 'Cartridge' -and [IO.Path]::GetExtension($OriginalRom).ToLowerInvariant() -notin @('.3ds','.cci')) {
    throw 'This backend requires your own decrypted .3ds/.cci file as the header source.'
}
if (Test-Path -LiteralPath $OutputFolder) { throw 'Choose a new output folder.' }
if (!(Test-Path -LiteralPath (Join-Path $GeneratedMod 'romfs') -PathType Container) -or
    !(Test-Path -LiteralPath (Join-Path $GeneratedMod 'exefs/code.ips') -PathType Leaf)) {
    throw 'The PC conversion stage must first create ROMFS and exefs/code.ips.'
}
. (Join-Path $PSScriptRoot 'Load-NativeBackend.ps1')
Initialize-DQXINativeBackend
$cancel = [Threading.CancellationToken]::None
if ($PSCmdlet.ParameterSetName -eq 'CIA') {
    if ($Format -ne 'cia') { throw 'A CIA source produces a CIA container. Use the mod stage for LayeredFS.' }
    [void][CiaSupport]::ValidateOriginal($OriginalCia,$cancel)
} else { [RomBuilder]::ValidateCartridge($OriginalRom) }
if ($PSCmdlet.ParameterSetName -eq 'CIA') {
    [BuildSupport]::NoReparse($OutputFolder)
    if ([BuildSupport]::IsWithin($OutputFolder,$GeneratedMod) -or [BuildSupport]::IsWithin($GeneratedMod,$OutputFolder) -or [BuildSupport]::IsWithin($OutputFolder,$OriginalCia)) { throw 'The container output folder must not overlap any input.' }
    [BuildSupport]::CreateExclusiveDirectory($OutputFolder)
    $work=Join-Path $OutputFolder '.dqxi-private'
    [BuildSupport]::CreateExclusiveDirectory($work)
    $cache=Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
    $source=$null;$reusedOriginal=$false
    if($PreparedOriginalRoot){
        $PreparedOriginalRoot=[IO.Path]::GetFullPath($PreparedOriginalRoot)
        [BuildSupport]::NoReparse($PreparedOriginalRoot)
        $expectedOriginal=Join-Path (Split-Path $GeneratedMod -Parent) 'original-3ds'
        if(![string]::Equals($PreparedOriginalRoot,[IO.Path]::GetFullPath($expectedOriginal),[StringComparison]::OrdinalIgnoreCase)){
            throw 'Prepared sources must belong to the same installer build folder.'
        }
        try{
            $source=[CiaSupport]::ReuseExtracted($OriginalCia,$PreparedOriginalRoot,$cancel)
            $reusedOriginal=$true
            Write-Output 'Reusing the verified original CIA export for container reconstruction.'
        }catch{
            $reason=$_.Exception.GetBaseException()
            if($reason -isnot [IO.FileNotFoundException] -and $reason -isnot [IO.DirectoryNotFoundException]){throw}
            Write-Output 'Original container images were released by an earlier LayeredFS build; preparing them for the CIA output.'
        }
    }
    if(!$source){
        $source=& (Join-Path $PSScriptRoot 'Extract-OriginalCIA.ps1') -OriginalCia $OriginalCia -OutputRoot (Join-Path $work 'original') -KeepIntermediate:$KeepIntermediate
    }
    $rebuilder=Get-3DSBuildTool -Name 3dstool -ToolCache $cache
    $makerom=Get-3DSBuildTool -Name makerom -ToolCache $cache
    $ctrtool=Get-3DSBuildTool -Name ctrtool -ToolCache $cache
    $notify=[Action[string,int]] { param($message,$percent) Write-Progress -Activity 'DQXI game container' -Status $message -PercentComplete $percent }
    $rebuilt=[RomBuilder]::BuildGameFromNcch($source.GamePath,$source.Root,$GeneratedMod,(Join-Path $work 'rebuild'),$notify,$cancel,$rebuilder,(!$KeepIntermediate.IsPresent))
    $final=Join-Path $OutputFolder 'DQXI-S-3DS.cia'
    [void][CiaSupport]::PackCia($source,$rebuilt,$final,$makerom,$ctrtool,$work,$cancel,(!$KeepIntermediate.IsPresent))
    [ordered]@{pc_source='DQXI S';output=$final;format='cia';output_bytes=(Get-Item -LiteralPath $final).Length;output_sha256=(Get-FileHash -LiteralPath $final -Algorithm SHA256).Hash.ToLowerInvariant();reused_original_extraction=$reusedOriginal;compact_work=(!$KeepIntermediate.IsPresent);fixed_input_hash_check=$false;headers_from_user_cia=$true;original_contents_preserved_except_verified_plaintext_flags=$true;container_content_readback_verified=$true;original_romfs_file_count=$source.RomFsFileCount;original_romfs_total_bytes=$source.RomFsTotalBytes;hardware_tested=$false;windows_end_to_end_tested=$false} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputFolder 'container-report.json') -Encoding UTF8
    Write-Progress -Activity 'DQXI game container' -Completed
    Write-Output $final
    return
}
New-Item -ItemType Directory -Path $OutputFolder | Out-Null
$work = Join-Path $OutputFolder '.dqxi-private'
$extracted = Join-Path $work 'original'
$generated = Join-Path $work 'generated'
New-Item -ItemType Directory -Path $extracted -Force | Out-Null
New-Item -ItemType Directory -Path $generated | Out-Null
$cache = Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools'
$cancel = [Threading.CancellationToken]::None
try {
    $ctrtool = Get-3DSBuildTool -Name ctrtool -ToolCache $cache
    $rebuilder = Get-3DSBuildTool -Name 3dstool -ToolCache $cache
    [BuildSupport]::RunTool($ctrtool,[string[]]@('-p','-n','0',('--romfsdir='+(Join-Path $extracted 'romfs')),('--exefsdir='+(Join-Path $extracted 'exefs')),$OriginalRom),$work,(Join-Path $work 'extract.log'),$cancel)
    Copy-Item -LiteralPath (Join-Path $GeneratedMod 'romfs') -Destination $generated -Recurse
    Copy-Item -LiteralPath (Join-Path $GeneratedMod 'exefs') -Destination $generated -Recurse
    $notify = [Action[string,int]] { param($message,$percent) Write-Progress -Activity 'DQXI game container' -Status $message -PercentComplete $percent }
    $cartridge = [RomBuilder]::Build($OriginalRom,$extracted,$generated,$notify,$cancel,$rebuilder)
    if ($Format -eq '3ds') {
        $final = Join-Path $OutputFolder 'DQXI-S-3DS.3ds'
        [IO.File]::Move($cartridge,$final)
    } else {
        $makerom = Get-3DSBuildTool -Name makerom -ToolCache $cache
        $cxi = Join-Path $work 'translated.cxi'
        [BuildSupport]::RunTool($rebuilder,[string[]]@('-x','-t','cci','-f',$cartridge,'--partition0',$cxi),$work,(Join-Path $work 'cia.log'),$cancel)
        $partial = Join-Path $OutputFolder 'DQXI-S-3DS.cia.partial'
        [BuildSupport]::RunTool($makerom,[string[]]@('-f','cia','-target','t','-ignoresign','-i',($cxi+':0:0'),'-o',$partial),$work,(Join-Path $work 'cia.log'),$cancel)
        # Re-extract the CIA content and compare all bytes via SHA-256.
        $prefix = Join-Path $work 'cia-content'
        [BuildSupport]::RunTool($ctrtool,[string[]]@('-p',('--contents='+$prefix),$partial),$work,(Join-Path $work 'cia-verify.log'),$cancel)
        $contents = @(Get-ChildItem -LiteralPath $work -File -Filter 'cia-content.*')
        if ($contents.Count -ne 1 -or (Get-FileHash -LiteralPath $contents[0].FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $cxi -Algorithm SHA256).Hash) {
            throw 'CIA readback verification failed. The partial file is not a completed output.'
        }
        $final = Join-Path $OutputFolder 'DQXI-S-3DS.cia'
        [IO.File]::Move($partial,$final)
    }
    [ordered]@{pc_source='DQXI S';output=$final;format=$Format;original_cia_required=$false;container_content_readback_verified=$true;hardware_tested=$false;windows_end_to_end_tested=$false} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputFolder 'container-report.json') -Encoding UTF8
    Write-Progress -Activity 'DQXI game container' -Completed
    Write-Output $final
} catch {
    Write-Progress -Activity 'DQXI game container' -Completed
    throw
}
