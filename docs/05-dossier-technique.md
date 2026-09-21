# Dossier technique — ERP KILIMA HOLDINGS

> Document historique du portage. Depuis le 20 septembre 2026, seul Django
> est livré dans `backend/` ; les anciens scripts et lanceurs FastAPI ont été retirés.
> Pour installer et démarrer la version actuelle, suivre `LIRE-MOI.md` à la racine.

> À destination de l'équipe informatique pour la reprise et le déploiement.
> État au 2026-07-24 · 89 tests d'intégration passants.

## 1. Stack technique

| Couche | Technologie | Version |
|---|---|---|
| Langage backend | **Python** | 3.12 |
| Framework API | **FastAPI** | 0.115 |
| Serveur ASGI | **Uvicorn** | 0.34 |
| ORM | **SQLAlchemy 2** (style 2.0, `Mapped[]`) | 2.0.36 |
| Validation | **Pydantic v2** (+ pydantic-settings pour la config) | 2.10 |
| Base de données | **SQLite** en développement · **PostgreSQL 14+** visé en production (driver psycopg 3 déjà inclus) | — |
| Authentification | **JWT** (python-jose) + **bcrypt** pour les mots de passe | — |
| Frontend | **JavaScript vanilla** (aucun framework, aucun build), HTML/CSS maison, icônes Tabler (CDN) | ES2020 |
| Tests | **pytest** + TestClient FastAPI (tests d'intégration bout-en-bout sur SQLite mémoire) | 8.3 |

Volumes de code indicatifs : ~9 800 lignes Python (backend), ~5 400 lignes JavaScript (frontend monofichier), ~600 lignes CSS.

## 2. Architecture

Monolithe API-first : FastAPI sert à la fois l'API REST (`/api/*`) et le frontend statique (`/static`, page unique `index.html` + `app.js`). Aucune étape de build frontend — les fichiers statiques sont servis tels quels avec des en-têtes no-cache.

```
backend/
  app/
    main.py            # point d'entrée FastAPI, montage des routers + static
    config.py          # settings (pydantic-settings, lit backend/.env)
    database.py        # engine SQLAlchemy + session par requête
    models.py          # TOUT le schéma ORM (~60 tables)
    deps.py            # auth JWT + contrôle d'accès PAR SOCIÉTÉ (rôles, héritage)
    security.py        # bcrypt + JWT
    services.py        # numérotation des pièces, paramètres, taux du jour, audit
    comptabilite.py    # moteur comptable OHADA (écritures équilibrées D=C)
    plan_comptable.py  # plan SYSCOHADA révisé chargé à la création de chaque société
    etats_financiers.py# bilan / compte de résultat / cockpit
    domain/            # logique métier pure sans DB (money, workflow, avances)
    routers/           # 1 fichier = 1 module fonctionnel :
      auth, taux, requisitions, ordres_depense, avances, approbations,
      caisse, transferts, pieces_jointes, lecture, config (administration),
      compta (écritures, revue, lettrage, rapprochement), analytique,
      commercial (articles, tiers, achats, POS), ventes (devis→facture→règlement),
      intersociete (miroirs, réceptions, traçabilité), transport (flotte, courses)
  static/              # frontend : index.html, app.js, styles.css
  scripts/             # seed, migrations idempotentes, sauvegarde/restauration
  tests/               # 89 tests d'intégration (métier + comptabilité vérifiée)
  uploads/             # pièces jointes (justificatifs)
  backups/             # sauvegardes auto de la base SQLite
  kilima_dev.db        # ⚠ base de DÉVELOPPEMENT — contient les données de test réelles
```

## 3. Points d'architecture importants

- **Multi-société côté serveur** : chaque requête vérifie l'affectation utilisateur ↔ société ↔ rôle (`deps.assert_acces_societe`). Le `societe_id` n'est jamais un paramètre de confiance. Les rôles personnalisés héritent des droits d'un rôle de base (`Role.herite_de`, résolution en chaîne).
- **Comptabilité générée, jamais saisie deux fois** : chaque opération métier (vente, avance, réception, course…) produit son écriture équilibrée via `comptabilite.post_ecriture` (contrôle D=C avant insertion). Les flux sensibles arrivent en statut `en_attente` et passent par l'écran « Pièces en attente » (reclassement, éclatement, ventilation analytique, justificatifs).
- **Intersociétés** : les tiers « groupe » sont liés à leur société (`Tiers.societe_liee_id`) ; les documents miroir (commande→devis, facture vente→facture achat) sont créés automatiquement dans les livres de l'autre société, chacune gardant sa validation. Règlements réels double-face.
- **Bi-devise USD/CDF** : natif au niveau ligne (taux du jour fixé par le DFI, table `taux_change`).
- **Numérotation** : séquences par société/année/type (`SequenceCompteur`), préfixes dans `services.PREFIXES` (REQ, ODP, FV, FC, BL, RI…).
- **Audit** : toutes les actions sensibles tracées (`services.enregistrer_audit`).

## 4. Base de données & migrations

- Schéma défini dans `models.py` ; `database/schema_v1.sql` est le schéma PostgreSQL historique de la V1 (les tables ajoutées depuis sont créées par `Base.metadata.create_all`).
- **Migrations** : scripts idempotents dans `scripts/migrate_*.py` (ALTER TABLE + create_all), à exécuter dans l'ordre sur toute base existante. Pas d'Alembic pour l'instant — **recommandation : introduire Alembic avant la production**.
- **Protection des données** : `scripts/init_dev_db.py` (réinitialisation totale) exige le drapeau `--je-confirme-effacer`. Sauvegarde quotidienne automatique au démarrage du serveur (`backups/`, 14 conservées) + `python -m scripts.sauvegarde_db` (`--lister`, `--restaurer`).

## 5. Lancer le projet

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# .env : DATABASE_URL (sqlite:///kilima_dev.db en dev), SECRET_KEY
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
→ application sur http://localhost:8000 · documentation API interactive sur **/docs** (OpenAPI/Swagger auto-générée — 190+ endpoints).
Tests : `python -m pytest -q` (≈ 3 min, aucune dépendance externe).

## 6. Checklist de mise en production (recommandations)

1. **Versionner** : `git init` + dépôt distant (le projet n'est pas encore sous git).
2. **PostgreSQL** : créer la base, jouer `schema_v1.sql` + `seed_v1.sql`, puis les `migrate_*.py` dans l'ordre ; ou générer le schéma complet via `create_all` sur base vierge + seed. Basculer `DATABASE_URL` (postgresql+psycopg://…).
3. **Secrets** : `SECRET_KEY` robuste dans `.env`, jamais commité.
4. **CORS** : restreindre `allow_origins` (actuellement `*` dans `main.py`).
5. **HTTPS / reverse proxy** : Nginx ou Caddy devant Uvicorn (plusieurs workers).
6. **Sauvegardes prod** : pg_dump planifié (le mécanisme actuel de backup vise SQLite).
7. **Comptes démo** : supprimer/désactiver les comptes `*@kilima.cd` / `demo1234` du seed.
8. **Uploads** : servir `uploads/` hors racine web, prévoir un antivirus si exposé.
9. **Alembic** pour les migrations futures.

## 7. Fonctionnel couvert (résumé)

Décaissements G01→G04 avec paliers de validation ; caisses bi-devise (sessions, billetage, rapport Z, transferts double validation) ; POS façon Odoo (multi-paiements USD/CDF/mobile money/crédit, remises, retours, fidélité) ; cycle de vente (devis→commande→BL→facture→règlements, encours clients) ; achats (commandes, réceptions 3 voies, frais accessoires) ; intersociétés (PO miroir, réception bon/mauvais/manquant, confirmation transporteur, manquants imputés, traçabilité par n° producteur) ; transport KAKO Logistique (flotte, fiches de course, sous-traitance, maintenance, rentabilité) ; comptabilité OHADA complète (grand livre, balance, lettrage, rapprochement, analytique avec export/impression, états financiers SYSCOHADA) ; administration (sociétés, agents, rôles avec héritage, tiers).
