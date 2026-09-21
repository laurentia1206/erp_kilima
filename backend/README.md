# ERP Kilima Holdings — moteur Django actif

L'application utilise Django et Django REST Framework pour l'API. `backend/`
regroupe le moteur, les justificatifs `uploads/` et les fichiers `.env`.
Le frontend Next.js est dans `../frontend/` ; voir son README. L'ancien
moteur FastAPI a été retiré du projet actif.

## Applications métier

Le dossier `apps/` contient les applications Django : approbations, trésorerie,
comptabilité, stocks, commercial, hôtel, transport, maintenance, engins,
groupe, RH, pilotage et éditions. `core/` conserve le socle partagé et des
alias pour les anciens imports. Chaque domaine possède ses routes ; les
domaines persistants possèdent leurs modèles et migrations.

Voir [le guide d’architecture](../docs/17-architecture-applications-django.md)
pour la répartition et la transition sans changement des tables existantes.

Les ressources métier utilisent des `ModelViewSet` avec des `ModelSerializer`
et des actions explicites pour les validations, paiements et clôtures.
Les rapports transversaux utilisent des `ViewSet`.
Voir [le guide ModelViewSet](../docs/19-model-viewsets.md) pour le routage,
la sérialisation, les transactions et la compatibilité des anciens imports.

## Utiliser l'installation existante

Pour continuer les tests sur la copie existante, depuis ce dossier :

```powershell
python ../demarrer_next.py
```

Ouvrir http://127.0.0.1:3000. `Demarrer-ERP.bat` et le lanceur racine
`../Demarrer-tests.bat` démarrent également cette copie de recette.
L'API seule peut être lancée avec `python ../demarrer_tests.py` sur le port
8012. Le serveur de développement doit rester limité à l'usage local.

La nouvelle interface est chargée au rafraîchissement de la page. Redémarrer
le serveur pour charger les corrections Python.

**Ne jamais initialiser, supprimer ou remplacer la base existante pour tester.**
Les scripts historiques de peuplement FastAPI ne sont pas nécessaires.

## Vérifier les changements

```powershell
python manage.py test core.tests --settings=kilima.test_settings
node --test tests/frontend-api.test.cjs tests/module-ux.test.cjs
```

Les tests Python créent une base en mémoire et désactivent les sauvegardes au
démarrage. Ils ne modifient pas `./kilima_dev.db`. Node est requis
uniquement pour les tests du contrat réseau et des outils de consultation.

La suite comprend le cycle G01 à G04, les refus de décaissement, les montants
comptables invalides, l'atomicité, les stocks, les autorisations par société,
les justificatifs et une restauration SQLite avec journal WAL.

## Migrations

La migration `0013_affectations_installation` crée la table d'affectations
utilisateur/société/rôle uniquement si elle manque. Elle conserve la clé
composite et laisse intactes les affectations existantes. Elle ne réinitialise
aucune donnée. Son retour arrière ne supprime volontairement pas cette table.

Après sauvegarde, l'équipe peut vérifier puis appliquer les migrations :

```powershell
python manage.py showmigrations
python manage.py migrate
```

La migration 0013 a été vérifiée sur une copie de la base existante et lors des
tests sur base vierge. Elle n'a pas été appliquée à la base de travail dans cette
intervention. Les corrections fonctionnent aussi sur sa table existante.

## Configuration

Les variables d'environnement du système priment sur `./.env`.

Le [guide de configuration complet](../docs/22-configuration-environnement.md)
décrit les réglages de base, sauvegardes, fichiers et HTTPS. Les modèles sont
`./.env.example` (local) et `./.env.production.example`
(hébergement PostgreSQL). `KILIMA_ENV_FILE` permet de choisir un autre fichier.
Ces fichiers proposent également un bloc MySQL commenté et un pilote optionnel
dans `requirements-mysql.txt`. La connexion MySQL est configurable ; son usage
métier exige encore le portage des migrations et du contexte d'audit. Voir le
guide avant toute bascule ; la configuration seule ne transfère pas les données.

| Variable | Usage |
|---|---|
| `ENVIRONMENT` | `dev` pour le local ; `production` active les garde-fous |
| `DEBUG` | `true` en développement ; obligatoirement `false` en production |
| `ALLOWED_HOSTS` | Hôtes séparés par des virgules ; local : `localhost,127.0.0.1,[::1]` |
| `SECRET_KEY` | Clé existante en local ; clé aléatoire d'au moins 50 caractères exigée en production |
| `DATABASE_URL` | Connexion à la base ; emplacement SQLite historique par défaut |
| `KILIMA_DB` | Remplace la connexion pour une copie de recette |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de session ; 720 minutes par défaut |
| `BACKUP_ON_STARTUP` | Sauvegarde quotidienne au démarrage ; `true` par défaut |
| `SECURE_SSL_REDIRECT` | Redirection HTTPS ; `true` par défaut en production |

Pour un accès local par une adresse réseau, ajouter explicitement le nom du
serveur à `ALLOWED_HOSTS`. En production, une clé de démonstration, `DEBUG=true`
ou les hôtes `*` provoquent un refus de démarrage.

Pour les tests sur copie, exemple PowerShell :

```powershell
$env:KILIMA_DB = 'sqlite:///../.build/qa/kilima_qa.db'
$env:BACKUP_ON_STARTUP = 'false'
python manage.py runserver 127.0.0.1:8012 --noreload
```

Cette commande suppose que la copie existe. Ne pas lancer `migrate` sur un
nouveau chemin en espérant y retrouver les données de travail.

## Préparation à la production

Le journal de traçabilité, ses contrôles d'accès et ses déclencheurs de base sont
décrits dans `../docs/20-journal-audit.md`. Lire ce guide avant toute intervention
SQL externe ou évolution des tables auditées.

Consulter `../docs/08-audit-django-et-ameliorations.md` pour les preuves de
validation et les travaux restants. La configuration et les tests livrés
ne constituent pas une certification de production.

Les versions actuellement installées (Django 5.1.4 / DRF 3.15.2) ont été
conservées pendant cette intervention pour isoler les changements. Django 5.1
ne reçoit plus de correctifs de sécurité : prévoir une mise à niveau testée
vers une série maintenue avant le déploiement. La série 5.2 LTS est une cible
à qualifier avec une version compatible de DRF.
[Calendrier officiel Django](https://www.djangoproject.com/download/),
[versions de Django REST Framework](https://www.django-rest-framework.org/community/release-notes/).

Le serveur de production, HTTPS, les secrets, PostgreSQL, les restrictions
d'accès réseau et la restauration doivent être validés ensemble. Si un proxy
termine HTTPS, sa configuration et la confiance accordée à ses en-têtes doivent
être définies avant activation du service.
[Consignes de déploiement Django](https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/).
