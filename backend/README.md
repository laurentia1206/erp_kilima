# Backend ERP KILIMA HOLDINGS — V1

API FastAPI du **Centre de décaissement & avances à justifier** (cœur de la V1).

## Stack
FastAPI · SQLAlchemy 2 · PostgreSQL 14+ · JWT (OAuth2 password) · bcrypt.

## Architecture
```
app/
  domain/        # Logique métier PURE, sans DB (testée) :
    money.py        — conversions USD/CDF au taux du jour
    workflow.py     — résolution des paliers + validation multi-signataires
    avances.py      — équilibre des justifications + blocage automatique
  models.py      # ORM (miroir de database/schema_v1.sql)
  services.py    # numérotation, paramètres, taux, chargement des paliers, audit
  security.py    # hachage bcrypt + JWT
  deps.py        # auth + contrôle d'accès PAR SOCIÉTÉ (côté serveur)
  schemas.py     # DTO Pydantic
  routers/       # auth · taux · requisitions · ordres_depense · avances
  main.py        # application
tests/           # tests de la logique métier pure (sans DB)
```

## Démarrage rapide — DÉVELOPPEMENT (SQLite, rien à installer)
La base est un simple fichier ; idéal pour tester/démontrer.
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # (Windows ; macOS/Linux : source .venv/bin/activate)
pip install -r requirements.txt
# Le fichier .env fourni pointe déjà sur SQLite (kilima_dev.db)
python -m scripts.init_dev_db        # crée + peuple la base de démo
uvicorn app.main:app --reload        # → http://localhost:8000/docs
```
**Comptes de démonstration** (mot de passe `demo1234`) : `dfi@kilima.cd`, `dg@kilima.cd`,
`admin@kilima.cd`, `president@kilima.cd`, `caissier@kilima.cd`, `comptable@kilima.cd`.

## Installation — PRODUCTION (PostgreSQL)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # DATABASE_URL=postgresql+psycopg://... + SECRET_KEY robuste

createdb kilima_erp
psql -d kilima_erp -f ../database/schema_v1.sql
psql -d kilima_erp -f ../database/seed_v1.sql
uvicorn app.main:app        # derrière un serveur WSGI/ASGI de production
```

## Tests (logique métier — ne nécessitent pas PostgreSQL)
```bash
cd backend
python -m pytest -q
```

## Flux implémenté (circuit G01 → G04)
1. **POST `/api/auth/login`** → jeton.
2. **POST `/api/taux`** (DFI) → taux USD/CDF du jour.
3. **POST `/api/requisitions`** → crée la réquisition (G01), calcul bi-devise.
4. **POST `/api/requisitions/{id}/valider-demande`** → DG + Admin (ou DG + DT pour HORIZON) ;
   interdiction de valider sa propre demande.
5. **POST `/api/ordres-depense`** (DFI) → résout le **palier** sur le montant USD, crée l'ordre (G02).
6. **POST `/api/ordres-depense/{id}/valider`** → validation **sortie de fonds** selon le palier
   (≤1000 : DFI seul ; 1001–10000 : DFI+DG+Admin+Président ; >10000 : Président).
7. **POST `/api/ordres-depense/{id}/executer`** (Caissier) → **refuse si bénéficiaire bloqué**,
   crée le bon de réception (G03), l'avance, le mouvement de caisse, calcule l'échéance de justification.
8. **POST `/api/avances/justifier`** → justification (G04), contrôle d'équilibre
   (trop-perçu → entrée de caisse ; dépenses > avance → complément).
9. **POST `/api/avances/verifier-retards`** → passe les avances échues en retard + crée les blocages.
10. **POST `/api/avances/blocages/{id}/lever`** (DFI) → lève un blocage.

## Moteur comptable OHADA (implémenté)
La comptabilisation est **automatique** (`app/comptabilite.py`) :
- Versement d'avance → **D 409 / C 571** (apuré au compte du bénéficiaire) ;
- Justification → **D charges [+ D 571 si solde rendu] / C 409** (apurement) ;
- Contrôle de partie double (D=C) avant toute insertion ; balance par compte.
Vérifié par un **test d'intégration bout-en-bout** (`tests/test_integration_decaissement.py`)
qui exécute tout le circuit et contrôle l'équilibre des écritures.

## Reste à faire (prochaines itérations)
- **Frontend** (interface web : réquisition, centre d'approbation, justification, dashboard DFI).
- États financiers complets (bilan/résultat/TFT — réutiliser la logique du prototype).
- Schémas comptables 100 % paramétrables (table `schema_comptable`), migrations Alembic.
- Notifications (email/WhatsApp), pièces jointes.
