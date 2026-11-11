@echo off
rem Stops the running copy of status.py from this folder (not other Python apps).
set "SCRIPT=%~dp0status.py"
powershell -NoProfile -Command "$s = $env:SCRIPT; Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($s) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('stopped ' + $_.ProcessId) }"
