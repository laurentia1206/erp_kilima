# Charte de l’interface React

La référence visuelle est l’interface historique conservée dans `legacy/` : couleurs vertes, police `Inter, "Segoe UI", Arial, sans-serif`, icônes **Tabler 2.44.0**, cartes, champs et menus. La police reste celle disponible localement, comme dans l’interface précédente. Aucun chargement de police distante n’est ajouté.

## Tailwind CSS

Tailwind CSS 4 est intégré au build Next.js par `postcss.config.mjs`. `app/tailwind.css` charge le thème et les utilitaires, **sans Preflight**, pour conserver les styles de base historiques. Les classes portent le préfixe `tw:` : `tw:flex`, `tw:flex-wrap`, `tw:gap-2`. Les tokens `primary`, `surface`, `muted`, `border` et `panel` reprennent les variables de la charte. Les styles historiques non placés dans une couche CSS gardent priorité sur les utilitaires ; ne pas déplacer ces styles dans une couche sans vérifier les écrans.

La détection des classes est limitée à `app/`, `components/` et `lib/`. Éviter les classes construites dynamiquement : écrire les variantes complètes dans le code React. Conserver Tabler (`<i className="ti ti-printer" aria-hidden="true" />`) pour toutes les icônes.

## Composants communs

- `ScreenPresentation` applique la charte aux 62 écrans métier. `ScreenTitle` reprend l’icône du menu actif.
- `ModuleGuide` restitue les repères du module ; ses raccourcis respectent les menus autorisés. L’espace système garde ses propres indications de sécurité.
- `DataTable` fournit les cartes de liste, recherche, tri, pagination, badges de statut, aperçus et exports. Les quantités gardent leur précision spécifique lorsqu’elle est fournie par le module.
- Les fenêtres utilisent une largeur de formulaire de 700 px, étendue pour les tableaux et rapports, dans la limite de l’écran.
- `app/native-workspace.css` adapte ces composants à la charte sans réactiver les anciens scripts qui manipulaient le DOM.

## Présentations métier

Les pièces à comptabiliser reprennent les groupes par provenance, cartes dépliables et corrections des comptes dans les lignes. Les brouillons survivent au filtrage, bloquent les changements de contexte et peuvent être abandonnés explicitement. Les étapes de confirmation, éclatement, ventilation analytique et contrôle du serveur sont conservées. L’impression reprend les données enregistrées.

Les autres écrans continuent d’utiliser leurs cartes, listes, onglets, planning, indicateurs et formulaires React. Le bandeau historique des dossiers RH est repris. Cette adaptation commune ne constitue pas une certification pixel par pixel de toutes les variantes d’affichage : les contrôles visuels se font sur les vues et données disponibles.

## Vérification

Exécuter `npm run typecheck`, `npm test` et `npm run build`. Le test Tailwind compile réellement la feuille de style et vérifie le préfixe et l’absence de remise à zéro des composants historiques. Les vérifications interactives s’effectuent sur une copie isolée des données, jamais sur les dossiers de test des utilisateurs.
