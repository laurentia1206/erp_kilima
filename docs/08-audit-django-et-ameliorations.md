# Kilima Holdings — diagnostic Django et première livraison

**Date : 14 septembre 2026. Périmètre : Django et l'interface qu'il sert.**

## Conclusion

Le projet contient déjà une base métier substantielle. Il faut consolider et
tester ses circuits avant d'ajouter davantage de fonctionnalités. Cette
intervention livre des corrections vérifiées et une nouvelle interface commune.
Elle ne signifie pas que l'ensemble de l'ERP est prêt pour une exploitation
généralisée en production.

La revue s'appuie sur le cahier des charges Markdown, les documents techniques
et de passation, les modèles et routes Django, les services transverses,
les fonctions sensibles étudiées et des essais. Il s'agit d'un diagnostic
initial ciblé, pas d'une revue exhaustive de chaque ligne ni d'une certification
comptable ou de sécurité.

## Compréhension de l'existant

Le cahier des charges prévoit sept entités métier et les sites de Likasi et
Kolwezi. La base consultée contient six sociétés actives : cette différence de
paramétrage doit être clarifiée avant la reprise définitive, sans créer ni
fusionner automatiquement des sociétés.

Le moteur actif comprend **82 modèles Django et 183 routes API**. Les montants
sont suivis en USD et CDF, avec un taux journalier. Les rôles et les affectations
par société pilotent l'accès et les circuits de validation.

| Domaine | Éléments déjà présents |
|---|---|
| Décaissement | G01 réquisition, validations, G02 ordre, G03 versement, G04 justification, avances et blocages |
| Trésorerie | Caisses, sessions, comptage et clôture, transferts, rapprochement |
| Comptabilité | Journaux, pièces, comptes, écritures automatiques, balance, grand livre, états, analytique |
| Achats / ventes | Commandes, réceptions partielles, factures, devis, livraisons, règlements, point de vente |
| Stocks | Articles, coût moyen, dépôts, transferts et inventaires |
| Intersociétés | Documents miroir, réceptions, positions, règlements et liens transport |
| Transport / engins | Flotte, courses, contrats, prestations, maintenance, carburant et documents |
| Hôtel / cuisine | Chambres, réservations, séjours, facturation, ménage, fiches recettes et consommations |

Les principaux liens sont déjà modélisés : décaissement ↔ caisse ↔ comptabilité ;
achats ↔ réceptions ↔ stock ↔ fournisseur ; ventes ↔ livraison ↔ facture ↔ client ;
commerce intersociétés ↔ transport ; hôtel / point de vente ↔ facturation et stock.

L'interface métier reste concentrée dans un fichier JavaScript de plus de
7 600 lignes. Cela rend les changements transversaux et leur vérification plus
difficiles. Le nouvel espace de travail est isolé dans `workspace.js` et
`workspace.css` afin de ne pas alourdir ce fichier davantage.

## Changements livrés

### Interface et expérience utilisateur

- Nouvelle page de connexion et identité visuelle commune, avec couleurs,
  contrastes et composants harmonisés.
- Accueil avec quatre indicateurs provenant de la société active : demandes
  soumises, ordres à valider, avances en cours et avances en retard.
- Accès directs aux étapes des circuits financiers, commerciaux et de stock.
- Catalogue des modules et accès récents propres au compte utilisateur.
- Recherche des modules, insensible aux accents, accessible par Ctrl K.
- Menu mobile, éléments de navigation accessibles au clavier, intitulés des
  boutons, fenêtres avec gestion du focus et fermeture par Échap.
- Mémorisation de la société choisie par utilisateur ; changement de société
  bloqué pendant une requête d'écriture ou tant qu'une fenêtre de saisie reste ouverte.
- États de chargement en erreur avec bouton de nouvel essai, messages réseau
  compréhensibles, signalement d'une perte de connexion.
- Refus d'une requête d'écriture identique déjà en cours dans le même onglet.
  Une écriture interrompue n'est jamais répétée automatiquement.

Ce dernier garde-fou ne remplace pas l'idempotence côté serveur entre plusieurs
postes. Le fonctionnement hors connexion avec synchronisation n'est pas livré.
Les écrans métier ne sont pas tous entièrement repensés pour téléphone.

### Fiabilité comptable et stocks

- Contrôle des lignes comptables : compte obligatoire, sens D/C valide,
  montants finis, non négatifs et compatibles avec la précision du modèle.
- Arrondi décimal de chaque ligne avant le contrôle d'équilibre ; les montants
  vérifiés correspondent exactement aux montants enregistrés.
- Écriture, lignes, numéro, exercice, journal et audit enregistrés dans une
  transaction unique ; une erreur annule l'ensemble de cette transaction.
- Refus de nouvelles écritures dans un exercice fermé, hors dates de l'exercice
  ou dans un journal désactivé.
- Opérations de stock atomiques, rechargement de l'article sous verrou,
  vérification de la société, du dépôt actif et du stock disponible.
- Transferts refusés vers le même dépôt ou une autre société ; mouvements
  source/cible conservés ensemble.

Les verrous de ligne doivent encore être éprouvés sur PostgreSQL avec plusieurs
opérateurs. SQLite ne fournit pas les mêmes garanties de verrouillage fin.

### Accès, sauvegarde et installation

- Une session expirée reçoit HTTP 401 ; HTTP 403 reste un refus d'autorisation.
  L'interface peut ainsi demander une reconnexion au bon moment.
- Durée des sessions configurable ; validation des types à la connexion.
- Accès aux pièces jointes contrôlé selon la société du document, pour la liste,
  le dépôt et le téléchargement. Types de document reconnus explicitement.
- Vérification des chemins des fichiers statiques et justificatifs pour bloquer
  les sorties du dossier autorisé.
- Configuration par environnement : DEBUG, hôtes autorisés, secret, HTTPS et
  en-têtes de sécurité. Refus des configurations de production manifestement
  dangereuses.
- Sauvegarde via l'API SQLite, contrôle d'intégrité avant publication du fichier,
  erreurs de sauvegarde journalisées. Le test vérifie une restauration incluant
  les données présentes dans le journal WAL.
- Migration 0013 pour les installations vierges : création de la table
  d'affectations à clé composite si absente. Aucun remplacement d'une table
  existante.

La copie de sauvegarde repose sur l'API prévue pour fonctionner pendant que
la base est utilisée. [Documentation Python sqlite3](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.Connection.backup).
La sauvegarde reste locale et déclenchée au démarrage ; une politique de
sauvegarde périodique hors machine reste nécessaire pour l'exploitation.

## Vérification effectuée

| Contrôle | Résultat |
|---|---|
| Tests Django | 28 tests réussis sur une base en mémoire |
| Tests réseau de l'interface | 5 tests réussis |
| Circuit réel de l'API Django | Réquisition → cosignatures → décaissement → justification → apurement du compte d'avance |
| Refus métier | Auto-validation, décaissement sans cosignatures et deuxième exécution refusés |
| Consultations sur copie | 45 routes × 6 sociétés = 270 réponses HTTP 200 |
| Temps de consultation observé | Maximum 970 ms lors de ce passage local, sans concurrence ; ce n'est pas un test de charge |
| Migrations | Base vierge et migration 0013 sur copie de l'existant ; aucune divergence modèle/migration détectée |
| Navigateur | Connexion, accueil, recherche, changement de société, accès hôtel, ouverture/fermeture de réservation |
| Affichage | Accueil contrôlé à 1280 px et 390 px ; aucun débordement horizontal du nouvel accueil mobile |
| Données existantes | Zéro écriture déséquilibrée détectée ; zéro article dont le total diverge des dépôts selon les contrôles ciblés |
| Préservation | Empreinte SHA-256 de la base de travail identique avant et après les validations |

Le test G01–G04 vérifie deux écritures équilibrées et les soldes attendus :
compte d'avance 421 apuré, charge 605 constatée et sortie de caisse 571.
Ces chiffres sont des données de test, pas une modification de vos opérations.

L'avertissement Django `fields.W342` demeure connu : la table d'affectations
possède une clé composite gérée en SQL direct. Son modèle de lecture ne doit
pas être converti arbitrairement en relation un-à-un.

Les tests historiques FastAPI ne sont pas présentés comme une preuve sur
Django. Ils restent inchangés dans l'archive.

## Travaux encore nécessaires pour une version prête à l'emploi

| Priorité | Travail | Critère de sortie |
|---|---|---|
| 1 | Mettre à niveau Django et DRF dans un environnement isolé | Version maintenue et toutes les recettes réussies |
| 1 | Recette complète par métier, notamment retours, annulations et opérations intersociétés | Scénarios approuvés avec leurs effets comptables et de stock |
| 1 | Idempotence serveur et concurrence sur paiements, numérotation, validations et stocks | Plusieurs postes ne peuvent produire un double paiement ou un numéro dupliqué |
| 1 | Validation systématique des entrées de l'API | Données mal formées et valeurs interdites refusées sans écritures partielles |
| 1 | Politique des sessions et contrôle d'accès approfondi | Révocation, changement de mot de passe, limitation des tentatives et matrice de rôles éprouvés |
| 1 | Reprise, hébergement, sauvegardes hors machine et restauration | Exercice de restauration et reprise des soldes validés sur le serveur cible |
| 2 | Optimisation des listes et rapports | Pagination et mesure des requêtes sur un volume représentatif |
| 2 | Découpage progressif de l'interface | Modules testables séparément ; formulaires conservés pendant les changements de page |
| 2 | UX détaillée métier par métier | Parcours compris et exécutés sans aide par caissier, comptable, magasinier et réceptionniste |
| 2 | Hors connexion et synchronisation | Règles explicites de conflits, limites de crédit et paiements après reconnexion |
| 3 | Budget d'engagement, RH/paie, consolidation et intégrations externes | Spécifications et calculs vérifiés avec les responsables concernés |

Django 5.1 est hors support depuis le 3 décembre 2025. La consigne historique
« rester sur 5.1 » doit donc être remplacée par une montée de version testée ;
la série 5.2 LTS reste supportée jusqu'en avril 2028. Les dépendances installées
n'ont pas été changées pendant cette première livraison.
[Calendrier officiel Django](https://www.djangoproject.com/download/),
[notes de versions DRF](https://www.django-rest-framework.org/community/release-notes/).

La préparation du serveur doit suivre les contrôles de déploiement du framework.
[Guide officiel Django](https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/).

## Examiner cette livraison

La version de recette a été démarrée à l'adresse **http://127.0.0.1:8012** avec
une **copie** de la base. Les opérations effectuées dans cet aperçu ne sont pas
des opérations de la base de travail. L'aperçu dépend du serveur local lancé
pour cette intervention.

Les changements sont dans les fichiers du projet, sans publication externe,
sans modification de l'archive FastAPI et sans application des migrations à la
base de travail. Voir `../backend/README.md` pour les commandes de
vérification et d'utilisation de l'installation Django existante.
