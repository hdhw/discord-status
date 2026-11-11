@echo off
rem Start the status script automatically when you log in to Windows.
rem   autostart.bat          add a shortcut to your Startup folder
rem   autostart.bat remove   remove it again
set "SCRIPT=%~dp0status.py"
set "MODE=%~1"
powershell -NoProfile -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Discord Status.lnk';" ^
  "if ($env:MODE -eq 'remove') { Remove-Item $lnk -ErrorAction SilentlyContinue; 'autostart removed'; exit }" ^
  "$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source;" ^
  "if (-not $py) { 'pythonw.exe not found - install Python from python.org and tick \"Add to PATH\"'; exit 1 }" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = $py; $s.Arguments = '\"' + $env:SCRIPT + '\"';" ^
  "$s.WorkingDirectory = Split-Path $env:SCRIPT; $s.Save(); 'autostart added: ' + $lnk"
