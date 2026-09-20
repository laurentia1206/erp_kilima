# Critique de la proposition ChatGPT & feuille de route — ERP Groupe KILIMA HOLDINGS

> Document de cadrage. Version 1 — 2026-06-22.

## 1. Verdict global

La proposition ChatGPT est un **bon inventaire fonctionnel** : la couverture des métiers est large, et surtout la **philosophie « contrôle dès la demande » (réquisition → validation → caisse)** est la bonne. Le « Centre d'approbation » est une excellente idée.

Mais c'est une **liste de fonctionnalités, pas un plan d'ingénierie**. Elle promet une « intégration des modules sans difficulté » sans jamais montrer **comment** les modules se parlent (aucun modèle de données). Or c'est précisément là que 90 % des projets ERP échouent. Plusieurs sujets *durs et propres à la RDC* sont survolés ou absents.

## 2. Ce qui est juste et à garder

- Architecture **multi-sociétés / multi-agences** sur une base unique.
- Le **verrou décaissement** : le caissier exécute, il ne crée jamais une dépense. À conserver absolument.
- Le **workflow par seuils de montant** (chef → DAF → DG).
- L'**audit / traçabilité** (qui, quand, ancienne/nouvelle valeur).
- Le découpage en **pôles métiers** (Direction, Finance, Commerce, Opérations, Hospitality).
- Le **MVP par modules** plutôt que tout d'un coup.

## 3. Ce qui manque ou est sous-estimé (les vrais risques)

### 3.1 Le multi-devises USD/CDF — traité en deux mots, c'est LE sujet dur
ChatGPT écrit « USD, CDF » et passe. En réalité il faut décider et concevoir :
- **Devise fonctionnelle vs devise de reporting.** Vous opérez en USD mais l'OHADA/le fisc exigent des états en CDF. Chaque écriture doit pouvoir être tenue dans les deux.
- **Gestion des taux** : taux du jour, taux historique (pour les immobilisations), taux de clôture.
- **Écarts de change** (gains/pertes de change réalisés et latents) — comptes dédiés, calcul automatique. Absent de la proposition.
- Une caisse USD et une caisse CDF dans la même agence, conversions tracées.

### 3.2 La consolidation groupe — la partie la plus difficile est ignorée
« Consolidation groupe » ≠ additionner les résultats. Il faut **éliminer les opérations intra-groupe** :
- PLANET ou DAKAM qui vend à KAKO, EST HORIZON qui loue à KAKO LOGISTIC, prêts et comptes courants entre sociétés.
- Sans élimination des intercos, le CA et le résultat consolidés sont **faux** (gonflés).
- Il faut donc marquer les tiers « intra-groupe » dès la saisie pour automatiser l'élimination.

### 3.3 Fiscalité RDC — à peine mentionnée, pourtant bloquante
- **TVA 16 %** (collectée / déductible, déclaration mensuelle).
- **Facture normalisée / dispositif fiscal électronique DGI** — obligation légale de numérotation et de format. Le module facturation doit s'y conformer dès le départ.
- **Retenues sur salaires** : IPR, cotisations CNSS, etc. (impact module Paie).
- **Impôts sur décaissements** : précompte BIC, retenues fournisseurs.
- Ces règles doivent être **paramétrables** (les taux changent), pas codées en dur.

### 3.4 SYSCOHADA révisé — il faut un vrai moteur d'écritures
ChatGPT donne des exemples « 601 / 401 » codés en dur. Il faut un **moteur de schémas comptables** : chaque type d'opération (achat, vente, paiement, avance, paie, dotation…) déclenche une écriture paramétrable, multi-devises, équilibrée, avec **lettrage** auxiliaire (clients/fournisseurs).

### 3.5 Clôture des périodes — absente, critique pour un DAF
- Verrouillage des périodes (mois/exercice) : interdiction d'écritures antidatées une fois la période close.
- Reports à nouveau, génération de la DSF (états financiers SYSCOHADA).
- Sans clôture, aucun chiffre n'est fiable dans le temps.

### 3.6 Contrôle budgétaire — le mot « engagement » manque
Pour bloquer une dépense, il faut une **comptabilité d'engagement** : `Budget → Engagé (réquisition validée) → Réalisé (facture) → Payé`. Le disponible budgétaire = budget − engagé, pas seulement budget − payé. C'est la différence entre un vrai contrôle et un tableau de bord décoratif.

### 3.7 Connectivité RDC & mode hors-ligne — pas un mot
Sites distants (Lubumbashi, Likasi, Kolwezi), internet instable. Le **POS KAKO** et la **réception hôtel** ne peuvent pas s'arrêter quand le réseau tombe. Décision d'architecture à prendre tôt : web centralisé ? postes avec cache hors-ligne et synchronisation ? Cela conditionne toute la stack.

### 3.8 Mobile money — « mode de paiement » ≠ intégration
Airtel Money / M-Pesa / Orange Money : encaisser est facile à *afficher*, mais le **rapprochement** avec les relevés opérateurs et les frais de transaction est le vrai travail.

### 3.9 Le moteur de workflow doit être configurable
Les seuils `<500 / <5000` ne suffisent pas : ils varient **par société, par nature de dépense, par ligne budgétaire**. Il faut un moteur de règles paramétrable, pas des seuils en dur.

### 3.10 Séparation des tâches & droits fins
La matrice des profils doit encoder la **ségrégation des fonctions** (celui qui valide ≠ celui qui paie ≠ celui qui comptabilise) — c'est votre meilleure arme anti-détournement.

## 4. Recompositions du MVP que je recommande

ChatGPT propose un MVP à 8 modules (compta, tréso, achats, stocks, ventes/POS, crédit, avances, dashboard). C'est **trop large pour une V1**. Stocks + POS + ventes à crédit, c'est déjà à eux seuls un projet.

**Je resserre le MVP sur la « colonne vertébrale du décaissement »** — votre plaie ouverte (sorties de fonds non contrôlées) :

**V1 — Le verrou financier (cœur)**
1. **Référentiel** : sociétés, agences, plan comptable SYSCOHADA, utilisateurs, profils & droits, centres de coûts, devises & taux.
2. **Réquisitions** : demande → workflow d'approbation configurable → bon à payer.
3. **Avances à justifier** : octroi, blocage si avance non justifiée, justification, calcul du solde (trop-perçu / complément).
4. **Caisse & Trésorerie** : caisses + banques multi-devises ; le caissier exécute uniquement ce qui est validé.
5. **Comptabilité OHADA** : moteur d'écritures automatiques sur les opérations ci-dessus + grand livre / balance.
6. **Dashboard DAF** : tréso temps réel, encours d'avances, dépenses engagées vs payées.

Cette V1 fait fonctionner **toutes les sociétés** dès le premier jour (toute société dépense de l'argent) et installe le modèle de données central.

**V2 — Commerce** : achats complets (BC → réception → facture), stocks multi-dépôts, ventes/POS, crédit clients. (PLANET, DAKAM, KAKO)

**V3 — Opérations** : location d'engins + timesheets (EST HORIZON), transport + carburant + rentabilité voyage (KAKO LOGISTIC), maintenance.

**V4 — Hospitality** : hôtel, restaurant (recettes & food cost), bar, housekeeping (Guest House Relax).

**V5 — Pilotage groupe** : consolidation avec élimination intercos, contrôle budgétaire avancé, KPI par activité, appli mobile « Centre d'approbation ».

## 5. Comment procéder (méthode)

1. **Récupérer l'existant** — vos ébauches Compta + Dashboard DAF, et surtout vos **Excel de gestion actuels** : ils contiennent vos vraies règles. (dossier `entrants/`)
2. **Modéliser la colonne vertébrale** — atelier détaillé sur Réquisition → Avance → Caisse → Écriture : tous les états, qui valide quoi, quels contrôles bloquants. C'est le document fondateur.
3. **Décider l'architecture** — après avoir cerné la contrainte connexion (point 3.7). Web/mobile, base de données, hébergement (local vs cloud).
4. **Concevoir le modèle de données central** — sociétés, tiers, comptes, écritures, devises, workflow. C'est ce qui garantit l'« intégration sans difficulté ».
5. **Construire la V1 par itérations** — chaque module démontrable avant de passer au suivant.

## 6. Prochaines décisions à trancher avec vous

- Périmètre exact de la V1 (valider le resserrage proposé au §4).
- Devise fonctionnelle de tenue de compte (USD ou CDF ?) et politique de taux.
- Contrainte connexion réelle par site (pour décider web pur vs hors-ligne).
- Y a-t-il des opérations entre sociétés du groupe ? (impacte la consolidation).
- Êtes-vous déjà sur un logiciel comptable ? (reprise de données / plan comptable existant).
