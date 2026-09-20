# Frontend Next.js — Kilima Holdings

Next.js 16.3.5, React 19.3 et TypeScript. L'API, les règles métier, les permissions,
la traçabilité et les documents PDF/Excel restent dans Django.

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

## Structure et état de migration

| Dossier | Rôle |
|---|---|
| `app/` | App Router, métadonnées, styles compilés et page d'erreur |
| `components/` | Connexion, navigation, choix de société, accueil et écrans métier React |
| `components/business/` | Suivi des tâches, audit, stock, taux, articles, chambres ; dialogues, tableaux et rapports partagés |
| `lib/` | Types, liste des vues et chargement unique des modules |
| `legacy/` | Écrans métier existants et adaptateur de transition vers React |
| `scripts/` | Préparation des assets publics |
| `tests/` | Contrats de l'adaptateur, proxy, filtres, délais, tri et exports CSV |
| `public/legacy/` | Copie générée des fichiers JS/CSS ; ne pas modifier directement |

Il ne s'agit pas encore d'une réécriture intégrale de tous les formulaires en
composants React. Les plus de 60 vues métier sont intégrées sans iframe ; leurs
fonctions existantes sont conservées. React possède l'enveloppe, l'accueil et
six écrans métier : `pilotage`, `audit`, `stock`, `taux`, `articles`, `hotel-chambres`, avec leurs formulaires,
dialogues et rapports. Les scripts historiques possèdent le contenu des autres
vues et leurs fenêtres modales. La conversion future doit se faire vue par vue, avec contrôle
des droits, de la société active, des saisies, des validations et des exports.

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
