Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'Common.ps1')
$script:DefaultPcRoot='C:\Program Files (x86)\Steam\steamapps\common\DRAGON QUEST XI S'
$script:sourceProcess=$null
$script:tempLogRoot=$null
$script:preparedOutput=$null
$script:finishedOutput=$null
$form=New-Object Windows.Forms.Form
$form.Text='DRAGON QUEST XI — Mod Installer (v18 · compact build)'
$form.Size=New-Object Drawing.Size(960,875)
$form.MinimumSize=New-Object Drawing.Size(960,875)
$form.StartPosition='CenterScreen'
$form.BackColor=[Drawing.Color]::FromArgb(14,27,39)
$form.ForeColor=[Drawing.Color]::FromArgb(235,241,238)
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$header=New-Object Windows.Forms.Panel
$header.Dock='Top';$header.Height=105;$header.BackColor=[Drawing.Color]::FromArgb(21,49,61);$form.Controls.Add($header)
$title=New-Object Windows.Forms.Label
$title.Text='MOD INSTALLER';$title.Font=New-Object Drawing.Font('Segoe UI Semibold',24)
$title.ForeColor=[Drawing.Color]::FromArgb(232,191,104);$title.Location=New-Object Drawing.Point(28,17);$title.AutoSize=$true;$header.Controls.Add($title)
$subtitle=New-Object Windows.Forms.Label
$subtitle.Text='Your original CIA + DRAGON QUEST XI S · title data is read from your CIA'
$subtitle.Location=New-Object Drawing.Point(32,75);$subtitle.AutoSize=$true;$header.Controls.Add($subtitle)
function Add-Input([int]$y,[string]$caption,[string]$value,[string]$buttonText) {
    $label=New-Object Windows.Forms.Label;$label.Text=$caption;$label.Location=New-Object Drawing.Point(32,$y);$label.AutoSize=$true;$form.Controls.Add($label)
    $text=New-Object Windows.Forms.TextBox;$text.Text=$value;$text.Location=New-Object Drawing.Point(32,($y+27));$text.Size=New-Object Drawing.Size(690,29)
    $text.BackColor=[Drawing.Color]::FromArgb(25,43,55);$text.ForeColor='White';$text.BorderStyle='FixedSingle';$form.Controls.Add($text)
    $button=New-Object Windows.Forms.Button;$button.Text=$buttonText;$button.Location=New-Object Drawing.Point(742,($y+24));$button.Size=New-Object Drawing.Size(175,34)
    $button.FlatStyle='Flat';$button.BackColor=[Drawing.Color]::FromArgb(37,72,83);$button.ForeColor='White';$form.Controls.Add($button)
    return [pscustomobject]@{Text=$text;Button=$button;Label=$label}
}
$ciaInput=Add-Input 124 '1 · Original Japanese CIA · encrypted or decrypted' '' 'Browse for CIA'
$ciaInput.Button.Add_Click({
    $d=New-Object Windows.Forms.OpenFileDialog;$d.Title='Select your unmodified original CIA';$d.Filter='CIA file (*.cia)|*.cia';$d.CheckFileExists=$true
    if($d.ShowDialog() -eq [Windows.Forms.DialogResult]::OK){$ciaInput.Text.Text=$d.FileName};$d.Dispose()
})
$hashHint=New-Object Windows.Forms.Label
$hashHint.Text='The CIA is decrypted automatically. No fixed input hash is required; title ID and structure are validated.';$hashHint.Location=New-Object Drawing.Point(34,189);$hashHint.AutoSize=$true
$hashHint.Font=New-Object Drawing.Font('Consolas',9);$hashHint.ForeColor=[Drawing.Color]::FromArgb(167,193,195);$form.Controls.Add($hashHint)
$defaultCodeIps=Join-Path (Split-Path $PSScriptRoot -Parent) 'code.ips'
if(!(Test-Path -LiteralPath $defaultCodeIps -PathType Leaf)){$defaultCodeIps=''}
$codeInput=Add-Input 211 '2 · Mod code patch · code.ips' $defaultCodeIps 'Browse for IPS file'
$codeInput.Button.Add_Click({
    $d=New-Object Windows.Forms.OpenFileDialog;$d.Title='Select the current code.ips';$d.Filter='IPS patch (*.ips)|*.ips';$d.CheckFileExists=$true
    if($d.ShowDialog() -eq [Windows.Forms.DialogResult]::OK){$codeInput.Text.Text=$d.FileName};$d.Dispose()
})
$codeHint=New-Object Windows.Forms.Label
$codeHint.Text='The selected patch is validated and copied unchanged for Azahar and Luma.'
$codeHint.Location=New-Object Drawing.Point(34,276);$codeHint.AutoSize=$true
$codeHint.Font=New-Object Drawing.Font('Consolas',9);$codeHint.ForeColor=[Drawing.Color]::FromArgb(167,193,195);$form.Controls.Add($codeHint)
$pcInput=Add-Input 300 '3 · Full PC installation: DRAGON QUEST XI S' $script:DefaultPcRoot 'Browse for PC game folder'
$pcInput.Button.Add_Click({
    $d=New-Object Windows.Forms.FolderBrowserDialog;$d.Description='Select the game root folder containing Engine and Game';$d.ShowNewFolderButton=$false
    if(Test-Path -LiteralPath $pcInput.Text.Text -PathType Container){$d.SelectedPath=$pcInput.Text.Text}
    if($d.ShowDialog() -eq [Windows.Forms.DialogResult]::OK){$pcInput.Text.Text=$d.SelectedPath};$d.Dispose()
})
$pcHint=New-Object Windows.Forms.Label;$pcHint.Location=New-Object Drawing.Point(34,365);$pcHint.Size=New-Object Drawing.Size(680,23);$pcHint.ForeColor=[Drawing.Color]::FromArgb(167,193,195);$form.Controls.Add($pcHint)
$pcInput.Text.Add_TextChanged({
    if(Test-Path -LiteralPath $pcInput.Text.Text -PathType Container){$pcHint.Text='Folder found. All required game files will be checked when the build starts.'}
    else{$pcHint.Text='Folder not found. Select the PC game folder.'}
})
if(Test-Path -LiteralPath $script:DefaultPcRoot -PathType Container){$pcHint.Text='Default Steam folder found. File validation runs when the build starts.'}else{$pcHint.Text='Default Steam folder not found. Select the PC game folder.'}
$defaultOut=Join-Path ([Environment]::GetFolderPath('Desktop')) ('DQXI-Build-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$outInput=Add-Input 394 '4 · New working and output folder' $defaultOut 'Choose destination'
$outInput.Button.Add_Click({
    $d=New-Object Windows.Forms.FolderBrowserDialog
    $d.Description=if($resume.Checked){'Select the existing DQXI-Build folder'}else{'Choose the parent output folder'}
    $d.ShowNewFolderButton=!$resume.Checked
    if($d.ShowDialog() -eq [Windows.Forms.DialogResult]::OK){
        $outInput.Text.Text=if($resume.Checked){$d.SelectedPath}else{Join-Path $d.SelectedPath ('DQXI-Build-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))}
    };$d.Dispose()
})
$resume=New-Object Windows.Forms.CheckBox
$resume.Text='Resume an existing movie build (reuse extraction and gameplay voices)'
$resume.Location=New-Object Drawing.Point(34,452);$resume.Size=New-Object Drawing.Size(850,20)
$resume.Font=New-Object Drawing.Font('Segoe UI',9);$resume.ForeColor='White';$form.Controls.Add($resume)
$group=New-Object Windows.Forms.GroupBox;$group.Text='Output format';$group.Location=New-Object Drawing.Point(32,475);$group.Size=New-Object Drawing.Size(885,72);$group.ForeColor=[Drawing.Color]::FromArgb(232,191,104);$form.Controls.Add($group)
$rom=New-Object Windows.Forms.RadioButton;$rom.Text='LayeredFS + Luma code patch';$rom.Location=New-Object Drawing.Point(18,30);$rom.AutoSize=$true;$rom.Checked=$true;$rom.Enabled=$true;$rom.ForeColor='White';$group.Controls.Add($rom)
$cia=New-Object Windows.Forms.RadioButton;$cia.Text='Modified CIA';$cia.Location=New-Object Drawing.Point(525,30);$cia.AutoSize=$true;$cia.Enabled=$true;$cia.ForeColor='White';$group.Controls.Add($cia)
$progressStatus=New-Object Windows.Forms.Label
$progressStatus.Location=New-Object Drawing.Point(35,559);$progressStatus.Size=New-Object Drawing.Size(880,20)
$progressStatus.Text='Ready to build';$progressStatus.AutoEllipsis=$true
$progressStatus.ForeColor=[Drawing.Color]::FromArgb(231,193,135);$form.Controls.Add($progressStatus)
$progress=New-Object Windows.Forms.ProgressBar
$progress.Location=New-Object Drawing.Point(35,582);$progress.Size=New-Object Drawing.Size(880,22)
$progress.Minimum=0;$progress.Maximum=100;$progress.Value=0
$progress.Style=[Windows.Forms.ProgressBarStyle]::Blocks;$form.Controls.Add($progress)
$log=New-Object Windows.Forms.TextBox;$log.Location=New-Object Drawing.Point(32,620);$log.Size=New-Object Drawing.Size(885,150);$log.Multiline=$true;$log.ReadOnly=$true;$log.ScrollBars='Vertical'
$log.BackColor=[Drawing.Color]::FromArgb(8,19,28);$log.ForeColor=[Drawing.Color]::FromArgb(151,217,179);$form.Controls.Add($log)
$state=New-Object Windows.Forms.Label;$state.Location=New-Object Drawing.Point(33,795);$state.Size=New-Object Drawing.Size(235,28);$state.AutoEllipsis=$true;$state.Text='Ready to validate source files';$form.Controls.Add($state)
$open=New-Object Windows.Forms.Button;$open.Text='Open build folder';$open.Location=New-Object Drawing.Point(282,785);$open.Size=New-Object Drawing.Size(185,38);$open.Enabled=$false;$open.FlatStyle='Flat';$open.ForeColor='White';$form.Controls.Add($open)
$open.Add_Click({if($script:preparedOutput -and (Test-Path -LiteralPath $script:preparedOutput)){Start-Process explorer.exe -ArgumentList (ConvertTo-DQXICommandArgument $script:preparedOutput)}})
$finished=New-Object Windows.Forms.Button;$finished.Text='Open finished output';$finished.Location=New-Object Drawing.Point(487,785);$finished.Size=New-Object Drawing.Size(185,38);$finished.Enabled=$false;$finished.FlatStyle='Flat';$finished.ForeColor='White';$form.Controls.Add($finished)
$finished.Add_Click({if($script:finishedOutput -and (Test-Path -LiteralPath $script:finishedOutput -PathType Container)){Start-Process explorer.exe -ArgumentList (ConvertTo-DQXICommandArgument $script:finishedOutput)}})
$go=New-Object Windows.Forms.Button;$go.Text='Build mod';$go.Location=New-Object Drawing.Point(692,785);$go.Size=New-Object Drawing.Size(225,38);$go.FlatStyle='Flat'
$go.BackColor=[Drawing.Color]::FromArgb(196,151,72);$go.ForeColor=[Drawing.Color]::FromArgb(20,31,38);$go.Font=New-Object Drawing.Font('Segoe UI Semibold',10);$form.Controls.Add($go)
$resume.Add_CheckedChanged({
    $outInput.Label.Text=if($resume.Checked){'4 · Existing DQXI-Build folder to resume'}else{'4 · New working and output folder'}
    $outInput.Button.Text=if($resume.Checked){'Choose existing build'}else{'Choose destination'}
    $go.Text=if($resume.Checked){'Resume build'}else{'Build mod'}
})
$timer=New-Object Windows.Forms.Timer;$timer.Interval=400
function Read-SharedLog([string]$path){
    if(!(Test-Path -LiteralPath $path)){return ''}
    $f=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try{$reader=New-Object IO.StreamReader($f);try{return $reader.ReadToEnd()}finally{$reader.Dispose()}}finally{$f.Dispose()}
}
$timer.Add_Tick({
    try{
        $stdout=Read-SharedLog (Join-Path $script:tempLogRoot 'stdout.log')
        $stderr=Read-SharedLog (Join-Path $script:tempLogRoot 'stderr.log')
        $log.Text=$stdout+"`r`n"+$stderr
        $log.SelectionStart=$log.TextLength;$log.ScrollToCaret()
        $progressLine=@($stdout -split '\r?\n' | Where-Object {$_.Trim().Length -gt 0} | Select-Object -Last 1)
        if($progressLine.Count -gt 0){$progressStatus.Text=$progressLine[0].Trim()}
        if($script:sourceProcess.HasExited){
            $timer.Stop();$script:sourceProcess.WaitForExit()
            if($script:sourceProcess.ExitCode -eq 0 -and (Test-Path -LiteralPath (Join-Path $script:preparedOutput 'source-preparation-report.json'))){
                $completion=Get-Content -LiteralPath (Join-Path $script:preparedOutput 'source-preparation-report.json') -Raw | ConvertFrom-Json
                $expectedFinal=Join-Path $script:preparedOutput $(if($completion.requested_format -eq 'cia'){'cia'}else{'Mod'})
                if(!$completion.build_output_generated -or !$completion.final_output_directory -or
                   ![string]::Equals([IO.Path]::GetFullPath($completion.final_output_directory),[IO.Path]::GetFullPath($expectedFinal),[StringComparison]::OrdinalIgnoreCase) -or
                   !(Test-Path -LiteralPath $expectedFinal -PathType Container)){throw 'The finished output path could not be verified.'}
                Assert-DQXIPathNoReparse $expectedFinal
                $script:finishedOutput=$expectedFinal;$finished.Enabled=$true
                $progress.Style=[Windows.Forms.ProgressBarStyle]::Continuous;$progress.Value=100
                $progressStatus.Text='Build completed successfully.'
                $state.Text='Build complete.';$open.Enabled=$true
            }
            else{
                $progress.Style=[Windows.Forms.ProgressBarStyle]::Continuous;$progress.Value=0
                $progressStatus.Text='Build failed. Review the log for details.'
                $state.Text='Build failed. See the log for details.'
                $open.Enabled=(Test-Path -LiteralPath $script:preparedOutput -PathType Container)
            }
            $script:sourceProcess.Dispose();$script:sourceProcess=$null;$go.Enabled=$true;$rom.Enabled=$true;$cia.Enabled=$true;$resume.Enabled=$true
            foreach($entry in @($ciaInput,$codeInput,$pcInput,$outInput)){$entry.Text.Enabled=$true;$entry.Button.Enabled=$true}
        }
    }catch{
        $timer.Stop();$progress.Style=[Windows.Forms.ProgressBarStyle]::Continuous;$progress.Value=0
        $progressStatus.Text='Unable to read build progress.';$state.Text='Log error: '+$_.Exception.Message
        if($script:sourceProcess -and $script:sourceProcess.HasExited){
            $script:sourceProcess.Dispose();$script:sourceProcess=$null
            $go.Enabled=$true;$rom.Enabled=$true;$cia.Enabled=$true;$resume.Enabled=$true
            $open.Enabled=(Test-Path -LiteralPath $script:preparedOutput -PathType Container)
            foreach($entry in @($ciaInput,$codeInput,$pcInput,$outInput)){$entry.Text.Enabled=$true;$entry.Button.Enabled=$true}
        }elseif($script:sourceProcess){$timer.Start()}
    }
})
$go.Add_Click({
    try{
        if(!$ciaInput.Text.Text -or !$codeInput.Text.Text -or !$pcInput.Text.Text -or !$outInput.Text.Text){throw 'Select the original CIA, current code.ips, PC installation and output folder.'}
        if(!(Test-Path -LiteralPath $ciaInput.Text.Text -PathType Leaf)){throw 'Original CIA not found.'}
        if(!(Test-Path -LiteralPath $codeInput.Text.Text -PathType Leaf)){throw 'The current code.ips was not found.'}
        if($resume.Checked){
            if(!(Test-Path -LiteralPath $outInput.Text.Text -PathType Container)){throw 'Select the existing DQXI-Build folder to resume.'}
        }elseif(Test-Path -LiteralPath $outInput.Text.Text){throw 'The output folder must not already exist. Choose a different folder name.'}
        $script:preparedOutput=[IO.Path]::GetFullPath($outInput.Text.Text)
        $script:tempLogRoot=Join-Path ([IO.Path]::GetTempPath()) ('dqxi-gui-'+[Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:tempLogRoot|Out-Null
        $format=if($cia.Checked){'cia'}else{'layeredfs'}
        $arguments=@('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'Prepare-Sources.ps1'),'-OriginalCia',$ciaInput.Text.Text,'-CodeIps',$codeInput.Text.Text,'-PcRoot',$pcInput.Text.Text,'-OutputFolder',$script:preparedOutput,'-Format',$format)
        if($resume.Checked){$arguments+='-Resume'}
        $quoted=@($arguments|ForEach-Object{ConvertTo-DQXICommandArgument ([string]$_)})
        $script:sourceProcess=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList ($quoted -join ' ') -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $script:tempLogRoot 'stdout.log') -RedirectStandardError (Join-Path $script:tempLogRoot 'stderr.log')
        $go.Enabled=$false;$open.Enabled=$false;$finished.Enabled=$false;$script:finishedOutput=$null;$rom.Enabled=$false;$cia.Enabled=$false;$resume.Enabled=$false
        foreach($entry in @($ciaInput,$codeInput,$pcInput,$outInput)){$entry.Text.Enabled=$false;$entry.Button.Enabled=$false}
        $progress.Style=[Windows.Forms.ProgressBarStyle]::Marquee;$progress.MarqueeAnimationSpeed=25
        $progressStatus.Text=if($resume.Checked){'Checking existing sources and movie checkpoints...'}else{'Starting validation and extraction...'}
        $state.Text=if($resume.Checked){'Resuming the existing movie build...'}else{'Validation and extraction are running...'};$timer.Start()
    }catch{
        $progress.Style=[Windows.Forms.ProgressBarStyle]::Continuous;$progress.Value=0
        $progressStatus.Text='Build could not be started.'
        [Windows.Forms.MessageBox]::Show($_.Exception.Message,'DQXI Mod Installer','OK','Error')|Out-Null
    }
})
$form.Add_FormClosing({param($sender,$eventArgs)
    if($script:sourceProcess -and !$script:sourceProcess.HasExited){$eventArgs.Cancel=$true;[Windows.Forms.MessageBox]::Show('Source files are still being processed. You can close this window after the build finishes.','DQXI Mod Installer')|Out-Null}
})
[void]$form.ShowDialog();$timer.Dispose();$form.Dispose()
