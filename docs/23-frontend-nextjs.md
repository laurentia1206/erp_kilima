# Passage du frontend à Next.js

Le frontend actif est désormais dans `frontend/` : Next.js, React et TypeScript.
Le backend Django reste dans `backend/`. Les API et les circuits métier sont
conservés. Le point d'entrée de tests est http://127.0.0.1:3000 avec
`Demarrer-Next.bat` ou `Demarrer-tests.bat`.

La connexion, le menu latéral, le choix de société et l'accueil sont rendus par
React. Un seul module reste déplié à la fois ; les accès sont filtrés selon le
compte, et les changements de société sont protégés lorsqu'une opération est
en cours. Les règles d'autorisation définitives restent sur le serveur Django.

Les **62 écrans métier** sont maintenant rendus en React, avec formulaires,
dialogues et rapports natifs. La couche `frontend/legacy/` subsiste pour les
services partagés (authentification, menus, notifications et navigation) ; le
rendu historique des 62 vues est neutralisé. Les sections ci-dessous décrivent
les lots successifs et conservent leur contexte historique.

Consulter `frontend/README.md` pour les commandes, la configuration du proxy,
les limites restantes et la préparation de l’hébergement.
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


## Complément — dépôts et inventaires

Deux écrans supplémentaires sont désormais entièrement en React :

- **Dépôts & transferts** : stocks par dépôt, création et modification des dépôts
  dédiés, affichage des inactifs, transferts multilignes et bons PDF / Excel.
  Les quantités disponibles sont visibles ; les lignes incomplètes, doublons et
  quantités insuffisantes sont signalés. La création d’article depuis le transfert
  réutilise le formulaire du catalogue et ses contrôles de doublons. La sélection
  d’une fiche existante la reprend directement dans la ligne.
- **Inventaires & écarts** : filtre mensuel et par dépôt, compteurs des manquants et
  excédents validés, saisie physique (vide différent de zéro), ajout d’articles sans
  stock théorique, détail et rapports portant explicitement le statut. Validation
  réservée au comptable / DFI, avec confirmation de l’impact ; annulation par le
  préparateur ou un validateur. Les contrôles de concurrence restent ceux de Django.

Les quantités conservent trois décimales et les coûts unitaires quatre. Les
transferts restent immédiats, sans écriture comptable ; le comptage reste un
brouillon jusqu’à validation. Aucun changement du schéma ni du circuit métier.

Vérifications de ce complément : compilation Next.js / TypeScript, 22 tests
frontend, 16 tests JavaScript de compatibilité et 11 tests Django du circuit des
inventaires / clôtures (base en mémoire). Parcours navigateur sur copie isolée :
création de dépôt, refus de transfert excessif, transfert de deux unités, comptage
avec quantité zéro, stock inchangé avant validation, ajustement et pièce comptable
après confirmation, annulation d’un second comptage, reprise d’un article existant,
PDF et Excel. Affichage contrôlé à 390 pixels. Aucun essai d’écriture dans la base
habituelle. L’empreinte de la base d’origine reste inchangée.

## Complément — réception hôtelière et cuisine

Deux nouveaux écrans métier sont en React, soit dix au total :

- **Réception & séjours** : planning par chambre, réservations, arrivées directes,
  sélection ou création d’un client avec contrôle des doublons et identification
  des fiches partagées, arrivée, modification du séjour, prestations, départ,
  facturation, règlement et note imprimable. Les factures du point de vente sont
  distinguées des prestations du séjour et ne sont pas facturées une seconde fois.
  Les montants HT, TVA, TTC et les soldes dus sont identifiés. En CDF, le taux du
  jour et les soldes sont relus avant paiement ; un paiement partiellement exécuté
  ou incertain oblige à relire le dossier avant toute nouvelle tentative.
- **Cuisine & coûts des plats** : création et modification des fiches techniques,
  portions et ingrédients, création d’article depuis la recette, coût moyen par
  portion, réglages du dépôt et du seuil d’alerte, consommations journalières avec
  confirmation, bons et rapports PDF / Excel. Les écarts d’inventaire validés sont
  séparés des consommations théoriques. La désactivation conserve les historiques.

Les règles Django sont conservées : départ mettant la chambre à préparer,
autorisations de règlement, une consommation par jour et signalement des stocks
négatifs. Aucun changement de schéma ni nouveau circuit de validation.

Vérifications : compilation Next.js / TypeScript réussie, 29 tests frontend,
16 tests JavaScript de compatibilité, 11 tests Django de catalogue, 11 tests
d’inventaires / clôtures et deux nouveaux tests cuisine en mémoire. Ces derniers
couvrent les quantités par portion, les coûts, l’impact stock / comptabilité,
le refus d’une seconde génération et d’une journée sans ventes.

Les essais navigateur utilisent exclusivement une copie isolée : création d’un
client et réservation, arrivée, prestations, départ, règlement CDF, création et
modification d’une recette, changement du dépôt cuisine, refus de consommation
sans ventes, aperçu et téléchargements. Les fichiers PDF et Excel ont également
été contrôlés à travers le relais Next.js. La base habituelle n’a pas reçu les
données de ces essais ; l’empreinte de la base d’origine reste inchangée.

## Complément — balance, grand livre et saisie comptable

Trois écrans supplémentaires sont migrés, portant le total à treize :

- **Balance générale** : exercice, classe, statut, indicateurs, recherche et tri,
  édition complète avec totaux ou édition de la sélection. Le solde N−1 reste
  séparé des mouvements N selon le calcul existant. Un filtre de classe porte
  une mention spécifique pour ne pas assimiler son écart à un déséquilibre global.
- **Grand livre** : filtre par début de compte et statut, synthèse des comptes,
  mouvements détaillés, recherche et exports. Les soldes progressifs du serveur
  sont conservés lors du tri et de la recherche, avec une mention dans le document.
  Le périmètre est explicitement « tout l’historique », comme l’API existante.
- **Saisie des écritures** : journal, date, référence, lignes débit / crédit,
  contrôle d’équilibre au centime, choix des tiers par identifiant et création
  de client / fournisseur sans quitter la saisie. La sélection distingue les
  fiches partagées. Aucune ligne incomplète n’est supprimée silencieusement.
  Une relecture précède l’enregistrement et la pièce peut être imprimée ou exportée.

La saisie manuelle reste directement validée par le comptable / DFI, comme avant
la migration ; ce comportement est annoncé dans le formulaire et la confirmation.
Les circuits des autres opérations ne changent pas. Une réponse réseau incertaine
interdit de soumettre à nouveau depuis la même fenêtre et demande de contrôler
le grand livre. La protection serveur refuse désormais un tiers inactif ou propre
à une autre société ; elle accepte les fiches partagées. Les montants non finis et
les dates invalides renvoient une erreur de saisie. Aucune migration de schéma.

Vérifications : 33 tests frontend, 30 tests Django (fondations et cinq nouveaux
contrats comptables) et compilation Next.js / TypeScript réussie. Sur la copie
isolée : refus d’un écart de 0,01 USD, création d’un fournisseur depuis la ligne,
confirmation d’une écriture de 12,34 USD, présence unique dans le grand livre,
filtres de statut / classe / compte et exports PDF / Excel. Le grand livre a été
contrôlé à 390 pixels de largeur. Les montants des aperçus sont formatés en français.
La base habituelle ne contient pas les données de ces essais.

Les autres écrans, notamment la revue des pièces, le plan comptable, le lettrage,
les achats / ventes, la trésorerie et les RH, restent intégrés via la transition
historique tant que leur conversion n’a pas été vérifiée.


## Complément — sept écrans comptables supplémentaires (21 septembre 2026)

Le périmètre React compte maintenant **20 écrans métier**, hors accueil :

- Plan comptable et journaux : comptes, filtres de classe et état, créations,
  modifications, paramètres automatiques et règles de revue séparées.
- Lettrage : sélection des lignes par identifiant, contrôle au centime,
  confirmation et délettrage du groupe avec avertissement sur les lignes masquées.
- Rapprochement bancaire : pointage, relevé avec zéro ou découvert explicites,
  écart, historique, rapport et annulation selon le fonctionnement existant.
- Synthèse financière : indicateurs actualisés chaque minute lorsque la page
  est visible, périmètre historique et inclusion des pièces en attente explicites.
- États financiers : compte de résultat, bilan N / N−1, flux de trésorerie,
  filtre de statut et éditions PDF / Excel.
- Analytique : axes et sections, ventilation partielle, recherche, rapports,
  confirmation de l’effacement et relecture avant remplacement d’une répartition.
- TVA mensuelle : mois, montants validés et en attente distincts, factures,
  ventilation par taux, dossier révisé et état enregistré séparé de l’état courant.

Les fenêtres verrouillent la navigation pendant la saisie. Les requêtes de
modification ne sont pas répétées automatiquement. La relecture côté interface
réduit les remplacements de données périmées ; elle ne constitue pas un verrou
transactionnel entre deux appels API. La TVA conserve son contrôle serveur de
révision. Aucun dépôt fiscal ni paiement n’est transmis par ces écrans.

Corrections ciblées Django : détail des immobilisations N−1 dans le bilan
(y compris postes sortis en N), contrôle société / axe en analytique, refus
explicite des sections dupliquées et montants analytiques non finis. Aucune
migration de schéma ni modification des circuits de validation. Le rapport
analytique conserve le calcul historique en valeurs de lignes sans compensation
débit/crédit : cette limite figure à l’écran et dans les rapports.

Les dates UTC sans suffixe émises par Django sont maintenant affichées dans le
fuseau de Lubumbashi ; les dates civiles et offsets explicites sont conservés.

Recette sur la copie isolée `next_interface.db` uniquement : création / modification
d’un compte, journal, lettrage équilibré de 12,34 USD, rapprochement sans écart,
création d’axe / section, répartition de 2,34 sur 12,34 USD et contrôle du reste,
sauvegarde d’un dossier TVA fictif, maintien du zéro distinct d’un montant absent,
aperçus et téléchargements PDF / Excel. Formulaire TVA contrôlé à 390 pixels,
sans débordement horizontal. Les erreurs provoquées par le remplacement à chaud
des anciens écrans ont disparu après chargement complet des assets synchronisés.

Tests : 46 frontend et 26 Django ciblés (clôtures, comptabilité, analytique et
comparatif financier), avec compilation complète Next.js / TypeScript.
Les autres vues continuent de fonctionner via la transition historique ; la
revue des pièces, le commerce, la trésorerie et les RH restent à convertir.


## Complément — revue comptable et rapports commerciaux (22 écrans)

La revue des pièces en attente passe en React : recherche par compte / tiers /
référence, filtres de provenance, montant et dates, dialogue de contrôle,
reclassement, éclatement, préparation de l’analytique, justificatifs et impression.
La validation conserve les rôles comptable / DFI. Une confirmation suit le contrôle
des saisies ; une part incomplète n’est plus ignorée. Le bouton d’impression de
la pièce actuelle montre les données enregistrées, pas les corrections en cours.

Django conserve le tiers initial sur les parts d’un éclatement lorsque le client
ne demande pas de changement. Il vérifie les montants positifs au centime, les
tiers fournis et l’équilibre exact de chaque éclatement. Une empreinte de la pièce
et un verrou transactionnel refusent une validation périmée ou répétée. Aucune
migration de schéma. Une ventilation analytique existante ne peut pas rester sur
une première part devenue trop petite ni être conservée sur un compte hors 6/7 :
elle doit être ajustée dans l’analytique avant cette correction comptable.

Le traitement analytique préparé reste distinct, après validation comptable, comme
le circuit précédent. En cas d’échec, le message confirme explicitement que la
pièce est validée et que l’analytique reste à terminer. Pas de répétition automatique.
Les pièces jointes restent enregistrées indépendamment de la validation ; leur
dialogue React peut être ouvert sans perdre les corrections. Le transport commun
accepte maintenant FormData sans transformer le fichier en JSON.

Le rapport commercial dispose de tableaux recherchables, triables, paginés,
d’un détail des articles et d’éditions PDF / Excel / CSV. Les calculs backend sont
conservés. Le périmètre est annoncé : historique des entrées en stock par référence
(pouvant inclure inventaires et transferts), synthèse des factures tous statuts,
avoirs déduits, palmarès de huit quantités sorties sans compensation des retours.
Ce rapport ne remplace pas les états comptables ou la déclaration TVA.

Recette sur copie isolée : refus d’une part vide, éclatement de 12,34 USD en 2,34
et 10 USD avec tiers conservé, ajout et récupération identique d’un justificatif
fictif, reclassement et ventilation de 12,34 USD, disparition de la pièce validée
et mise à jour du compteur. Les fichiers de cette recette sont dans un stockage
isolé. Tests : 50 frontend et 14 Django ciblés (revue, saisie et analytique).

Contrôles visuels complémentaires : dialogue de revue à 390 pixels sans débordement
horizontal, filtre d’origine et détail des articles du rapport commercial,
synthèse et aperçu d’édition. Aucun avertissement ni erreur de console sur les
parcours de cette série. Compilation Next.js / TypeScript réussie avant livraison.


## Palier de 30 écrans — exploitation, configuration et documents

Huit vues supplémentaires : `dashboard`, `config-hotel`, `config-engins`,
`config-transport`, `config-maintenance`, `contrats-transport`, `flotte-documents`
et `engins-rpe`. L’accueil et les sous-dialogues ne sont pas comptés comme écrans.
Les quatre guides de configuration partagent un composant, mais conservent leurs
propres menus, compteurs et actions métier. Leurs formulaires de création sont
React ; les liens vers les autres modules restent soumis aux menus accessibles.

Le tableau de suivi actualise ses indicateurs chaque minute quand la page est
visible. Les contrats disposent d’une grille tarifaire contrôlée, d’une sélection
ou création de client de la société, et d’un récapitulatif PDF/Excel. Les fiches
partagées sont clairement identifiées. Une ligne tarifaire incomplète n’est jamais
retirée silencieusement de la demande.

Les documents du parc sont recherchables, filtrables par état, renouvelables et
supprimables avec confirmation. Les fichiers utilisent le dialogue commun de
pièces jointes. Les listes de porteurs indisponibles sont signalées séparément,
sans masquer les documents accessibles au maintenancier. Le renouvellement garde
le même porteur. Les dates des champs partagés sont synchronisées dès la saisie.

Le relevé des engins reprend les calculs Django (jour/nuit, arrondis, forfait,
supplément et tarifs), avec exports et confirmation avant facturation mensuelle.
Les circuits, rôles et réglages métier existants sont conservés. Aucun schéma de
base n’est modifié. Les erreurs réseau après envoi portent un indicateur explicite
de résultat incertain pour empêcher une seconde soumission sans vérification.

Recette isolée : création d’un contrat avec tarif 12,50 USD/tonne, d’un engin et
d’une caisse ; création puis renouvellement d’un document au 30/09/2027 ; facture
mensuelle de recette de 380 USD HT / 440,80 USD TTC ; lecture des huit API et
exports PDF et XLSX avec signatures valides. Aucun fichier fictif ni transaction
de cette recette n’est ajouté à la base habituelle des tests.

Tests : 53 contrôles frontend ; 9 tests Django ciblés sur les contrats, documents,
permissions intersociétés et revue comptable. Vérification visuelle des huit vues,
apercu du tableau de suivi à 390 px, navigation et dialogues. Compilation complète
Next.js/TypeScript contrôlée avant mise à disposition.


## Palier de 40 écrans — parc, maintenance et trésorerie

Dix écrans supplémentaires sont possédés par React : `flotte`, `engins-parc`,
`engins-heures`, `maintenance-parc`, `maintenance-interventions`, `carburant`,
`tarifs-pos`, `transferts`, `caisse-exec`, `intersociete`.

- Parc : créations, modification des engins, disponibilité, interventions et exports.
- Maintenance : plans, périodicité, échéances, historique, planification, démarrage
  et clôture. Un zéro saisi reste distinct d’un coût non renseigné.
- Prestations : heures de nuit, arrêts, index et arrondis configurés, aperçu et
  calcul confirmé par Django ; filtres de période et rapports.
- Carburant : pleins, modification, suppression confirmée, suivi réel/théorique
  et exports. Le sélecteur `GET /carburant/vehicules` retourne seulement les ID,
  types et noms des véhicules actifs de la société, avec les droits carburant.
  Le dispatcher n’a pas besoin de droits supplémentaires sur la maintenance.
- Tarifs POS : listes, prix par article (vide = défaut, zéro conservé), points de
  vente, associations à une caisse et un dépôt. Les enregistrements successifs
  des prix signalent explicitement une réussite partielle.
- Trésorerie : émission et réception/rejet des transferts ; exécution des ordres
  selon le rôle, choix/création du bénéficiaire, paiements partiels, billetage,
  pièces imprimables. Aucun changement du circuit de validation.
- Intersociétés : positions et factures accessibles, règlement avec deux pièces
  en attente de validation, traçabilité et liaisons des tiers propres à la société.

Correction de document : le bon de sortie reprend désormais le montant et le
receveur du BonReception, plutôt que le montant total et le bénéficiaire courant
modifiables de l’ordre. Le paramètre facultatif `bon_numero` sélectionne une pièce
précise de cet ordre ; sans paramètre, le dernier bon est retourné. Aucun schéma
ni migration de données n’est nécessaire.

Recette dans la base isolée `next_interface.db` : cycle planifier/démarrer/terminer,
coût réel zéro ; prestation 22h–6h avec arrêt 23h45–0h15 = 7h30 ; plein 10,5 L à
1,25 USD = 13,12 USD et compteur zéro ; modification de consommation théorique ;
liste de prix dont un tarif zéro et point de vente sans caisse ; refus d’un
transfert vers sa source ; paiement bancaire fictif de 1 USD avec changement de
bénéficiaire, bon de 1 USD ; règlement intersociété fictif de 1 USD avec solde et
pièces en attente. Les essais ne modifient pas la base de test habituelle.

Les 55 tests frontend passent. Les tests Django ciblés couvrent les circuits de
décaissement, le bénéficiaire historique et les permissions/scopes des sélecteurs.
Les scénarios de recette ne constituent pas une homologation de tous les circuits
ERP ni de tous les rôles ; la recette métier par les utilisateurs reste nécessaire.


## Achèvement des 62 écrans — 21 septembre 2026

Les 22 dernières vues sont natives : `nouvelle-req`, `requisitions`, `approbation`,
`ordres`, `avances`, `caisse`, `courses`, `config`, `administration`, `systeme`,
`rh`, `rh-simulateur`, `rh-decomptes`, `rh-finances`, `rh-paiements`, `rh-mensuel`,
`achats`, `ventes`, `commandes`, `receptions`, `devis` et `pos`.

- Réquisitions, précisions, validations, émission d’ordre et confirmation du
  bénéficiaire effectif suivent les circuits Django. Les liens du tableau de
  suivi ouvrent les dossiers React ; leur cible est effacée en changeant de
  société ou de session.
- Les achats couvrent commandes, réceptions, frais accessoires et facturation.
  Les ventes couvrent devis, remises successives, livraison, facturation et
  règlement. La remise effective retournée par Django est décomposée à la
  réouverture d’un devis pour ne pas déduire la remise globale deux fois. Une
  remise globale historique de 100 % ne permet pas de retrouver la remise
  initiale de ligne : le formulaire le signale si l’utilisateur veut la réduire.
- Le point de vente conserve les tarifs, les prix à zéro, les paniers en attente,
  les paiements fractionnés USD/CDF, les tickets, retours et imputations hôtel.
- Les RH proposent les dossiers et documents des agents, contrats, pointages,
  organisations de travail, simulation, accords financiers, échéanciers,
  préparation mensuelle, validations et bulletins selon les API existantes.
- Les permissions restent contrôlées côté serveur. La super administration
  concerne uniquement comptes, rôles et restrictions des utilisateurs.

### Recette et limites

63 tests frontend et 185 tests Django passent ; le contrôle TypeScript et la
compilation de production Next.js sont valides.
Les essais avec écritures ont été réalisés dans `next_interface.db`, une base
isolée, sans alimenter la base habituelle des utilisateurs ni la base historique.
La recette navigateur a vérifié une réquisition, une commande avec réception et
facture, un pointage traversant minuit, la simulation d’une rémunération, sa
reprise en contrat et la préparation d’un bulletin. Le point de vente a produit
un ticket remisé avec deux règlements. Le devis conserve son total après édition, puis donne un bon de livraison et une
facture du même montant. La connexion super administrateur affiche uniquement
la gestion des utilisateurs, sans sélecteur de société ni opérations métier.

La migration d’interface ne complète pas les fonctions métier encore limitées :
le circuit complet d’autorisation et d’acquisition des congés, le net à payer et
le paiement du décompte final, ainsi que la récupération d’avances à justifier
sur salaire restent à finaliser dans le backend. Ces limites sont annoncées dans
les écrans concernés. Les déclarations conservent les assiettes réglementaires ;
aucun mécanisme de minoration arbitraire des rémunérations déclarées n’a été ajouté.
Le ticket natif utilise l’aperçu d’impression commun ; une mise en page thermique
80 mm dédiée reste distincte de cette migration.
