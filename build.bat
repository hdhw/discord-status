@echo off
rem Builds dist\DiscordStatus.exe with PyInstaller.
rem PyInstaller is installed into a throwaway .build-venv folder, not your main Python.
setlocal
cd /d "%~dp0"

if not exist ".build-venv\Scripts\python.exe" (
    python -m venv .build-venv || exit /b 1
)
".build-venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check "pyinstaller>=6,<7" || exit /b 1

".build-venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
    --name DiscordStatus --icon icon.ico ^
    --add-data "config.example.json;." --add-data "icon.ico;." ^
    status.py || exit /b 1

echo.
echo Built dist\DiscordStatus.exe
