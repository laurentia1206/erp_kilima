# Revue des modules et comparaison fonctionnelle

Périmètre : moteur Django et interface existante. Demande du 14 septembre 2026.

## Règle de travail

Les améliorations de présentation, recherche et lisibilité ne changent pas les
circuits existants. Toute proposition touchant aux règles métier, aux droits,
aux étapes de validation, aux données ou aux liens entre modules nécessite
l'accord préalable de Laurent. Les propositions ci-dessous ne valent pas
autorisation de les réaliser.

## Décision structurelle S1 — bénéficiaire d'un décaissement

**Constat :** dans `executer()` et dans sa fenêtre de saisie, le bénéficiaire peut
être remplacé au moment de décaisser un ordre déjà validé. Cette souplesse existe
aujourd'hui et n'est pas traitée comme une erreur à corriger automatiquement.

**Proposition à approuver :** afficher le bénéficiaire validé en lecture seule et
refuser côté serveur toute demande de paiement désignant un autre bénéficiaire.
Un paiement à une autre personne nécessiterait un nouvel ordre dans le circuit
habituel. Les ordres et paiements historiques resteraient inchangés.

**Conséquence pratique :** le caissier ne pourrait plus régler à une personne
substituée lors du dernier écran. Les possibilités actuelles de paiement partiel,
de choix de caisse/banque et de justification resteraient identiques.

**Décision de Laurent : « Conserver le changement possible ».** La proposition
de verrouillage n'est pas retenue. Le champ reste modifiable et le serveur
continue à accepter le changement de bénéficiaire. Aucun nouveau contrôle ni
nouvel ordre obligatoire n'est ajouté.

## Sources consultées

- [Odoo : rechercher, filtrer et grouper](https://www.odoo.com/documentation/19.0/fr/applications/essentials/search.html).
- [Frappe / ERPNext : fonctions des listes](https://docs.frappe.io/framework/user/en/api/list).
- [ERPNext : rapprochement des paiements](https://docs.frappe.io/erpnext/payment-reconciliation).
- [Odoo : comptabilité et facturation](https://www.odoo.com/documentation/19.0/applications/finance/accounting.html).
- [Cloudbeds : calendrier hôtelier](https://myfrontdesk.cloudbeds.com/hc/en-us/articles/235146587-Calendar-Everything-you-need-to-know).
- [Odoo : réapprovisionnement](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html).
- [ERPNext : maintenance des actifs](https://docs.frappe.io/erpnext/asset-maintenance).
- [Odoo : parcours du point de vente](https://www.odoo.com/documentation/19.0/applications/sales/point_of_sale/use.html).

Ces documentations servent de références de parcours et d'ergonomie. Leur
existence ne prouve ni la conformité de Kilima, ni l'adéquation de leurs règles
aux sociétés du groupe. Les circuits Kilima restent la référence métier.

## Améliorations livrées pendant cette revue

Les listes de consultation compatibles disposent désormais d'une recherche
multi-mots sans accents, d'un filtre sur le statut affiché, du tri, de pages de
25/50/100 lignes (ou toutes), d'un compteur et d'une remise à zéro. L'export CSV
porte sur les résultats trouvés, toutes pages confondues. Il exclut les colonnes
d'actions et protège les libellés commençant par une formule de tableur.

Le périmètre est explicitement indiqué : la recherche porte sur les données
déjà chargées et ne recalcule pas les indicateurs du module. Les filtres métier
existants continuent à déterminer ce que le serveur charge. Les nouveaux outils
remplacent l'ancien champ générique quand celui-ci existait, sans le dupliquer.

Chaque famille de modules possède un encadré repliable expliquant son rôle et
ses liens vers les écrans connexes accessibles au compte. Les formulaires ont
des libellés reliés à leurs champs. Les tableaux de consultation peuvent défiler
horizontalement dans leur cadre sans élargir toute la page.

### Résultat module par module

| Module / écrans inspectés | Constat et amélioration livrée | Référence ergonomique / limite |
|---|---|---|
| Accueil, tableau de bord | Accès aux circuits et priorités existants vérifiés ; repères ajoutés au tableau de bord. | Navigation entre documents, Odoo/Frappe. Les indicateurs gardent leur définition. |
| Réquisitions, nouvelle demande, approbation | Formulaire en trois sections avec explication du circuit et de la nature ; saisie des lignes accessible ; numéro ouvrant la fiche existante ; recherche, tri, statut et export des listes. | Listes et accès au document, Frappe. Aucun changement aux paliers. |
| Ordres, exécution, avances | Listes homogènes et repères demande → ordre → avance. Décision S1 conservée et testée. | Suivi du document et du paiement. Aucune nouvelle obligation de justification. |
| Caisse et transferts | Recherche des caisses par nom/état ; outils de consultation sur les listes de transferts compatibles. | Parcours caisse d'Odoo. Le journal à solde progressif reste chronologique. |
| Point de vente, tarifs | Panier, sélection des articles, client et modes de paiement inspectés ; repères vers tarifs et articles. | Odoo POS. Pas de mode hors ligne ni de nouvel état de commande ajouté. |
| Commandes fournisseurs | Recherche, statut, tri et export des commandes. | Listes Odoo/Frappe ; commande et réception restent distinctes. |
| Réceptions et factures d'achat | Outils de liste séparés sur les deux étapes et accès aux modules associés. | Traçabilité des documents. Aucune modification des écritures générées. |
| Devis et factures de vente | Recherche et consultation homogènes ; les boutons de livraison, règlement et document gardent leurs gestionnaires. | Odoo ventes et facturation. Les statuts métier et les plafonds ne changent pas. |
| Rapports commerciaux | Repères de lecture et export CSV commun protégé. | Odoo reporting. Les totaux ne sont pas triés ni paginés comme des documents. |
| Stock, dépôts et articles | Outils sur état du stock, journal des mouvements, articles et transferts compatibles ; recherche dans les fiches de dépôts. | Listes d'inventaire. Le CUMP, les réservations et les seuils restent inchangés. |
| Courses, flotte, contrats et configuration transport | Outils de liste sur courses et interventions ; recherche des véhicules ; liens vers contrats et carburant. | Frappe listes et ERPNext maintenance. Départ, arrivée, retour et facturation gardent leur circuit. |
| Parc d'engins, heures, RPE et configuration | Recherche dans le parc et les interventions ; repères parc → heures → RPE. | Consultation des actifs, ERPNext. Forfaits et arrondis des heures conservés. |
| Maintenance, interventions, documents et configuration | Recherche du véhicule et des listes compatibles, filtres par état ; repères d'échéance. | ERPNext maintenance. Plans, périodicités et seuils conservés. |
| Carburant | Recherche, tri et export des tableaux de consommation et du journal des pleins ; rappel des unités. | Listes de suivi. Aucun changement au calcul d'écart ou au seuil d'alerte. |
| Hôtel : réception, chambres, configuration | Planning à date choisie sur 7/14/31 jours, navigation précédente/suivante et retour à aujourd'hui ; ouverture du séjour au clavier ; recherche des chambres. | Calendrier Cloudbeds. Dates, réservation, arrivée et facturation inchangées. |
| Hôtel : indicateurs de réception | « Arrivées attendues » et « Départs à effectuer » précisent l'inclusion des retards. Un message explique les séjours en cours dont le départ prévu est dépassé. | Clarification des données existantes, sans prolongation automatique des séjours. |
| Cuisine | Recherche, tri et export des recettes et consommations compatibles ; liens vers dépôts et POS. | Odoo restaurant, lecture des coûts. Aucune nouvelle étape de production. |
| Intersociétés | Repères vers les documents commerciaux et de transport ; positions et traçabilité inspectées. | Rapprochement ERPNext. Aucune compensation ou écriture de régularisation automatique. |
| Comptabilité : cockpit, pièces, OD, grand livre, lettrage, rapprochement, analytique, balance, états, plan comptable | Repères de société/période/document ; libellés de champs accessibles ; exports CSV communs protégés. Les tableaux éditables, regroupés et à totaux conservent leur présentation métier. | Odoo comptabilité et ERPNext rapprochement. Aucun changement de méthode comptable. |
| Taux, paramétrage et administration | Repères sur la portée des réglages ; recherche/statut/tri/export des listes administratives compatibles. | Listes Frappe. Affectations, droits et taux inchangés. |

Les outils s'appliquent à 22 vues de listes et 6 vues de fiches lorsqu'elles
contiennent des données compatibles. Les listes vides, tables éditables, tables
avec cellules fusionnées ou totaux ne reçoivent pas automatiquement ces outils.

## Évolutions structurelles à examiner avec Laurent

Ces pistes issues de la comparaison ne sont **pas implémentées** et ne sont pas
des décisions acquises. Une proposition précise sera soumise avant toute action.

- **Réapprovisionnement automatique** : Odoo peut préparer des achats selon des
  seuils. Dans Kilima, déterminer d'abord qui fixe les seuils par dépôt, qui
  approuve la commande et comment les demandes déjà ouvertes sont prises en compte.
- **Contrôles supplémentaires à l'achat** : définir avec les équipes la conduite
  à tenir en cas d'écart entre commande, réception et facture avant d'introduire
  un nouveau blocage ou une nouvelle validation.
- **Maintenance automatique** : ERPNext relie planning et journaux de maintenance.
  Décider si une échéance Kilima doit créer une intervention ou seulement alerter,
  et si elle peut immobiliser un véhicule ou empêcher une course.
- **POS et cuisine** : une file de préparation, une vente hors connexion ou une
  réservation de stock modifient le moment où l'opération agit sur les autres
  modules. Il faut définir ces règles avant développement.
- **Hôtel** : préciser le traitement d'un client encore présent après son départ
  prévu avant toute prolongation, facturation ou occupation automatique.
- **Rapprochement intersociétés** : examiner les pièces sources avant d'automatiser
  un lettrage ou une régularisation. La copie inspectée affiche notamment un écart
  de 42,62 USD entre KAKO LOGISTICS et KAKO SARL ; son origine n'est pas établie par
  cette revue de l'interface et aucune correction financière n'a été passée.

## Vérifications et limites

- Parcours de **52 écrans distincts** depuis la navigation avec le compte DFI sur
  la copie de recette, notamment avec les données de Guest House Relax. Aucun
  écran d'erreur de chargement ni erreur JavaScript observé pendant ce passage.
  Un premier passage avait également examiné 25 écrans avec PLANET.
- Réquisition : recherche « generatrice reparation » sans accents, ouverture de
  la bonne fiche, remise à zéro et tri des montants 125 / 800 / 3 000 / 5 000.
- Hôtel : période historique du 1er septembre, passage à 7 jours (8 colonnes avec
  la chambre), ouverture de la fiche depuis la barre du séjour ; recherche d'une
  chambre « suite » donnant 1 résultat sur 3.
- Liste fictive de **61 documents** : pages de 25, passage à la deuxième page,
  filtre réduisant la liste à 31 résultats, dernière page de 6 lignes, bouton du
  document 61 encore fonctionnel, résultat vide, remise à zéro et affichage des
  61 lignes. Cette vérification ne crée aucun document métier.
- **29 tests Django réussis**, dont un test dédié au changement de bénéficiaire
  après validation de l'ordre. **10 tests JavaScript réussis** couvrant le réseau,
  les doublons de requêtes, la recherche, les montants et les exports.
- Vérification syntaxique des scripts et absence d'erreurs de diff. Empreinte de
  la base de travail originale identique à celle relevée avant les contrôles.

La pagination est locale : elle facilite la lecture mais ne réduit pas encore
le volume téléchargé. Les contrôles de consultation ne certifient pas tous les
circuits métier, tous les rôles ni les accès simultanés en production. L'affichage
des nouvelles listes a été inspecté sur ordinateur ; la tentative de forcer une
largeur de 390 px sur l'onglet de test n'a pas changé sa largeur réelle et ne
constitue donc pas une validation mobile complète. Une recette sur téléphone
reste à faire. Les réserves de production du document 08 restent applicables.
