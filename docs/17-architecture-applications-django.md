# Architecture Django par domaine métier

Le moteur actif est dans `backend_django/`. L’interface reste dans
`backend/static/`. `backend/app/` conserve l’ancienne implémentation FastAPI
à titre historique ; ce n’est pas le serveur utilisé.

## Applications

| Application | Responsabilité |
|---|---|
| `core` | Sociétés, utilisateurs, rôles, tiers partagés, paramètres, audit, authentification et pièces jointes |
| `apps.approbations` | Réquisitions, paliers, validations et ordres de dépense |
| `apps.tresorerie` | Caisses, banques, paiements, avances à justifier et transferts |
| `apps.comptabilite` | Comptes, journaux, écritures, états financiers, analytique et TVA |
| `apps.stocks` | Articles, dépôts, mouvements, transferts et inventaires |
| `apps.commercial` | Achats, réceptions, ventes, factures, devis et livraisons |
| `apps.hotel` | Chambres, séjours, fiches techniques et consommation cuisine |
| `apps.transport` | Véhicules, chauffeurs, courses, contrats et carburant |
| `apps.maintenance` | Interventions, plans d’entretien et documents de flotte |
| `apps.engins` | Matériel, prestations et arrêts |
| `apps.groupe` | Opérations intersociétés |
| `apps.rh` | Dossiers, contrats, pointages, demandes, dettes, paie et décomptes |
| `apps.pilotage` | Files de tâches et règles de relance transversales |
| `apps.editions` | Documents PDF et Excel |

Chaque application dispose de son `AppConfig`, de ses routes et de ses vues.
Les domaines qui possèdent des données ont leurs modèles et migrations.
Pilotage et éditions utilisent les données existantes sans table supplémentaire.
Les services suivent leur domaine : calculs dans `apps/rh/`, écritures dans
`apps/comptabilite/services.py`, stocks dans `apps/stocks/services.py`.

Les appels entre applications restent internes au même projet et à la même
base. Les transactions entre domaines restent possibles. Les circuits de
validation, les droits et la portée par société des données sont conservés.

## Compatibilité

Les adresses `/api/...` et les réponses attendues par l’interface sont conservées.
`kilima/urls.py` appelle `core/urls.py`, qui assemble les routes des applications.
Les anciens modules `core.rh_finances`, `core.comptabilite`, etc. sont des
alias vers les nouveaux modules, sans duplication de leur code métier.
`core.models` réexporte les anciens noms pour les intégrations existantes.
Le nouveau code doit importer depuis l’application propriétaire.
Quelques vues de lecture historiques restent dans `core.views`, raccordées
aux routes de leur domaine.

Les tests transversaux restent dans `core/tests/`, car ils vérifient les cycles
entre modules. Les futurs tests spécifiques peuvent être ajoutés dans
`apps/<domaine>/tests/`. `manage.py test` sans étiquette les inclura également.

## Migrations

Les migrations historiques `core/0001` à `core/0020` sont conservées intactes
pour permettre la création d’une base neuve. Ensuite, les migrations
`0001_adoption_modeles` rattachent les modèles à leur nouvelle application,
puis `core/0021_applications_metier` retire leurs anciennes définitions.

Ces étapes utilisent `SeparateDatabaseAndState` sans opération physique.
Elles ne créent, ne renomment et ne suppriment aucune table. Les noms
historiques, notamment `core_rh...`, sont conservés explicitement. Seuls
l’historique des migrations et les types de contenu Django sont complétés.
Les anciens types de contenu restent présents ; aucune suppression automatique.

Ne pas supprimer les migrations historiques, utiliser `--fake`, ou recréer
la base pour cette transition. Vérifier `KILIMA_DB` / `DATABASE_URL`,
sauvegarder la base ciblée puis, depuis `backend_django/` :

```powershell
python manage.py migrate --plan
python manage.py migrate
python manage.py check
```

La base de tests `.build/qa/kilima_qa.db` a reçu la transition après sauvegarde.
Le fichier historique `backend/kilima_dev.db` n’a pas été modifié.
Une future modification des modèles RH passera par :

```powershell
python manage.py makemigrations rh
python manage.py migrate
```

## Vérifications

- 111 tests Django : circuits existants et contrats d’architecture.
- 14 tests JavaScript : navigation, filtres, concurrence et isolation de société.
- Aucun changement de migration manquant (`makemigrations --check --dry-run`).
- Transition sur copie : schéma physique identique, mêmes 100 tables métier
  et mêmes 2 401 lignes, comparées intégralement.
- Création d’une base vierge vérifiée par les tests Django.

L’avertissement `fields.W342` sur `UtilisateurSociete` préexistait. Cette table
garde sa clé composite historique et son accès spécifique.

Ces vérifications concernent SQLite et le serveur local. PostgreSQL et
l’hébergement de production restent un chantier distinct ; voir le guide
`15-preparation-cloud-et-approbations-mobiles.md`.
