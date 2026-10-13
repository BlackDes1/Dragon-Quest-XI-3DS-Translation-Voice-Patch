Option Explicit

Dim fso, shell, rootPath, scriptPath, systemRoot, processArch, powershellPath
Dim quote, command, exitCode, runError, runDescription

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

rootPath = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(rootPath, "src\Launch-Installer.ps1")

If Not fso.FileExists(scriptPath) Then
    MsgBox "The installer files were not found." & vbCrLf & vbCrLf & _
        "Extract the complete release ZIP, then run DQXI-Mod-Installer.vbs from its folder.", _
        vbOKOnly + vbCritical, "DQXI Mod Workshop"
    WScript.Quit 2
End If

systemRoot = shell.ExpandEnvironmentStrings("%SystemRoot%")
processArch = shell.ExpandEnvironmentStrings("%PROCESSOR_ARCHITEW6432%")

If Len(processArch) > 0 And processArch <> "%PROCESSOR_ARCHITEW6432%" Then
    powershellPath = systemRoot & "\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
Else
    powershellPath = systemRoot & "\System32\WindowsPowerShell\v1.0\powershell.exe"
End If

If Not fso.FileExists(powershellPath) Then
    powershellPath = systemRoot & "\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
End If

If Not fso.FileExists(powershellPath) Then
    MsgBox "Windows PowerShell 5.1 was not found. It is required to run this installer.", _
        vbOKOnly + vbCritical, "DQXI Mod Workshop"
    WScript.Quit 3
End If

quote = Chr(34)
command = quote & powershellPath & quote & _
    " -NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File " & _
    quote & scriptPath & quote

On Error Resume Next
exitCode = shell.Run(command, 0, True)
runError = Err.Number
runDescription = Err.Description
On Error GoTo 0

If runError <> 0 Then
    MsgBox "Windows PowerShell could not be started." & vbCrLf & vbCrLf & runDescription, _
        vbOKOnly + vbCritical, "DQXI Mod Workshop"
    WScript.Quit 4
End If

If exitCode <> 0 Then
    MsgBox "The installer stopped during startup (exit code " & CStr(exitCode) & ")." & _
        vbCrLf & vbCrLf & "Check the startup diagnostic file in your temporary folder, " & _
        "or share the error shown by the installer.", _
        vbOKOnly + vbCritical, "DQXI Mod Workshop"
    WScript.Quit exitCode
End If

WScript.Quit 0
