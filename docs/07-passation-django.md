# Passation à l'équipe informatique — ERP KILIMA HOLDINGS sur Django

> Bascule effectuée le 2026-08-14. Le backend de production est désormais
> **Django 5.1 + Django REST Framework 3.15** (`backend/`). Depuis le
> regroupement du 20 septembre 2026, l'ancien moteur FastAPI est retiré.
> Ce document décrit le portage initial ; les guides 17 à 22 détaillent
> l'architecture et les réglages actuels.

## 1. Démarrer

```bash
cd backend
pip install django==5.1.4 djangorestframework==3.15.2 bcrypt python-jose
python manage.py runserver 127.0.0.1:8000
```

→ http://localhost:8000 sert le frontend ET l'API (mêmes URL qu'avant la
bascule : le frontend `backend/static/` n'a pas changé d'une ligne).
Comptes de démonstration : `*@kilima.cd` / `demo1234`.

⚠ **NE JAMAIS passer à Django 6** : incompatible avec Django REST Framework
(ImportError `cc_delim_re`). Rester sur Django 5.1.x + DRF 3.15.x.

## 2. Où sont les choses

| Quoi | Où |
|---|---|
| Base de données (dev) | `backend/kilima_dev.db` (SQLite) — données de test réelles de la DFI, **ne jamais réinitialiser** |
| Sauvegardes auto | `backend/backups/` (une par jour au démarrage, 14 conservées) |
| Secrets / config | `backend/.env` (non versionné — modèle : `backend/.env.example`) |
| Frontend | `backend/static/` (vanilla JS, servi par `core/frontend_views.py`) |
| Pièces jointes | `backend/uploads/` |
| Modèles (≈65 tables) | `backend/core/models.py` |
| Moteur comptable OHADA | `core/comptabilite.py` (post_ecriture : partie double D=C obligatoire) |
| Règles métier pures | `core/domain.py` (devises, paliers de validation, avances) |
| Services transverses | `core/services.py` (numérotation, paramètres, taux, audit, horodatages) |
| Vues par module | `core/*_views.py` (compta, décaissements, caisse, commercial, ventes, intersociété, transport, config, analytique) |

## 3. Le schéma appartient aux migrations Django

`migrate --fake-initial` a été appliqué : la migration `core/0001_initial`
décrit l'existant et est marquée appliquée. **Toute évolution du schéma passe
désormais par** :

```bash
python manage.py makemigrations core
python manage.py migrate
```

Exception : la table `utilisateur_societe` a une **clé primaire composite**
(utilisateur, société, rôle) que l'ORM Django ne gère pas. Elle reste
`managed=False` ; ses INSERT/DELETE se font en SQL brut dans
`core/config_views.py` (`_inserer_affectation` / `_supprimer_affectation`).
Ne pas la « corriger » avec l'ORM.

## 4. Conventions à respecter absolument

Ces conventions viennent du portage à parité stricte avec FastAPI — les
casser casserait des comportements que le frontend et la comptabilité
attendent :

1. **Horodatages** : jamais `auto_now_add`. Utiliser
   `services.maintenant()` (UTC naïf, à la seconde — format
   CURRENT_TIMESTAMP de SQLite) pour les colonnes d'insertion, et
   `services.maintenant_micro()` (avec microsecondes) là où l'ancien code
   posait un `datetime.now()` explicite. `USE_TZ = False` est obligatoire.
2. **Erreurs dans les flux d'écriture** : jamais `return Response(...)` nu
   dans un bloc `transaction.atomic()` — utiliser `refus(...)`
   (`core/erreurs.py`) qui marque la transaction pour rollback. Sinon des
   écritures partielles seraient committées (numéros de pièces consommés,
   lignes orphelines).
3. **Montants** : les endpoints qui répondaient via un `response_model`
   Pydantic sérialisent les Decimal en **chaînes** (`"100.00"`) ; les dicts
   construits à la main utilisent `float()`. Respecter l'existant endpoint
   par endpoint.
4. **Écritures comptables** : toujours via `comptabilite.post_ecriture`
   (équilibre D=C vérifié, numérotation `{journal}-{année}-{seq:05d}`).
   Les pièces des flux sensibles naissent en statut `en_attente` (validation
   comptable dans « Pièces en attente »).
5. **UUID en SQL brut** : stockés en hexadécimal 32 caractères sans tirets
   (`uuid.UUID(x).hex`).

## 5. Tests et preuve de parité

- La suite Django active vit dans `backend/core/tests/` ; les tests JavaScript
  de l'interface sont dans `backend/tests/`. La suite pytest historique
  FastAPI a été retirée avec l'ancien moteur.
- Chaque phase du portage a été validée par des bancs de parité
  (mêmes appels rejoués sur FastAPI et Django, réponses et bases comparées) :
  détail phase par phase dans `docs/06-plan-portage-django.md`.

## 6. Mise en production (PostgreSQL)

`DATABASE_URL` dans `backend/.env` accepte une URL PostgreSQL
(`postgresql+psycopg://user:mdp@hote/base`) — `kilima/settings.py` la parse.
Étapes : provisionner la base, exécuter `python manage.py migrate` (cette
fois les tables seront réellement créées), transférer les données, restreindre
`ALLOWED_HOSTS`/CORS, passer `DEBUG = False`, servir derrière un vrai serveur
(gunicorn/uvicorn + nginx).

## 7. L'archive FastAPI

L'ancien code FastAPI et ses lanceurs ont été retirés du projet actif le
20 septembre 2026. Une archive de sécurité locale a été conservée dans
`.build/ancien-backend-fastapi-avant-regroupement.zip` ; elle n'est pas
distribuée avec le projet. Les documents, configurations, sauvegardes et
la base historique ont été transférés sans modification dans le backend Django.
Le dossier `backend/tests/` contient désormais les tests JavaScript actifs.
