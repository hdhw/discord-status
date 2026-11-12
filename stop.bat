@echo off
rem Stops the running copy of status.py from this folder (not other Python apps).
rem Asks it to quit first so it can remove its tray icon, then force-stops it if needed.
set "SCRIPT=%~dp0status.py"
powershell -NoProfile -Command "$s = $env:SCRIPT; $procs = @(Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($s) }); if ($procs.Count) { try { [void][System.Threading.EventWaitHandle]::OpenExisting('Local\DiscordStatusPresenceStop').Set() } catch {} }; foreach ($p in $procs) { try { Wait-Process -Id $p.ProcessId -Timeout 6 -ErrorAction Stop } catch { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host ('stopped ' + $p.ProcessId) }"
