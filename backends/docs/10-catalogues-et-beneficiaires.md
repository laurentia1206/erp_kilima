# Catalogues et bénéficiaires — 14 septembre 2026

## Décisions conservées

- Le DFI choisit un bénéficiaire provisoire. Au décaissement, le caissier peut
  confirmer ce choix ou choisir une autre personne. Aucun verrouillage du
  bénéficiaire ni nouvelle étape d’approbation n’a été ajouté.
- Les clients et fournisseurs propres à une société coexistent avec les fiches
  partagées existantes. Aucune fiche n’a été déplacée, fusionnée ou rendue
  partagée automatiquement.
- Les articles, marchandises et matières premières restent propres à leur
  société. Un article d’une autre société ne peut pas être introduit dans une
  facture par son identifiant, même lorsqu’il n’est pas géré en stock.

## Sélection et création dans les formulaires

Un bouton « Rechercher / créer… » permet de rechercher une fiche ou d’ouvrir sa
création sans fermer le document en cours. La fiche créée est sélectionnée ;
les notes, lignes et autres informations saisies sont conservées.

Couverture : client du Walk-in et des réservations, clients des devis, courses,
contrats de transport et facturation d’engins, fournisseurs des commandes et de
la maintenance, tiers des factures, clients du point de vente, articles des
devis, factures, commandes et justifications, ingrédients et plats des fiches
techniques, articles des transferts de stock, bénéficiaires des ordres et
décaissements. Les droits existants continuent à limiter les créations ; une
nouvelle fiche bénéficiaire n’est pas un nouveau compte de connexion.

Les nouvelles fiches créées directement appartiennent à la société active,
nommée dans le formulaire. Les sélections affichent le code et la mention
« Société active » ou « Fiche partagée ». La gestion d’une politique de partage
par une sélection de plusieurs sociétés n’a pas été introduite : le modèle
existant distingue une société précise et une fiche commune.

Les créations vérifient les codes et noms dans la société et les fiches
partagées. Un code ou code-barres déjà utilisé est bloqué. Un nom identique,
après suppression des différences de casse, accents et espaces superflus,
déclenche une alerte ; un homonyme réellement distinct nécessite une
confirmation explicite et un autre code. Les modifications de noms sont
également contrôlées. La réception réutilise le client choisi ; l’ancien mode
de saisie libre reste disponible et signale les noms correspondant à plusieurs
fiches. Il n’y a aucune fusion automatique d’identités historiques.

## Un répertoire commun pour les bénéficiaires

Les deux étapes consultent désormais le même répertoire de la société : agents
actifs affectés à cette société, fiches financières actives de cette société,
et fiches partagées. Un agent disposant déjà d’une fiche financière liée est
présenté une seule fois. Sinon, cette liaison est créée lors de son utilisation
dans le document, dans la même transaction. Consulter la liste ne crée rien.

Le formulaire de paiement affiche explicitement le titulaire de l’avance avant
confirmation. L’avance, le bon de réception, le mouvement de caisse et la ligne
comptable utilisent ce bénéficiaire effectif. Chaque paiement partiel conserve
son propre bénéficiaire ; un paiement suivant à une autre personne ne modifie
pas la première avance. Le choix provisoire des nouveaux ordres et les
confirmations au paiement sont enregistrés dans le journal d’audit.

Une incohérence réelle a été observée dans la copie de recette : l’ordre
`ODP-PLA-2026-000006` (160 USD, PLANET) désigne « MARCHE CENTRE VILLE », une fiche
active rattachée à Guest House Relax. Le formulaire signale désormais que ce
bénéficiaire n’est pas disponible pour PLANET et exige un choix valide. Il ne
sélectionne plus implicitement la première personne de la liste. Cet ordre et
la fiche historique n’ont pas été corrigés automatiquement.

## Vérifications

- 45 tests Django réussis : circuit d’approbation et justification, remplacement
  du bénéficiaire, deux paiements partiels à des personnes différentes,
  répertoire identique pour DFI et caissier, agents existants, création et
  doublons, refus des fiches privées d’une autre société, clients partagés et
  création depuis la réception.
- 10 tests JavaScript réussis : échanges réseau, double clic, changement de
  société, session et fonctions de recherche/export.
- Dans une copie distincte de la recette utilisateur : création d’un client
  depuis Walk-in avec conservation de la note ; tentative de code en double
  bloquée et sélection de l’existant ; création d’un article dans un devis,
  prix repris, note conservée et disponibilité sur la ligne suivante.
- Formulaire de décaissement inspecté visuellement : bénéficiaire indisponible
  laissé vide, confirmation désactivée, sélection d’un agent existant,
  récapitulatif de l’avance actualisé et recherche sans création en double.
  Aucun paiement n’a été exécuté dans la copie utilisateur pour ces tests.

Les tests financiers utilisent une base temporaire. Les créations fictives
dans le navigateur sont isolées dans `.build/qa/catalogue_ui.db`. La base de
recette utilisateur `.build/qa/kilima_qa.db` est conservée, ainsi que la base
originale `backend/kilima_dev.db`.

## Points restant soumis à une décision métier

Le fonctionnement existant d’une fiche client partagée cumule ses points de
fidélité et contrôle son plafond de crédit sur les opérations des sociétés qui
l’utilisent. Cette portée est maintenant indiquée dans le point de vente.
Séparer ces paramètres par société serait un changement structurel à faire
valider, pas une conséquence automatique du partage de l’identité.

La détection des doublons concerne les chemins de création et modification
traités dans Django ; elle ne constitue pas une contrainte d’unicité nouvelle
sur toutes les écritures directes en base ou tous les imports externes. Les
éventuels doublons historiques nécessitent une revue avant toute fusion.
La recette mobile complète et les réserves de production du document 08
restent à traiter.
