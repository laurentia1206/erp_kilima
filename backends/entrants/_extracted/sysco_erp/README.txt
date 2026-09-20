SYSCO ERP v2.0 — Comptabilité OHADA
=====================================
Planet Resources SARL · 1 244 écritures · 1 192 comptes

DÉMARRAGE (2 commandes)
------------------------
  pip install flask openpyxl
  python3 backend/app.py
  → http://localhost:5000

OU double-cliquer start.sh (Linux/Mac)

MODULES
-------
  Dashboard      — KPI temps réel, anomalies, graphiques
  Multi-sociétés — Gestion multi-entités, consolidation
  Saisie         — Validation OHADA en direct (D=C, partie double, doublons)
  Import Excel   — Balance d'ouverture à n'importe quelle date
  7 Journaux     — RAWBANK, EQUITY, Caisse, Ventes, Achats, OD, A-Nouveaux
  Balance        — 1192 comptes, audit OHADA automatique ligne par ligne
  Bilan OHADA    — Actif(Brut/Amort/Net) / Passif, comparatif N-1
  Résultat       — Charges / Produits / Résultat net
  TFT            — Tableau de flux SYSCOHADA méthode indirecte A+B+C
  Grand livre    — Détail par client, fournisseur, banque, caisse
  Audit OHADA    — 7 règles, explication détaillée de chaque anomalie
  Ratios & KPI   — Marge, autonomie, délais, structure financière
  Rapprochement  — Contrôle D=C, écritures déséquilibrées
  Configuration  — Plan de compte (CRUD), journaux, exercices, société

ARCHITECTURE ERP-READY
-----------------------
  Multi-tenant   — Plusieurs sociétés dans une seule base
  API REST       — /api/<tid>/<endpoint>
  SQLite         — Légère, embarquée, ~660 KB pour 1244 écritures
  Modules futurs — RH, Paie, Stocks, Ventes, Achats (tables prêtes)
