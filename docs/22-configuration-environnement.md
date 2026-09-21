# Configuration d'environnement du serveur Django

## Fichiers fournis

- `backend/.env` : configuration privée utilisée sur cet ordinateur. Les valeurs
  existantes, y compris la clé et la connexion, sont conservées. Ne pas le publier.
- `backend/.env.example` : modèle local sans secret, utilisable pour une nouvelle installation.
- `backend/.env.production.example` : modèle PostgreSQL/HTTPS à compléter pour l'hébergement.

L'archive du projet contient les deux modèles, jamais le `.env` privé.
Le lanceur `Demarrer-tests.bat` génère un `.env` complet et une nouvelle clé
si ce fichier manque ; il ne remplace jamais une configuration existante.

## Priorité et format

Django lit `backend/.env`, puis applique les variables de l'environnement du
processus, qui ont priorité. `KILIMA_ENV_FILE`, défini dans le système avant
le démarrage, permet de choisir un autre fichier. Un chemin relatif est résolu
depuis `backend/` ; un fichier explicitement désigné mais absent bloque le démarrage.

Une variable par ligne : `NOM=valeur`. Les guillemets simples ou doubles autour
d'une valeur sont facultatifs. Utiliser UTF-8. Placer les commentaires sur des
lignes séparées : le caractère `#` dans une valeur reste un caractère littéral.
Les expressions `${VARIABLE}` ne sont pas développées. Les chemins Windows
peuvent utiliser `/`. Les changements nécessitent un redémarrage du serveur.

**Les tests locaux restent isolés.** `Demarrer-tests.bat` impose la base existante
`data/kilima_test.db` dans la livraison, ou `.build/qa/kilima_qa.db` dans le projet.
Il impose aussi le mode local HTTP, les hôtes locaux et la désactivation de la
sauvegarde au démarrage. Utiliser ce lanceur pour continuer les tests.
La variable `KILIMA_DB` remplace `DATABASE_URL` : la retirer du service de production.

## Paramètres pris en charge

| Variable | Utilisation |
|---|---|
| `APP_NAME` | Nom technique de l'application, renvoyé par le contrôle de disponibilité |
| `ENVIRONMENT` | `dev`, `development` ou `test` en local ; `production` pour l'hébergement |
| `DEBUG` | Affichage des erreurs détaillées ; obligatoire à `false` en production |
| `ALLOWED_HOSTS` | Noms DNS ou adresses IP autorisés, séparés par des virgules, sans protocole ni port |
| `DATABASE_URL` | Connexion SQLite, PostgreSQL ou MySQL (voir limite MySQL ci-dessous) |
| `KILIMA_DB` | Remplacement prioritaire de la connexion, notamment pour la recette |
| `DB_TIMEOUT_SECONDS` | Attente de verrou SQLite ou délai de connexion PostgreSQL/MySQL, entier positif, défaut 20 |
| `DB_CONN_MAX_AGE` | Durée de réutilisation des connexions PostgreSQL/MySQL en secondes, défaut 60 ; 0 désactive la réutilisation |
| `DB_SSLMODE` | Mode SSL PostgreSQL, dont `require` ou `verify-full` selon l'hébergeur |
| `DB_SSLROOTCERT` | Chemin du certificat d'autorité PostgreSQL ; vide pour le comportement standard du pilote |
| `DB_MYSQL_SSL_MODE` | MySQL seulement : `DISABLED`, `PREFERRED`, `REQUIRED` (défaut), `VERIFY_CA`, `VERIFY_IDENTITY` |
| `DB_MYSQL_SSL_CA` | Certificat d'autorité MySQL, requis avec `VERIFY_CA` ou `VERIFY_IDENTITY` |
| `DB_MYSQL_SSL_CERT` | Certificat client MySQL facultatif, à fournir avec sa clé |
| `DB_MYSQL_SSL_KEY` | Clé privée du certificat client MySQL, à fournir avec le certificat |
| `SECRET_KEY` | Clé de signature des sessions ; aléatoire et au moins 50 caractères en production |
| `ALGORITHM` | Signature JWT : `HS256` par défaut, ou `HS384`, `HS512` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de validité des sessions, entier positif, défaut 720 minutes |
| `SECURE_SSL_REDIRECT` | Redirection vers HTTPS ; activée par défaut en production |
| `TRUST_PROXY_HTTPS` | Reconnaissance de `X-Forwarded-Proto: https`, désactivée par défaut |
| `SECURE_HSTS_SECONDS` | Durée HSTS ; 0 désactive cet en-tête pendant la préparation HTTPS |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Extension HSTS aux sous-domaines, défaut `false` |
| `SECURE_HSTS_PRELOAD` | Ajout du marqueur HSTS preload, défaut `false` ; ne réalise aucune inscription externe |
| `UPLOADS_DIR` | Dossier privé des pièces jointes, défaut `uploads` sous `backend/` |
| `MAX_UPLOAD_MB` | Limite par pièce jointe, entier positif, défaut 10 Mo |
| `BACKUP_ON_STARTUP` | Copie SQLite au premier démarrage du jour ; ne sauvegarde pas PostgreSQL |
| `BACKUP_DIR` | Dossier des copies SQLite ; vide = `backups` à côté de la base active |
| `BACKUP_KEEP_COUNT` | Nombre de copies quotidiennes conservées par nom de base, défaut 14, minimum 1 |

Les booléens acceptent `true`/`false`, `1`/`0` et `yes`/`no`.
Les options PostgreSQL `sslmode`, `sslrootcert` et `connect_timeout` peuvent aussi
figurer dans l'URL ; les variables correspondantes explicites sont prioritaires.
Les options inconnues sont refusées pour éviter une configuration silencieusement ignorée.
Pour MySQL, utiliser les variables `DB_MYSQL_*`, sans options dans l'URL.

## Connexion à la base

Exemple SQLite relatif à `backend/` dans la livraison :

```dotenv
DATABASE_URL=sqlite:///../data/kilima_test.db
```

Exemple PostgreSQL (valeurs fictives) :

```dotenv
DATABASE_URL=postgresql://kilima:MOT_DE_PASSE@serveur-db:5432/kilima_erp
DB_SSLMODE=verify-full
DB_SSLROOTCERT=/etc/kilima/postgresql-ca.crt
```

Encoder les caractères réservés dans l'utilisateur et le mot de passe de l'URL :
`@` devient `%40`, `#` devient `%23`, `/` devient `%2F`, `%` devient `%25`.
Ne pas copier les identifiants réels dans les captures d'écran ou les échanges publics.

Changer `DATABASE_URL` ne transfère aucune donnée. La reprise sur PostgreSQL,
les migrations, les déclencheurs d'audit, les pièces jointes et la restauration
doivent être vérifiés avant de basculer l'exploitation. Aucun serveur PostgreSQL
Sygma Cloud n'a été connecté ni validé lors de cette préparation.

### Configuration MySQL préparée — compatibilité métier à terminer

Les trois fichiers `.env`, `.env.example` et `.env.production.example` contiennent
désormais des blocs PostgreSQL et MySQL commentés. Pour préparer un changement,
**remplacer l'unique ligne `DATABASE_URL` active**, puis activer les options du
moteur choisi. Ne pas cumuler plusieurs lignes actives de même nom.

Exemple MySQL (identifiants fictifs) :

```dotenv
DATABASE_URL=mysql://kilima:MOT_DE_PASSE@serveur-mysql:3306/kilima_erp
DB_TIMEOUT_SECONDS=20
DB_CONN_MAX_AGE=60
DB_MYSQL_SSL_MODE=VERIFY_IDENTITY
DB_MYSQL_SSL_CA=/etc/kilima/mysql-ca.crt
DB_MYSQL_SSL_CERT=
DB_MYSQL_SSL_KEY=
```

Le connecteur Django prépare l'encodage `utf8mb4`, le mode strict et l'isolation
`read committed`. PostgreSQL utilise le port 5432 par défaut ; MySQL, 3306.
Les options SSL PostgreSQL ne sont pas transmises au pilote MySQL.
Pour un serveur MySQL local de développement sans TLS, choisir explicitement
`DB_MYSQL_SSL_MODE=DISABLED` et laisser les chemins de certificats vides.

Le pilote MySQL est optionnel, pour conserver l'installation SQLite actuelle :
depuis la racine du projet, exécuter `python -m pip install -r backend/requirements-mysql.txt`.
Selon le système, son installation peut nécessiter les bibliothèques clientes natives.
Le choix de `mysqlclient` et du mode strict suit la
[documentation Django](https://docs.djangoproject.com/en/5.1/ref/databases/#mysql-db-api-drivers) ;
les options TLS sont celles du
[pilote mysqlclient](https://github.com/PyMySQL/mysqlclient/blob/main/src/MySQLdb/connections.py).

**La configuration MySQL ne rend pas encore l'ERP exploitable sur MySQL.**
Les migrations d'audit (`core/migrations/_audit_schema_v1.py`) n'acceptent
actuellement que SQLite et PostgreSQL. Il faut porter les déclencheurs et le
contexte d'audit, vérifier les autres migrations et requêtes SQL, puis tester
les circuits métier sur une base MySQL isolée avant une bascule. Aucun mécanisme
d'audit n'a été supprimé ou contourné. Aucun serveur MySQL n'a été connecté ici ;
seule la construction et la validation de sa configuration sont testées.

## À préparer avec l'informaticien / Sygma Cloud

1. Le domaine de l'ERP et son certificat HTTPS.
2. L'adresse, le port, le nom de la base PostgreSQL, un compte dédié et son mot de passe.
3. Les modalités SSL et le certificat d'autorité de la base, si nécessaire.
4. Un volume persistant privé pour les pièces jointes et un plan de sauvegarde
   de la base **et** des fichiers, avec un test de restauration.
5. Un service Django de production, son environnement et un proxy HTTPS.

Activer `TRUST_PROXY_HTTPS=true` uniquement si le proxy de confiance supprime
les valeurs transmises par les visiteurs et définit lui-même `X-Forwarded-Proto`.
L'accès direct au serveur Django doit être restreint. Configurer aussi la limite
de taille des requêtes du proxy en cohérence avec `MAX_UPLOAD_MB`.

Générer la clé sur le serveur avec :

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Remplacer uniquement la valeur `SECRET_KEY` du modèle de production. Une rotation
de clé invalide les sessions existantes, sans modifier les mots de passe.
Le modèle laissé avec sa clé d'exemple provoque volontairement un refus de démarrage.
Le compte du service doit être le seul compte ordinaire autorisé à lire les secrets
et doit pouvoir écrire dans les dossiers de documents et de sauvegarde.

Le port d'écoute et les processus sont définis par le service d'hébergement ;
en local, utiliser `python demarrer_tests.py --port 8012`. Le `.env` ne lance pas
le serveur et ne configure pas le pare-feu. Les notifications SMTP ne sont pas
connectées à un service d'envoi dans cette livraison : aucune variable de courrier
sans effet n'a été ajoutée. Les règles métier et les paramètres propres aux sociétés
restent dans l'application et dans sa base, pas dans le `.env`.

Le français et le fuseau `Africa/Lubumbashi` restent ceux de l'installation.
La gestion historique des dates est conservée. Lire aussi la section production
de `backend/README.md` avant tout déploiement, notamment la mise à niveau
du moteur Django actuellement installé.
