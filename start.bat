@echo off
rem Runs the presence updater in the background (no console window).
rem Logs go to status.log next to this file.
call "%~dp0stop.bat" >nul 2>&1
start "" pythonw "%~dp0status.py"
