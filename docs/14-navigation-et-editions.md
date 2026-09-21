# Navigation et éditions — 15 septembre 2026

## Navigation

Un seul module peut être déployé dans le menu latéral. Le changement de page ouvre son module et ferme les autres. La recherche filtre les entrées sans ouvrir plusieurs modules. Les raccourcis communs (carburant, documents de flotte) conservent le module depuis lequel ils ont été choisis.

Ordre : Pilotage ; Réquisitions & validations ; Trésorerie ; Comptabilité ; Achats ; Ventes ; Point de vente ; Stocks & inventaires ; Ressources humaines ; Hôtel & restauration ; Transport ; Location d’engins ; Parc & maintenance ; Gestion du groupe ; Administration & réglages.

La Trésorerie rassemble les ordres, avances à justifier et caisses. Il s’agit d’un regroupement de navigation, sans changement des circuits ni des droits d’accès. Les intitulés des sous-menus précisent mieux leur contenu, notamment les paiements RH (avances/prêts ou paie mensuelle).

## Documents

Une édition commune est raccordée aux documents A4 commerciaux (factures, devis, commandes, bons de livraison et réception), pièces de caisse, fiches de course, notes de séjour, états financiers, rapports et documents RH.

L’aperçu propose l’impression, le téléchargement d’un PDF paginé et un véritable classeur `.xlsx`. En-têtes de société, ville et identifiants disponibles, titres, tableaux, totaux, mentions et signatures sont présentés de façon homogène. Les identifiants absents ne sont pas inventés. Aucun logo fictif ni signature automatique n’est ajouté. Les données et les statuts proviennent du document existant.

Les PDF sont produits dans Django, sans transmettre les données à un service extérieur. Les tables répètent leurs en-têtes sur les pages suivantes, les paragraphes se répartissent dans les cellules, les rapports larges passent en paysage. Les pages comportent les références de la société et leur numéro. Les tickets de point de vente conservent une présentation compacte adaptée à une imprimante de 80 mm.

Les boutons Excel existants produisent désormais des `.xlsx`. Les listes disposant d’une barre de recherche proposent également Excel et PDF pour les lignes filtrées, sur toutes les pages de la liste chargée, sans les boutons d’action. Le CSV reste proposé séparément pour l’échange de données.

Les classeurs comportent une identité de société, un titre, une date d’édition, des en-têtes mis en forme, des filtres, des volets figés, des largeurs adaptées et une mise en page d’impression. Les montants reconnus restent numériques ; les références conservent leurs zéros initiaux. Les textes pouvant être interprétés comme des formules sont stockés comme textes. Aucun total comptable supplémentaire n’est inventé, notamment pour les rapports contenant plusieurs devises.

## Vérifications et périmètre

90 tests Django et 13 tests JavaScript passent : authentification et société des exports, texte/formules Excel, nombres et références, pagination d’un rapport de 160 lignes, navigation exclusive, recherche et conservation des routes/droits. Vérification visuelle de PDF fictifs : facture, bulletin et rapport sur plusieurs pages. Aperçu d’un compte de résultat existant et téléchargements PDF/XLSX vérifiés dans le navigateur de l’application. L’ouverture dans Microsoft Excel natif et les imprimantes physiques ne sont pas automatisées dans cette vérification.

Aucun paiement, validation métier ou migration de données n’est effectué par cette livraison. L’amélioration de la présentation d’un bulletin ou d’une déclaration ne lève pas les contrôles métier/réglementaires nécessaires. Les documents existants qui sont des projets restent des projets.

Dépendances du moteur d’édition ajoutées aux exigences de Django : ReportLab et openpyxl. Les exemples fictifs de contrôle sont conservés sous `.build/editions-qa`, séparément des données de gestion.
