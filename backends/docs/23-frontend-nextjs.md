# Passage du frontend à Next.js

Le frontend actif est désormais dans `frontend/` : Next.js, React et TypeScript.
Le backend Django reste dans `backend/`. Les API et les circuits métier sont
conservés. Le point d'entrée de tests est http://127.0.0.1:3000 avec
`Demarrer-Next.bat` ou `Demarrer-tests.bat`.

La connexion, le menu latéral, le choix de société et l'accueil sont rendus par
React. Un seul module reste déplié à la fois ; les accès sont filtrés selon le
compte, et les changements de société sont protégés lorsqu'une opération est
en cours. Les règles d'autorisation définitives restent sur le serveur Django.

Les écrans métier sont intégrés à Next.js via une couche de transition ; leurs
formulaires ne sont pas tous réécrits en React. Les sources historiques sont
dans `frontend/legacy/`, sans iframe et sans duplication dans `backend/static/`.
Le remplacement de cette couche se fait par écran, en vérifiant notamment les
opérations financières, les contrôles de paie et les impressions.

Consulter `frontend/README.md` pour les commandes, la configuration du proxy,
les limites de cette première étape et la préparation de l'hébergement.
Le frontend ne contient aucun identifiant de base de données ni clé de signature.

## Écrans métier convertis en React — lot du 20 septembre 2026

- **Suivi des tâches** : périmètres personnel / supervision DFI, actualisation
  toutes les 30 secondes, filtres, répartition par utilisateur, détails, ouverture
  du module concerné, rapports PDF / Excel / impression et réglage des délais.
  L'enregistrement conserve la version de contrôle de concurrence fournie par
  Django. Les échéances et responsabilités restent calculées par le backend.
- **Journal de traçabilité** : filtres appliqués distincts des filtres en cours de
  saisie, pagination avec borne stable, protection du journal, différences avant /
  après, traces liées, exports PDF / Excel. Le super administrateur conserve
  exclusivement le périmètre des utilisateurs et habilitations.
- **État du stock** : valorisation, quantités, 40 derniers mouvements, recherches,
  tri numérique, pagination et exports de la sélection en CSV / Excel / PDF.
  Une erreur réseau est signalée ; elle n'est plus présentée comme un stock nul.
- **Taux de change** : saisie contrôlée, confirmation de l'enregistrement, blocage
  des doubles envois et protection de la saisie pendant la navigation. Le taux
  reste global au groupe ; l'enregistrement pour une date existante le remplace,
  conformément au circuit antérieur.
- **Catalogue des articles** : recherche, tri, pagination, exports et formulaires
  complets de création / modification. Les contrôles de code, code-barres et
  désignation sont conservés côté Django. La confirmation d'un homonyme est
  remise à zéro si l'identité saisie change. La TVA par article et les natures
  marchandise, matière première et consommable sont conservées. Code et unité
  sont affichés en lecture seule en modification, car l'API existante ne les modifie pas.
- **Chambres & ménage** : cartes, recherche, filtre d'état, création / modification,
  maintenance, nettoyage et remise en service. Les chambres inactives peuvent être
  retrouvées par un filtre. L'occupation reste pilotée par les séjours et contrôlée
  par Django. Les rapports de la sélection peuvent être imprimés ou exportés.

Aucune migration de base ni modification des règles métier dans ce lot. Les
opérations de vérification ont utilisé `.build/qa/next_interface.db`, une copie
isolée exclue des livraisons. Les autres écrans restent dans la couche de transition.

Vérifications : compilation TypeScript / Next.js, 18 tests frontend et 16 tests
JavaScript de compatibilité, essais navigateur DFI et super administrateur,
enregistrement des délais et d'un taux sur copie, ouverture d'un module depuis
une tâche, rapport de stock et affichage à 390 pixels. Les exports produits par
Django ont aussi été vérifiés à travers le relais Next.js.
Les essais sur copie couvrent aussi les refus de code dupliqué et de désignation
identique sans confirmation, la création d'un article exonéré, sa modification,
le refus du passage « sans stock » pour un article ayant encore du stock, puis la
création d'une chambre et son aller-retour en maintenance.
