@echo off
setlocal
cd /d "%~dp0"
echo Installation de l'environnement ERP Kilima avec Python 3.12.
if exist ".venv\Scripts\python.exe" goto dependencies
py -3.12 -m venv .venv
if errorlevel 1 goto error
:dependencies
".venv\Scripts\python.exe" -m pip install -r backend_django\requirements.txt
if errorlevel 1 goto error
echo Installation terminee. Lancez Demarrer-tests.bat.
pause
exit /b 0
:error
echo Installation incomplete. Verifiez Python 3.12 et la connexion Internet.
pause
exit /b 1
