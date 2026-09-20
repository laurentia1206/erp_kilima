#!/bin/bash
echo ""
echo "================================================"
echo "  SYSCO ERP v2.0 — Comptabilité OHADA"
echo "  Planet Resources SARL"
echo "================================================"
echo ""
echo "  Vérification des dépendances..."
python3 -c "import flask, openpyxl" 2>/dev/null || pip install flask openpyxl --break-system-packages -q
echo "  Dépendances : OK"
echo ""
echo "  Démarrage du serveur..."
echo "  Ouvrir : http://localhost:5000"
echo ""
echo "  Ctrl+C pour arrêter"
echo "================================================"
echo ""
cd "$(dirname "$0")/backend"
python3 app.py
