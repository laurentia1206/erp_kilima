# Frontend Next.js — Kilima Holdings

Next.js 16.3.5, React 19.3, TypeScript et Tailwind CSS 4. L'API, les règles métier, les permissions,
la traçabilité et les documents PDF/Excel restent dans Django.

La [charte d’interface](CHARTE_INTERFACE.md) décrit la reprise de la police,
des icônes Tabler et des composants historiques. Tailwind est compilé localement,
avec des classes préfixées `tw:` et sans Preflight pour préserver ces styles.

## Démarrage local

Depuis la racine du projet, après `Installer-Windows.bat` :

```powershell
python demarrer_next.py
```

Ouvrir http://127.0.0.1:3000. Le lanceur prépare les assets et utilise l'API locale
sur le port 8012. Si elle est arrêtée, il démarre la copie de recette existante.
Les mêmes comptes restent utilisables ; le changement de port demande une
nouvelle connexion, car les sessions sont stockées par origine du navigateur.

Sans le lanceur, depuis `frontend/` :

```powershell
npm ci
npm run dev
```

Django doit alors tourner séparément. Copier `.env.example` en `.env.local` pour
changer `DJANGO_API_URL`. Le lanceur de tests impose l'API locale afin de ne pas
accéder accidentellement à un serveur distant. Node.js 24 LTS est utilisé ici ;
le minimum déclaré par Next.js est 20.9.

## Adresses du frontend

| Environnement | Adresse publique | Configuration |
|---|---|---|
| Développement | `http://127.0.0.1:3000` | Copier `.env.example` en `.env.local` |
| Production | `https://kilimaholdings.com` | Copier `.env.production.example` en `.env.production.local` hors Docker |

`APP_URL` définit l'adresse de référence des métadonnées du frontend. La navigation
et les appels `/api/...` restent relatifs au site ouvert, aussi bien en local que
sur le domaine de production. `DJANGO_API_URL` reste l'adresse interne de Django :
ne pas y mettre `https://kilimaholdings.com`, qui pointerait le relais vers lui-même.

En production hors Docker, retirer les valeurs de développement de `.env.local`
(ce fichier a priorité). Avec Docker, `APP_URL` est fourni par `.env.docker` à la
construction et à l'exécution. Reconstruire le frontend après sa modification.
Le lanceur `demarrer_next.py` impose l'adresse locale et adapte son port si
`--port` est utilisé. Le domaine doit être relié au serveur et son certificat HTTPS installé chez
l'hébergeur ; ces fichiers ne modifient pas le DNS.

## Structure et état de migration

| Dossier | Rôle |
|---|---|
| `app/` | App Router, métadonnées, styles compilés et page d'erreur |
| `components/` | Connexion, navigation, choix de société, accueil et écrans métier React |
| `components/business/` | Pilotage, audit, stocks et inventaires, catalogues, réception et cuisine ; dialogues, tableaux et rapports partagés |
| `lib/` | Types, liste des vues et chargement unique des modules |
| `legacy/` | Services historiques partagés et adaptateur ; rendu métier neutralisé |
| `scripts/` | Préparation des assets publics |
| `tests/` | Contrats de l'adaptateur, proxy, filtres, délais, tri et exports CSV |
| `public/legacy/` | Copie générée des fichiers JS/CSS ; ne pas modifier directement |

Les **62 écrans métier du menu sont désormais rendus en React**, avec leurs
formulaires, dialogues et rapports natifs, en plus de la connexion et de l’accueil.
Les modules couvrent le pilotage, les réquisitions et validations, la trésorerie,
la comptabilité, les achats et ventes, le point de vente, les stocks, les RH,
l’hôtel, la cuisine, le transport, les engins, la maintenance et l’administration.

Les scripts historiques sont encore chargés pour l’authentification, la définition
des menus et les services partagés de transition. Leurs fonctions de rendu sont
neutralisées pour les 62 vues ; leur suppression complète est un chantier technique
séparé. Les API Django et les limites métier existantes restent applicables.

`next-adapter.js` assure cette frontière. Aucun mot de passe, clé Django ou accès
à la base de données ne doit être ajouté à Next.js. Les décisions d'autorisation
restent prises par l'API ; les menus ne constituent pas une protection serveur.
La super administration reste limitée aux utilisateurs.

Les vues React portent `data-react-owned` : le rendu historique et l'observateur
`ModuleUX` ne doivent jamais modifier leur contenu. Les dialogues React utilisent
un portail distinct (`react-modal-root`) et une fenêtre native avec gestion du
focus. `holdNavigation()` protège les saisies et les documents ouverts contre
les changements de société, de module et les déconnexions volontaires. Il ne
bloque pas l'expiration de session. La liste des vues migrées doit rester cohérente
dans `lib/runtime.ts`, `components/business/index.tsx` et `legacy/next-adapter.js`.
Chaque écran est remonté lors d'un changement d'utilisateur ou de société ; les
réponses tardives d'une consultation abandonnée ne sont pas appliquées.

Les URL `/espace/<vue>` restaurent l'écran après actualisation ; les vues
non autorisées ne sont pas ouvertes. La navigation utilise l'historique du
navigateur pour préserver les modules durant cette phase de migration.

## Vérifications et compilation

```powershell
npm test
npm run typecheck
npm run build
npm start
```

Exécuter les tests avec Node.js 24 (lecture native des utilitaires TypeScript).

`npm run build` prépare les scripts métier, compile les composants et vérifie
TypeScript. `npm start` sert la compilation sur le port 3000. L'adresse Django
est lue côté serveur : redémarrer Next.js après une modification de `DJANGO_API_URL`.
En production, exposer Next.js derrière HTTPS et conserver Django sur le réseau
privé. La route serveur `/api/[...path]` transmet les autorisations, les formulaires,
les fichiers et les exports sans répétition automatique des écritures ni cache.
Les données restent celles de Django. Les corps envoyés sont bornés à 16 Mo
par défaut (`API_MAX_BODY_MB`) et transmis avec une longueur connue, compatible
avec Django/WSGI. Ajuster cette limite au-dessus de `MAX_UPLOAD_MB` du backend.

L'ancien accès de comparaison au port 8012 est conservé pendant la migration ;
Django y lit `frontend/legacy/index.html`. Le chemin `/static/` de compatibilité
utilise les mêmes sources, sans copie concurrente dans `backend/`.

Documentation de référence : [installation Next.js](https://nextjs.org/docs/app/getting-started/installation),
[routes serveur](https://nextjs.org/docs/app/api-reference/file-conventions/route).
