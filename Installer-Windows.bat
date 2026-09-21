@echo off
setlocal
cd /d "%~dp0"
echo Installation de l'environnement ERP Kilima avec Python 3.12.
if exist ".venv\Scripts\python.exe" goto dependencies
py -3.12 -m venv .venv
if errorlevel 1 goto error
:dependencies
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 goto error
where node >nul 2>nul
if errorlevel 1 goto node_missing
pushd frontend
call npm ci
if errorlevel 1 goto frontend_error
call npm run prepare:assets
if errorlevel 1 goto frontend_error
popd
echo Installation terminee. Lancez Demarrer-Next.bat.
pause
exit /b 0
:error
echo Installation incomplete. Verifiez Python 3.12 et la connexion Internet.
pause
exit /b 1
:frontend_error
popd
echo Installation du frontend incomplete. Verifiez Node.js et la connexion Internet.
pause
exit /b 1
:node_missing
echo Installez Node.js 24 LTS puis relancez ce fichier.
pause
exit /b 1
