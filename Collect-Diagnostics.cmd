@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\Collect-Diagnostics.ps1"
if errorlevel 1 pause
