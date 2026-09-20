# ERP Kilima Holdings — projet Django complet

Cette livraison contient le code actuel, l’interface, les tests, la documentation,
les pièces jointes disponibles et une copie des données utilisées pour les tests.
Le back-end est organisé en 13 applications Django métier et un socle commun.
Ses ressources API utilisent les `ModelViewSet` et `ModelSerializer` de
Django REST Framework. Les workflows conservent des actions explicites ;
l’organisation est expliquée dans `docs/19-model-viewsets.md`.

## Reprendre les tests sur un autre ordinateur Windows

1. Extraire **tout le ZIP** dans un dossier local.
2. Installer Python **3.12** avec son lanceur Windows `py`, puis **Node.js 24 LTS**.
3. Ouvrir `Installer-Windows.bat`. Une connexion Internet est nécessaire pour
   télécharger les dépendances Python et celles du frontend Next.js.
4. Ouvrir `Demarrer-Next.bat` (ou `Demarrer-tests.bat`) et garder sa fenêtre ouverte.
5. Aller sur **http://127.0.0.1:3000/** et utiliser les mêmes comptes et mots
   de passe que dans les tests actuels.

Si le port 3000 est déjà occupé, ouvrir le serveur existant ou utiliser :

```powershell
.venv\Scripts\python.exe demarrer_next.py --port 3002
```

La clé technique de l’installation d’origine n’est pas fournie. Au premier
démarrage, une nouvelle clé locale est générée dans `backend/.env` : il faut
se reconnecter, mais aucun compte utilisateur ni mot de passe n’est modifié.
Le lanceur refuse de créer une base vide si le fichier attendu manque.

## Contenu

| Emplacement | Contenu |
|---|---|
| `backend/` | Serveur actif Django, applications métier, migrations et tests |
| `frontend/` | Frontend Next.js, React et TypeScript |
| `frontend/legacy/` | Écrans métier conservés pendant leur conversion progressive en React |
| `backend/uploads/` | Pièces jointes stockées sur disque |
| `data/kilima_test.db` | Copie cohérente de la base de tests actuelle, migrations appliquées |
| `data/base_historique.db` | Copie de conservation de la base historique, sans réorganisation appliquée |
| `docs/` | Guides fonctionnels, architecture et préparation de l’hébergement |
| `backend/core/tests/`, `backend/tests/` | Tests Django et tests JavaScript de l'interface |
| `database/` | Scripts SQL historiques ; ne pas les exécuter sur les bases fournies |
| `MANIFESTE-SHA256.txt` | Empreintes permettant de vérifier les fichiers extraits |

Les dossiers virtuels Python, caches, historiques Git, sauvegardes redondantes
et le fichier `.env` d’origine sont exclus. Les données et comptes présents
dans les bases sont conservés : **cette archive est confidentielle**.

Le lanceur utilise uniquement `data/kilima_test.db` dans la livraison. Dans
le dossier de développement d’origine, il peut utiliser la copie existante
`.build/qa/kilima_qa.db`. Il ne démarre jamais sur la base historique.
Ne pas exécuter les anciens scripts de peuplement ou remplacer une base pour tester.
Faire des sauvegardes régulières de la base de tests et de `backend/uploads/`.

## Pour l’informaticien

La migration du frontend est décrite dans `docs/23-frontend-nextjs.md` et
`frontend/README.md`. La connexion, la navigation, l’accueil, le suivi des tâches,
le journal d'audit, l'état du stock, les taux de change, les articles et les chambres sont en React ; les
autres écrans restent intégrés via une couche de transition. Django
conserve l’API sur le port 8012 ; Next.js fournit l’interface sur le port 3000.


Les modèles `backend/.env.example` et `backend/.env.production.example`
regroupent la configuration locale et celle de l'hébergement PostgreSQL/HTTPS.
Consulter `docs/22-configuration-environnement.md` pour les paramètres et les
informations à demander à l'hébergeur. Le fichier privé `.env` est exclu du ZIP.

La super administration et les permissions sont décrites dans
`docs/21-super-administration-permissions.md`. Les identifiants provisoires du
compte global sont transmis séparément ; son mot de passe provisoire n'est pas
inclus dans cette archive.

Le journal est accessible dans **Pilotage → Journal de traçabilité** aux DFI
et administrateurs autorisés. Consulter `docs/20-journal-audit.md` pour sa
couverture, les exports, les protections et les précautions de maintenance.

Lire `docs/17-architecture-applications-django.md` pour la répartition du code,
les imports de compatibilité et la transition des migrations sans changement
des tables. Les migrations historiques restent nécessaires ; ne pas les supprimer.
Les documents RH stockés dans la base sont inclus dans sa copie.

Pour vérifier l’installation sans lancer le serveur :

```powershell
.venv\Scripts\python.exe demarrer_next.py --verifier
```

Pour les tests automatiques, depuis `backend/` :

```powershell
..\.venv\Scripts\python.exe manage.py test --settings=kilima.test_settings
node --test tests/frontend-api.test.cjs tests/module-ux.test.cjs tests/navigation.test.cjs tests/pilotage.test.cjs tests/systeme.test.cjs
```

Node.js est nécessaire pour le frontend Next.js et les tests JavaScript. Les tests Django
utilisent une base en mémoire. Le serveur fourni est destiné aux tests locaux ;
la préparation de la production est décrite dans
`docs/15-preparation-cloud-et-approbations-mobiles.md`.
