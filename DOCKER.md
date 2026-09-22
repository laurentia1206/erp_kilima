# Livraison Docker — ERP Kilima Holdings

## Contenu et état de validation

`docker-compose.yaml` fournit PostgreSQL 17, un service ponctuel de migrations, Django
avec Gunicorn, Next.js/React/Tailwind et Nginx. Deux volumes conservent la base et
les pièces jointes. Seul Nginx est publié, sur `127.0.0.1:8080` par défaut.
Les images ne contiennent ni `.env`, ni bases locales, ni pièces jointes.

Organisation des fichiers :

```text
backend/
  Dockerfile
  requirements-production.txt
  deployment/                 # Démarrage, disponibilité, premier administrateur
frontend/
  Dockerfile
  nginx.conf
docker-compose.yaml
.dockerignore
.env.docker.example
DOCKER.md
```

Les deux Dockerfiles utilisent la racine du dépôt comme contexte de construction,
comme indiqué dans Compose. Pour les construire séparément, depuis cette racine :
`docker build -f backend/Dockerfile -t kilima-backend:local .` et
`docker build -f frontend/Dockerfile -t kilima-frontend:local .`.
Le backend conserve l'accès aux assets historiques de `frontend/legacy/`.

Cette configuration démarre une **installation neuve**. Elle ne convertit pas
automatiquement la base SQLite Windows vers PostgreSQL. Les permissions et
circuits de validation restent ceux du logiciel actuel.

**Docker n'est pas disponible sur le poste de livraison.** Les fichiers et les
archives sont contrôlés ; la construction des images, les migrations PostgreSQL
et le démarrage des conteneurs doivent encore être testés sur le serveur cible.
Django 5.1.4 est conservé pour livrer la version actuelle : cette série n'est plus
maintenue. Qualifier une version maintenue et ses dépendances avant l'ouverture
Internet. Cette livraison n'est pas une certification de production.

## Prérequis

- Serveur Linux avec Docker Engine et Docker Compose v2, ou Docker Desktop
  configuré en conteneurs Linux sur Windows.
- Accès aux registres Docker, npm et PyPI pour construire les images.
- Vérifier que l'abonnement Sygma Cloud autorise une VM, Docker, des volumes
  persistants et un proxy HTTPS ; un hébergement PHP mutualisé seul ne suffit pas.
- Base de dimensionnement à ajuster : 4 vCPU, 8 Go de RAM, stockage SSD permettant
  de conserver les pièces jointes et plusieurs sauvegardes.

## Démarrer une installation neuve

Extraire le ZIP du code. Le ZIP Docker seul est un complément : placer ses fichiers
à la racine du même projet. Exécuter toutes les commandes depuis cette racine.
Pour remplacer l'ancienne livraison, extraire le nouveau code dans un dossier
propre ou retirer l'ancien `compose.yaml` après sauvegarde : Docker Compose
lui donnerait priorité sur `docker-compose.yaml` s'ils coexistent. Les anciennes
configurations de `docker/` sont remplacées par les emplacements ci-dessus.

1. Copier `.env.docker.example` vers `.env.docker`.
2. Générer deux secrets distincts en exécutant deux fois :

   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

3. Renseigner `SECRET_KEY` et `POSTGRES_PASSWORD`. Ne pas réutiliser le `.env`
   local Windows. Conserver `.env.docker` dans un coffre ; sous Linux, appliquer
   `chmod 600 .env.docker`. Les secrets URL-safe générés évitent les caractères
   `$` interprétés par Compose. Aucune clé n'est fournie dans la livraison.
4. Vérifier sans afficher les secrets, construire puis démarrer :

   ```sh
   docker compose --env-file .env.docker config --quiet
   docker compose --env-file .env.docker build --pull
   docker compose --env-file .env.docker up -d
   docker compose --env-file .env.docker ps -a
   docker compose --env-file .env.docker logs --tail=100 migrate backend frontend web
   ```

   `migrate` doit terminer avec le code 0 ; les autres services deviennent sains.
   Les dépendances attendent la disponibilité de PostgreSQL, les migrations,
   Django puis Next.js avant d'ouvrir Nginx.
5. Créer le premier administrateur sur une base neuve :

   ```sh
   docker compose --env-file .env.docker exec backend python /app/backend/deployment/bootstrap_admin.py
   ```

   Saisir l'adresse choisie (par exemple `admin@kilimaholdings.com`), le nom et
   un mot de passe personnel, saisi masqué. Le script refuse de remplacer un
   compte existant ou de créer un second administrateur initial. Le compte gère
   les utilisateurs et la sécurité, **sans affectation ni droit métier sur les
   sociétés**. Sur une base existante sans super administrateur, la commande
   du projet `python manage.py initialiser_super_admin adresse@exemple.com`
   active un compte existant et actif. `createsuperuser` ne s'applique pas au
   modèle spécifique de l'ERP.
6. Ouvrir http://127.0.0.1:8080 sur le serveur, ou utiliser un tunnel SSH :
   `ssh -L 8080:127.0.0.1:8080 utilisateur@serveur`.
   Vérifier `/api/health`, connexion, permissions, pièces jointes et exports.

Une base neuve ne contient pas les sociétés, opérations et paramètres des tests.
Leur reprise et la qualification des circuits complets précèdent l'exploitation.

## HTTPS / Sygma Cloud

Le domaine de production du frontend est `https://kilimaholdings.com`, défini par
`APP_URL` dans `.env.docker`. Il est fourni à la construction de l'image Next.js ;
reconstruire l'image après un changement. Le développement Windows conserve
`http://127.0.0.1:3000` dans `frontend/.env.example`.

Configurer ce domaine et le certificat chez l'hébergeur, puis un proxy HTTPS vers
`http://127.0.0.1:8080`, avec redirection HTTP vers HTTPS. Ne publier que 80/443.
Le proxy doit conserver le Host d'origine et imposer les en-têtes de transfert.
`DJANGO_API_URL=http://backend:8000` reste une adresse privée au serveur.

HTTPS et HSTS sont appliqués par le proxy public. Les liaisons locales entre
services restent HTTP ; `SECURE_SSL_REDIRECT=false` dans Django évite une boucle
de redirection vers son nom interne. Ne pas exposer Django ou PostgreSQL.
Si le proxy est sur une autre machine, adapter HTTP_BIND, filtrer l'accès à son
IP et protéger la liaison ; ne pas publier simplement 8080 sur Internet.

Nginx remplace les en-têtes d'adresse contre leur falsification. Pour retrouver
l'IP utilisateur dans ses journaux derrière le proxy de l'hébergeur, configurer
`set_real_ip_from` pour les seules IP du proxy maîtrisé, puis
`real_ip_header X-Forwarded-For`. Ne jamais faire confiance à tous. Le journal
d'audit Django utilise actuellement REMOTE_ADDR : dans cette architecture il
verra l'adresse du relais Next.js. La restitution de l'IP d'origine dans ce
journal nécessite une adaptation distincte de la confiance entre proxys ; elle
n'est pas ajoutée implicitement par cette configuration.

## Mise à jour

Sauvegarder d'abord. Arrêter les services métier pendant les migrations :

```sh
docker compose --env-file .env.docker stop web frontend backend
docker compose --env-file .env.docker build --pull
docker compose --env-file .env.docker run --rm migrate
docker compose --env-file .env.docker up -d
```

En cas d'échec, analyser avant de rouvrir aux utilisateurs. Ne jamais exécuter
`docker compose down -v` : cette commande supprime les volumes. Après qualification,
l'informaticien peut verrouiller les images de base par digest pour reproduire
exactement le déploiement.

## Sauvegarde PostgreSQL + documents (terminal Linux)

Prévoir des sauvegardes quotidiennes chiffrées hors serveur et un essai de
restauration régulier. Les commandes suivantes arrêtent les écritures pendant
la copie ; changer le nom du dossier à chaque sauvegarde et vérifier chaque
code de retour. `cp` évite les redirections binaires problématiques de PowerShell.

```sh
mkdir -p sauvegarde
docker compose --env-file .env.docker stop web frontend backend
docker compose --env-file .env.docker exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/kilima.dump'
docker compose --env-file .env.docker cp db:/tmp/kilima.dump sauvegarde/kilima.dump
docker compose --env-file .env.docker run --rm --no-deps --user root --entrypoint tar -v "$PWD/sauvegarde:/backup" backend -czf /backup/documents.tgz -C /app/backend/uploads .
docker compose --env-file .env.docker up -d
```

Conserver le code correspondant et une copie sécurisée de `.env.docker` avec
la sauvegarde. Ne pas modifier POSTGRES_PASSWORD sur un volume existant en
pensant changer le mot de passe SQL : la rotation doit aussi être faite dans
PostgreSQL, puis dans la configuration des services.

### Restauration dans un environnement distinct et vide

Copier `.env.docker` en `.env.restauration` et choisir un autre HTTP_PORT.
Utiliser `-p kilima-restauration` à chaque commande pour isoler les volumes.
Ne pas lancer l'application avant d'avoir restauré la base et les documents.

```sh
docker compose -p kilima-restauration --env-file .env.restauration up -d db
# Attendre que db soit sain avec la commande ps.
docker compose -p kilima-restauration --env-file .env.restauration cp sauvegarde/kilima.dump db:/tmp/kilima.dump
docker compose -p kilima-restauration --env-file .env.restauration exec -T db sh -c 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/kilima.dump'
docker compose -p kilima-restauration --env-file .env.restauration run --rm --no-deps --user root --entrypoint sh -v "$PWD/sauvegarde:/restore:ro" backend -c 'tar -xzf /restore/documents.tgz -C /app/backend/uploads && chown -R 10001:10001 /app/backend/uploads'
docker compose -p kilima-restauration --env-file .env.restauration up -d
```

Restaurer uniquement des sauvegardes de confiance vérifiées. Contrôler ensuite
les totaux comptables, les droits, les justificatifs et le journal d'audit.

## Reprise de vos tests actuels

Le ZIP privé contient des instantanés SQLite cohérents et les pièces jointes.
Pour retrouver les tests sous Windows, extraire le ZIP privé et celui du code
dans le même dossier parent, puis suivre `LIRE-MOI.md`.

**Un fichier SQLite ne se restaure pas dans un volume PostgreSQL.** La conversion
doit conserver et rapprocher les identifiants, les affectations à clé composite,
les séquences et le journal d'audit protégé. Aucun transfert automatique n'est
fourni ou exécuté ici. Les anciens `database/schema_v1.sql` et `seed_v1.sql` ne
représentent pas le schéma actuel : ne pas les exécuter pour l'initialiser.

MySQL reste un exemple de connexion historique : migrations et contexte d'audit
ne sont pas encore portés. Compose utilise donc PostgreSQL uniquement.

## Références

- [Ordre de démarrage Compose](https://docs.docker.com/compose/how-tos/startup-order/)
- [Auto-hébergement Next.js](https://nextjs.org/docs/app/guides/self-hosting)
- [Gunicorn](https://gunicorn.org/deploy/)
- [Versions maintenues Django](https://www.djangoproject.com/download/)
