@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\Fix-LumaCodePatch.ps1"
if errorlevel 1 pause
