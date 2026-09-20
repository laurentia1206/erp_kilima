@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" demarrer_next.py
if errorlevel 1 pause
exit /b
:missing
echo Lancez d'abord Installer-Windows.bat.
pause
exit /b 1
