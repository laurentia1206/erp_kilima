@echo off
title ERP KILIMA HOLDINGS - Serveur
cd /d "%~dp0"
echo ============================================================
echo   ERP KILIMA HOLDINGS - Demarrage du serveur
echo ============================================================
echo.
echo   Laissez cette fenetre OUVERTE pendant l'utilisation.
echo   Ouvrez ensuite votre navigateur sur :  http://localhost:8000
echo.
echo   Pour arreter le serveur : fermez cette fenetre (ou Ctrl+C).
echo ============================================================
echo.
cd /d "%~dp0..\backend_django"
python manage.py runserver 127.0.0.1:8000 --noreload
pause
