@echo off
title ERP KILIMA HOLDINGS - Version locale de test
cd /d "%~dp0"
echo ============================================================
echo   ERP KILIMA HOLDINGS - Version locale de test
echo   (exactement le meme code que la version deployee)
echo ============================================================
echo.
echo   Deux fenetres noires vont s'ouvrir :
echo     - API Django (port 8012)
echo     - Ecran Next.js (port 3000)
echo   Laissez-les OUVERTES pendant l'utilisation.
echo.
echo   Le navigateur s'ouvrira sur :  http://localhost:3000
echo   (toujours "localhost", jamais 127.0.0.1)
echo.
echo   Base de donnees : data\kilima_local.db (donnees de TEST,
echo   independantes du serveur deploye).
echo ============================================================
start "ERP Kilima - API Django (8012)" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0backend\manage.py" runserver 127.0.0.1:8012 --noreload"
timeout /t 3 /nobreak >nul
start "ERP Kilima - Frontend Next.js (3000)" cmd /k "node "%~dp0frontend\node_modules\next\dist\bin\next" dev --webpack "%~dp0frontend""
echo.
echo   Demarrage en cours... patientez une quinzaine de secondes,
echo   le navigateur va s'ouvrir tout seul.
timeout /t 15 /nobreak >nul
start http://localhost:3000
echo.
echo   Pour tout arreter : fermez les deux fenetres noires.
pause
