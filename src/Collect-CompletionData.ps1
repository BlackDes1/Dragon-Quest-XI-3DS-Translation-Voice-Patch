param([string]$WorkFolder)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
if(!$WorkFolder){$WorkFolder=Read-Host 'Existing DQXI build working folder'}
$WorkFolder=[IO.Path]::GetFullPath($WorkFolder.Trim('"'))
. (Join-Path $PSScriptRoot 'Get-PCBuildTools.ps1')
$tools=Get-PCBuildTools -ToolCache (Join-Path $env:LOCALAPPDATA 'DQXI-Mod-Werkstatt/tools')
Assert-DQXIPathNoReparse $WorkFolder
$output=Join-Path $WorkFolder ('DQXI-Completion-Data-'+[Guid]::NewGuid().ToString('N')+'.zip')
& $tools.python '-I' (Join-Path $PSScriptRoot 'python/completion_data.py') '--work' $WorkFolder '--output' $output
if($LASTEXITCODE -ne 0){throw 'Metadata collection failed. See the log for details.'}
