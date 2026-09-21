# CAHIER DES CHARGES FONCTIONNEL ET TECHNIQUE
# Système Intégré de Gestion — GROUPE KILIMA HOLDINGS

| | |
|---|---|
| **Maître d'ouvrage** | Direction Financière (DFI) — Groupe KILIMA HOLDINGS |
| **Périmètre** | 7 sociétés, sites de Likasi & Kolwezi (RDC) |
| **Référentiel comptable** | SYSCOHADA révisé |
| **Devises** | USD (pivot) et CDF |
| **Nature du projet** | Développement sur mesure (full custom) |
| **Version du document** | 1.0 — 2026-06-22 |
| **Statut** | Document de travail — à valider par la Direction |

---

## 1. PRÉSENTATION DU PROJET

### 1.1 Contexte et enjeux
Le Groupe KILIMA HOLDINGS exploite sept sociétés aux métiers variés (distribution, négoce, quincaillerie, location d'engins, transport, hôtellerie). La gestion repose aujourd'hui sur un **système documentaire papier/Excel déjà standardisé** (formulaires G01 à G09, procédures écrites par société, notes de service) et sur des outils dispersés (Excel, papier, plateforme DGI). Un prototype comptable OHADA (`sysco_erp`) et un prototype de tableau de bord DFI existent déjà.

L'enjeu central, exprimé par la Direction Financière, est le **contrôle des décaissements** : aujourd'hui, les sorties de fonds sont contrôlées de façon manuelle et chronophage, et le suivi des **avances à justifier** est difficile. Le projet vise à **numériser et faire respecter automatiquement** ce système existant, et non à le réinventer.

### 1.2 Objet du document
Ce cahier des charges décrit les exigences fonctionnelles, techniques et non fonctionnelles du futur système. Il sert de base au chiffrage, au développement et à la recette. C'est un **document vivant**, appelé à être affiné au fil des ateliers.

### 1.3 Décisions structurantes
- **D1 — Développement sur mesure.** La solution sera développée spécifiquement pour le groupe (option Odoo écartée par la Direction).
- **D2 — Démarche par phases.** Livraison incrémentale, module par module (voir §21), pour obtenir une solution opérationnelle rapidement sans tout construire d'un coup.
- **D3 — Le contrôle du décaissement est prioritaire** (V1).
- **D4 — Multi-société / multi-site / multi-devise** sont des exigences de socle, pas des options.
- **D5 — La logique comptable OHADA du prototype `sysco_erp` est réutilisée** ; sa stack technique est refondue (sécurité, multi-utilisateur).

### 1.4 Objectifs mesurables
Le système doit permettre de :
1. **Contrôler chaque dépense dès la demande** (et non au moment du paiement) ;
2. Garantir qu'**aucune sortie de fonds** n'a lieu sans réquisition et autorisation conformes aux paliers ;
3. **Bloquer automatiquement** toute nouvelle avance à un agent ayant une avance non justifiée ;
4. Donner au DFI une **visibilité temps réel** sur la trésorerie, les avances en cours, les créances et la conformité quotidienne ;
5. **Automatiser la comptabilisation OHADA** des opérations ;
6. Produire les **états financiers** et la **consolidation groupe** ;
7. Assurer la **traçabilité intégrale** (qui, quand, quoi, ancienne/nouvelle valeur).

---

## 2. PÉRIMÈTRE

### 2.1 Entités du groupe

| Code | Entité | Métier | Stock | Spécificité majeure |
|---|---|---|---|---|
| PLA | **PLANET Sarl** | Distribution à la commission (chaux/gravier GCK) | Non | Reverse à GCK **après** encaissement client, au prorata |
| DAK | **DAKAM Sarl** | Achat/revente ciment en gros | Non (hébergé GCK) | 2 circuits de vente ; n° commande GCK obligatoire ; entité « stratégique » |
| KAL | **KAKO Sarl — Likasi** | Quincaillerie + ciment détail | Oui (papier+Excel) | Retail + Business |
| KAK | **KAKO Sarl — Kolwezi** | Quincaillerie + ciment détail | Oui (système IT) | Caissier = vendeur → contrôle hebdo obligatoire |
| KLO | **KAKO Logistique** | Transport (15 camions) | Non | Avance carburant vérifiée au réservoir |
| HOR | **Ets HORIZON** | Location d'engins miniers | Non | Facturation mensuelle sur fiches de prestation ; validation demande DG+DT |
| GHR | **Guest House Relax** | Hôtel + restaurant + bar | Boissons seulement | Reçus manuels → régularisation DGI quotidienne ; contrôle cuisine par ratio |

> **Caisse centrale** : une caissière centrale (Eliane MUSOLO) encaisse/décaisse pour **toutes** les sociétés.

### 2.2 Sites
Likasi (siège financier, caisse centrale, majorité des entités) et Kolwezi (KAKO Sarl Kolwezi, comptable de KAKO Logistique). Le système doit être **mono-base, multi-site**, accessible depuis les deux villes.

### 2.3 Acteurs / parties prenantes
Président · Directeur Général (Arsène) · **Directeur Financier / DFI (maître d'ouvrage)** · Administratrice (Huguette) · Directeur Technique (Ruffin, HORIZON) · Comptables (par société, certains gèrent 2 entités) · Caissière centrale (Eliane) · Caissier-vendeur Kolwezi (Patient) · Responsable Inventaire & IT · Assistant technique logistique · Vendeurs · Réceptionnistes GHR · Bénéficiaires d'avances (agents). Voir matrice §5.

### 2.4 Périmètre fonctionnel par phase (in/out scope)
Voir le plan de déploiement détaillé au §21. En résumé : **V1** = socle + décaissement/avances + caisse + compta + dashboard DFI ; **V2** = achats/stocks/ventes/POS/créances ; **V3** = location engins + transport ; **V4** = hôtellerie ; **V5** = budget avancé + consolidation + mobile.

---

## 3. ARCHITECTURE GÉNÉRALE ET EXIGENCES TECHNIQUES

### 3.1 Principes fondateurs
- **Multi-société** : une base unique ; chaque opération est rattachée à une société. Cloisonnement strict des données par société selon les droits.
- **Multi-site** : accès concurrent depuis Likasi et Kolwezi.
- **Multi-devise** : USD (devise pivot) et CDF gérés **au niveau de chaque ligne d'opération** (voir §4.3).
- **Multi-utilisateur** : accès simultané sécurisé, traçabilité par utilisateur.
- **Configurable** : seuils, paliers, délais, circuits de validation **paramétrables** (jamais codés en dur).

### 3.2 Architecture applicative recommandée
- **Application web centralisée** (navigateur), responsive, complétée en V5 par une **application mobile** pour le « Centre d'approbation ».
- **Backend** : API REST structurée, base de données relationnelle **PostgreSQL** (transactions ACID, accès concurrent — le SQLite du prototype est insuffisant). Couche métier comptable portée depuis `sysco_erp`.
- **Frontend** : application web moderne (la maquette du prototype sert de référence UX).
- **Séparation stricte** : la logique métier (validation OHADA, calculs d'états, règles de workflow) réside **côté serveur**, jamais dans le navigateur.

### 3.3 Hébergement et connectivité (point critique RDC)
- Décision d'hébergement à confirmer : **cloud** (accessible multi-sites, sauvegardé) recommandé, vs serveur local.
- **Mode dégradé / hors-ligne** : à étudier pour les postes critiques en cas de coupure réseau (notamment POS KAKO et réception GHR), avec synchronisation au rétablissement. À cadrer selon la qualité réelle de connexion par site (**question ouverte, cf. §22**).

### 3.4 Sécurité et authentification
- Authentification obligatoire (login + mot de passe haché, politique de complexité, expiration de session).
- **Contrôle d'accès côté serveur** par rôle ET par société (un comptable ne voit que ses sociétés). L'isolation ne doit jamais dépendre d'un paramètre d'URL.
- Chiffrement des communications (HTTPS), sauvegardes chiffrées, journal de connexion.

### 3.5 Intégrations
- **Plateforme de facturation DGI** : émission des factures normalisées (étude d'interface ou ressaisie contrôlée).
- **Mobile money** (Airtel/M-Pesa/Orange) : encaissement et **rapprochement** avec relevés opérateurs (V2+).
- **Email / WhatsApp** : notifications de workflow.
- Export comptable et tableurs (Excel/PDF).

---

## 4. EXIGENCES TRANSVERSES (SOCLE)

### 4.1 Référentiel
Gestion centralisée de : sociétés, sites/agences, départements, **centres de coûts**, utilisateurs, profils/rôles. CRUD réservé aux administrateurs. Chaque entité a ses identifiants légaux (RCCM, ID Nat, NIF).

### 4.2 Plan comptable SYSCOHADA & exercices
- Plan comptable **SYSCOHADA révisé**, par société, avec comptes auxiliaires (clients/fournisseurs/agents).
- Gestion des **exercices** (ouverture/clôture), journaux (Ventes, Achats, Banque, Caisse, OD, À-nouveaux, etc.).
- Import d'une balance d'ouverture (déjà supporté par le prototype).

### 4.3 Multi-devise USD/CDF (exigence forte)
- **USD = devise pivot** de tenue et de consolidation (à confirmer ; les états légaux peuvent exiger le CDF — cf. §22).
- Chaque ligne d'opération porte **un montant USD et un montant CDF**, conformément à tous les formulaires existants (G01–G06, G08, journaux, registres).
- **Table des taux de change** : taux du jour, taux historique, taux de clôture, avec historisation.
- **Écarts de change** : calcul et comptabilisation automatiques des gains/pertes de change (réalisés et latents) sur comptes dédiés.
- Totalisations et états disponibles **par devise** et en équivalent pivot.

### 4.4 Gestion des tiers
- Référentiel clients / fournisseurs / agents (bénéficiaires d'avances).
- **Marquage « intra-groupe »** des tiers qui sont d'autres sociétés du groupe (indispensable à la consolidation — §19).
- Limites de crédit clients, conditions de paiement.

### 4.5 Numérotation et séquences
- Numérotation **unique, séquentielle et non réutilisable** par type de pièce et par société (ex. réquisition `REQ-PLA-2026-000125`, avance `AVJ-2026-000125`, ordre de dépense, bon de réception, justification).
- Conformité **facture normalisée DGI** (format et numérotation légaux). Reçus manuels GHR numérotés, jamais détruits (un reçu annulé est conservé barré).

### 4.6 Moteur de workflow et de validation (configurable)
- Moteur de circuits d'approbation **paramétrable par société, par type de document, par palier de montant et par nature de dépense**.
- Notion de **validation multi-signataires** (co-signature conjointe).
- États de document configurables ; historique de chaque transition (qui, quand, commentaire).
- Substitution/délégation en cas d'absence (ex. « le Président peut valider seul en cas d'indisponibilité »).

### 4.7 Notifications
Notifications **in-app, email et WhatsApp** sur les événements de workflow (demande à valider, avance à justifier, échéance, alerte). Un destinataire voit en un coup d'œil ce qui l'attend (cf. Centre d'approbation §18).

### 4.8 Audit et traçabilité (immuable)
- **Aucune suppression physique** de données financières : annulation par contre-passation/extourne uniquement.
- **Journal d'audit immuable** : pour chaque action, enregistrer utilisateur, horodatage, type d'action, **ancienne et nouvelle valeur**. Exemple attendu : « Prix du ciment passé de 11 à 10,5 USD le 15/06/2026 à 10h22 par Jean Kabongo ».
- Journal consultable et filtrable, non modifiable.

### 4.9 Gestion documentaire
Toute pièce (devis, proforma, facture, reçu, photo) peut être **jointe** au document concerné (réquisition, justification d'avance, etc.) et conservée.

### 4.10 Clôture de période
- **Verrouillage** des périodes comptables (mensuelle, annuelle) : interdiction d'écriture antidatée sur période close.
- Reports à nouveau ; génération des états de synthèse (DSF SYSCOHADA).

---

## 5. UTILISATEURS, RÔLES ET DROITS

### 5.1 Rôles
| Rôle | Périmètre | Pouvoirs clés |
|---|---|---|
| **Président** | Groupe | Valide les décaissements > 10 000 USD ; co-signataire 1 001–10 000 ; **fixe les plafonds** ; supervision |
| **Directeur Général (DG)** | Groupe | Supervision ; co-signataire ; valide la *demande* (standard) ; destinataire des rapports |
| **Directeur Financier (DFI)** | Groupe | **Autorise les sorties de fonds** ; valide paiements/achats/avances ; reçoit escalades ; supérieur des comptables/caissiers ; accès toutes sociétés |
| **Administrateur (Admin)** | Groupe | Co-validation de la demande + co-signature palier 1 001–10 000 |
| **Directeur Technique (DT)** | HORIZON | Co-validation des **demandes techniques** (engins, pièces) ; arbitrage immobilisation/charge |
| **Comptable** | Ses sociétés | Saisie comptable, préparation/exécution paiements, réconciliations, états, fiscalité |
| **Caissier central** | Toutes sociétés | Encaisse/décaisse **uniquement sur ordre validé** ; tient journaux ; clôture caisse |
| **Caissier-vendeur (point de vente)** | Sa société/site | Caisse + vente comptoir + facturation cash ; soumis à contrôle hebdo |
| **Responsable Inventaire & IT** | Son site | Contrôle physique caisse hebdo + signe PV ; inventaire ; support IT |
| **Assistant technique** | KLO / HOR | Saisie fiches course / prestations |
| **Vendeur** | Point de vente | Saisie ventes, facturation |
| **Administrateur système** | Technique | Gestion utilisateurs, paramétrage, sauvegardes (sans accès aux validations financières) |

### 5.2 Matrice des droits
Le système gère des droits fins **par module et par action (CRUD + valider/approuver/exécuter)**, croisés avec le **périmètre société/site**. Un comptable affecté à PLANET + GHR ne voit que ces deux sociétés. Une matrice détaillée RACI sera produite en annexe d'atelier.

### 5.3 Séparation des tâches (règles dures)
À câbler dans le système, non contournables :
- Celui qui **crée** la réquisition ≠ celui qui **autorise** ≠ celui qui **exécute** le décaissement ≠ celui qui **comptabilise** ≠ celui qui **contrôle**.
- **Interdiction d'auto-validation** : un utilisateur ne peut valider sa propre demande.
- Cas caissière centrale (« seule à vérifier sa propre caisse ») : contrôle indépendant obligatoire (cf. §7).
- Cas caissier-vendeur Kolwezi : contrôle physique hebdomadaire signé par le Responsable Inventaire & IT.

### 5.4 Délégations et plafonds paramétrables
Les seuils de validation, les plafonds de délégation et les seuils « à définir par la DG » (cf. §22) sont des **paramètres configurables par société et par rôle**.

---

## 6. MODULE CŒUR — CENTRE DE DÉCAISSEMENT & AVANCES À JUSTIFIER ⭐

> Module prioritaire (V1). Il numérise le circuit documentaire existant G01 → G04 et ses contrôles. C'est la **colonne vertébrale** du système.

### 6.1 Vue d'ensemble du circuit
```
[Agent] G01 Réquisition
        → Validation de la DEMANDE (e-mail/in-app, multi-signataires)
        → [DFI] G02 Ordre de Dépense  (validation SORTIE DE FONDS selon paliers)
        → [Caissier] G03 Bon de Réception de Fonds  (remise des fonds)
        → Exécution / Achat
        → [Agent] G04 Fiche de Justification d'Avance  (≤ délai)
        → Contrôle d'équilibre (Avance = Dépenses + Solde retourné)
        → Retour du solde en caisse  /  Demande complémentaire
        → Comptabilisation automatique OHADA
        → Clôture du dossier
```

### 6.2 G01 — Réquisition (Requisition Form)
**Objet** : initier une demande de sortie de fonds.
**Champs** : n° réquisition (auto), date, **société**, département/centre de coûts, initié par, **priorité** (Normal / Urgent / Top Urgent), objet/justification, **lignes** (imputation comptable proposée, code article, description, unité, quantité, prix unitaire, total), **total USD / total CDF**, jusqu'à **3 fournisseurs suggérés**, **pièces jointes** (devis, proforma, photos).
**Règles** :
- Au moins une ligne ; total cohérent ; devise renseignée.
- Le centre de coûts conditionne le contrôle budgétaire (V5).
**États** : `Brouillon → Soumise → (Demande validée / Rejetée / En attente d'info) → Transformée en Ordre de Dépense → Clôturée`.

### 6.3 Moteur de validation par paliers (règle de gestion centrale)
Deux validations **distinctes** :

**(a) Validation de la DEMANDE** (en amont) :
- Standard : **DG + Administratrice**, conjointement.
- **Exception HORIZON** : **DG + DT (Ruffin)**, conjointement (caractère technique).
- En cas d'indisponibilité : le **Président peut valider seul**.
- La validation **e-mail/in-app fait foi** ; aucune instruction verbale n'est acceptée.

**(b) Validation de la SORTIE DE FONDS** (sur l'Ordre de Dépense) — grille par palier, **paramétrable** :

| Palier (équivalent USD) | Approbateurs requis |
|---|---|
| ≤ 1 000 | DFI seul |
| 1 001 – 10 000 | DFI + DG + Administratrice + Président (conjoints) |
| > 10 000 | Président |

> Les bornes (1 000 / 10 000) sont des paramètres. Le palier s'évalue sur l'équivalent USD si la demande est en CDF.

### 6.4 G02 — Ordre de Dépense
**Objet** : autorisation formelle de décaissement.
**Champs** : n° ordre (auto), **réf. réquisition G01**, bénéficiaire, lignes avec **compte d'imputation** + montant USD + montant CDF, total autorisé, **montant en lettres**, motif, **signatures** (Caissier / DFI / Bénéficiaire), mode prévu (Caisse/Banque).
**Règles** : ne peut être émis que depuis une réquisition à demande validée ; déclenche le circuit de paliers (§6.3b) ; sans les co-signatures requises, **le caissier doit refuser le décaissement**.
**États** : `À valider → Validé (selon palier) → Transmis caisse → Exécuté → Clôturé / Rejeté`.

### 6.5 G03 — Bon de Réception de Fonds
**Objet** : accusé de réception des fonds par le bénéficiaire.
**Champs** : n° bon, **réf. G02**, receveur, déposant/caissier, montant USD/CDF, **mode (Caisse/Banque)**, montant en lettres, signatures.
**Règles** : généré au moment de la remise effective ; alimente le journal de caisse (G05).

### 6.6 Exécution / décaissement
- **Le caissier exécute uniquement** ce qui est validé. Il ne peut **jamais** créer une dépense.
- Vérification automatique : ordre validé + co-signatures conformes au palier + solde de caisse suffisant.
- Pour KAKO Logistique : l'avance carburant n'est **jamais remise en espèces** au chauffeur — elle est **vérifiée physiquement au réservoir** (statut spécifique).

### 6.7 G04 — Fiche de Justification d'Avance
**Objet** : reddition de comptes après dépense.
**Champs** : n° fiche, **réf. G02**, avance reçue USD/CDF, **lignes de dépense** (date, nature, fournisseur, n° reçu/facture, montant USD/CDF, pièce jointe), **total justifié**, **solde non utilisé retourné**, **contrôle d'équilibre**.
**Contrôle d'équilibre automatique** : `Avance reçue = Total dépenses justifiées + Solde retourné`.
- **Cas 1 — Trop-perçu** (avance > dépenses) : le solde doit être **remboursé en caisse** ; le dossier ne se clôt qu'après retour effectif.
- **Cas 2 — Dépense supérieure** (avance < dépenses) : génère une **demande complémentaire** soumise au circuit de validation.
- **Écart inexpliqué** : signalé au DFI, dossier bloqué.
**États** : `À justifier → Justifiée (en contrôle) → Validée → Comptabilisée / Rejetée (à corriger)`.

### 6.8 Règle de blocage automatique (exigence forte)
- Tout bénéficiaire ayant **une avance non justifiée au-delà du délai** (ou un solde non remboursé) est **automatiquement bloqué** : il ne peut recevoir aucune nouvelle avance.
- **Levée** uniquement par le DFI (avec motif tracé), ou après régularisation.
- Le blocage et son motif sont visibles dans le dossier de l'agent et sur le dashboard DFI.

### 6.9 Délais de justification par type d'avance (paramétrables)
| Type d'avance | Délai | Entité |
|---|---|---|
| Avance course (carburant + route), solde retour camion | **2 h** après retour | KAKO Logistique |
| Avance achats alimentaires (marché) | **2 h** après retour marché | GHR |
| Avance chauffeur / convoyeur | lendemain matin | KAKO Logistique |
| Pièces / maintenance | **24 h** | HORIZON, KAKO Log. |
| Boissons / dépenses diverses | **24 h** | GHR, KAKO, PLANET |
| Budget entretien mensuel forfaitaire | avant le **30 du mois** | GHR |
| Avance fournisseur GCK | apurement ≤ **15 j** (alerte 10 j) | DAKAM |

### 6.10 Comptabilisation automatique (schémas OHADA)
Le système génère les écritures **sans saisie manuelle** (moteur de schémas §8.2). Schémas types observés :
- **Versement d'avance** : D **4091** (ou 425/467 selon bénéficiaire) / C **52 ou 57** (banque/caisse).
- **Réception facture / justification (achat)** : D **601** (ou compte de charge/immo idoine) / C **4091**.
- **Trop-perçu remboursé** : D **52/57** / C **4091**.
- **Avance < facture (complément dû)** : D **4091** / C **401**.
- HORIZON : distinction **immobilisation (2xx) vs charge (6xx)** arbitrée par DT + DFI.

### 6.11 Diagramme d'états du dossier d'avance
`Réquisition(Brouillon→Soumise→Validée) → OrdreDépense(Validé→Exécuté) → BonRéception(Émis) → Avance(À justifier→Justifiée→Validée) → Comptabilisée → Clôturée`. États d'exception : `Rejetée`, `Bloquée`, `Complément demandé`, `Trop-perçu à rembourser`.

### 6.12 Variantes par société (paramétrage)
- **DAKAM / GCK** : avance fournisseur GCK, apurement ≤ 15 j, récupération facture ≤ 5 j, schéma 4091.
- **KAKO Logistique** : avance par course (km × conso + péages), vérif. réservoir, retour solde ≤ 2 h.
- **GHR** : avance journalière marché (Idris), justification ≤ 2 h ; avance mensuelle forfaitaire entretien.
- **HORIZON** : validation demande DG + DT ; arbitrage immo/charge.

---

## 7. MODULE CAISSE & TRÉSORERIE

### 7.1 Caisses
Une ou plusieurs caisses **par société/site**, tenues en **USD et CDF**. La caissière centrale opère pour toutes les sociétés (journaux séparés par entité).

### 7.2 G05 — Journal de caisse journalier
Solde d'ouverture USD+CDF, mouvements (heure, nature, réf. document, entrée/sortie USD, entrée/sortie CDF, solde courant), solde de clôture **théorique vs physique compté**, **écart**. Tout écart ≠ 0 ⇒ **signalement immédiat au DFI**.

### 7.3 G06 — Bordereau de cession de fonds
Transfert de fonds entre caisses (ex. caisses GHR/KAKO → caisse centrale) : cédant/receveur, catégories (ventes espèces USD/CDF, encaissements clients, avances non dépensées…), total cédé, reçus joints.

### 7.4 G08 — Fiche de clôture de caisse
Réconciliation théorique/physique avec **détail de comptage par coupure** (billets/pièces USD et CDF, autres devises). Explication d'écart obligatoire si ≠ 0.

### 7.5 Banques et rapprochement bancaire
Comptes bancaires par société ; saisie/import des relevés ; **rapprochement bancaire** (lettrage relevé ↔ écritures) ; prévisions de trésorerie.

### 7.6 Règles
- Le caissier exécute, ne crée jamais une dépense (cf. §6.6).
- Aucune caisse ne peut afficher un solde négatif (alerte/blocage).

---

## 8. MODULE COMPTABILITÉ OHADA

### 8.1 Écritures et partie double
Saisie d'écritures multi-lignes, contrôle **Débit = Crédit** en temps réel (repris du prototype), journaux OHADA, pièces jointes, libellés, lettrage.

### 8.2 Moteur de schémas comptables (paramétrable)
Chaque **type d'opération** (achat, vente, paiement, avance, paie, dotation…) déclenche une **écriture paramétrable** (comptes, sens, devise), au lieu d'écritures codées en dur. Permet l'automatisation du §6.10 et des autres modules.

### 8.3 Comptabilité auxiliaire & lettrage
Comptes auxiliaires clients/fournisseurs/agents ; **lettrage** des paiements ; balance âgée ; historique par tiers.

### 8.4 États financiers
Balance, grand livre, **bilan OHADA** (Brut/Amort/Net, comparatif N-1), **compte de résultat**, **TFT** (méthode indirecte SYSCOHADA). La logique du prototype est reprise mais **calculée côté serveur** (bilan/résultat ne doivent plus être calculés dans le navigateur).

### 8.5 Audit OHADA automatique
Reprise des **7 règles d'audit** du prototype (actif créditeur, caisse créditrice, amortissement débiteur, charge/produit anormaux, compte courant associé débiteur…), classées warning/critique, avec explication.

### 8.6 Fiscalité DGI
- **TVA 16 %** (collectée/déductible) ; déclarations entre le **10 et le 15** du mois suivant.
- **Facture normalisée DGI** : conformité format et numérotation ; gestion du cas GHR (reçus manuels → régularisation quotidienne, risque fiscal si non régularisé < 24 h).
- Retenues et précomptes (fournisseurs, salaires) — voir §16.
- Taux et règles **paramétrables**.

### 8.7 Clôture et DSF
Clôture mensuelle/annuelle, verrouillage (§4.10), reports à nouveau, génération des états de synthèse (DSF).

---

## 9. MODULE CRÉANCES & RECOUVREMENT

- **G07 — Tableau de suivi des créances** : par facture (n°, date, client, montant facturé USD/CDF, échéance, **jours de retard**, payé, solde, statut, dernière relance).
- Statuts : `En attente / Partiel / En retard / Soldé`.
- **Relance** automatique dès **+7 j** de retard ; **escalade DG** à **+30 j**.
- **Limites de crédit** clients : blocage des ventes à crédit au-delà de la limite.

---

## 10. MODULE ACHATS & FOURNISSEURS

- Circuit : **Réquisition → Bon de commande → Réception → Facture fournisseur → Paiement → Comptabilisation**.
- **Interdiction de payer sans réception** (contrôle bloquant).
- Base fournisseurs, contrats, historique, suivi des commandes (en attente / partiellement reçues / livrées).
- Cas **GCK** (DAKAM/PLANET) : avances fournisseur, n° de commande GCK, réconciliation mensuelle.

---

## 11. MODULE STOCKS & INVENTAIRE

- Articles (référence, désignation, catégorie, marque, unité), **multi-dépôts**.
- Mouvements : entrée, sortie, transfert, consommation interne, ajustement.
- **Transfert inter-sites** (KAKO) via **Bon de Transfert (KS01)** → compte inter-sociétés, **jamais une facture**.
- Inventaires : **physique hebdomadaire (vendredi)** (ST02), tournant, général ; **réconciliation ventes/caisse/stock** (ST03).
- Registres : stock journalier (ST01), **stock boissons GHR** (ST04).
- Valorisation **CUMP** ou **FIFO** (à choisir par société).
- Alertes : stock minimum, critique, rupture.

---

## 12. MODULE VENTES & FACTURATION

- **Retail / POS** (KAKO) : caisse, ticket/souche obligatoire, encaissement cash, mobile money, carte.
- **Business / à crédit** : devis → bon de commande → bon de livraison → **facturation sur quantités livrées** (≤ 48 h) → échéancier → encaissement.
- **Hébergement/services GHR** : facture unique regroupant chambre + restaurant + bar + autres (cf. §15).
- **Prestations HORIZON** : facturation mensuelle sur fiches de prestation (cf. §13).
- **Commandes DAKAM** : n° commande GCK obligatoire (VT04), 2 circuits.
- **Commission PLANET** : prix de vente toujours > prix GCK ; reversement après encaissement, au prorata.

---

## 13. MODULE LOCATION D'ENGINS (HORIZON)

- **Parc engins** : n°, marque, modèle, année, valeur, client affecté, historique.
- **Contrats de location** : client, période, tarif, conditions.
- **Fiches de prestation journalières (MT01)** saisies par le terrain, compilées (MT02), **réconciliées mensuellement** (avant le 3) et **validées/signées par le DT (Ruffin)** — pièce déclenchant la facturation (avant le 5).
- **Facturation automatique** (ex. heures × tarif).
- Suivi **coût de maintenance par engin** (ratio coût/CA) ; distinction immobilisation/charge (DT + DFI).
- Affectation du personnel (chauffeur/opérateur/mécanicien) ; suivi heures/disponibilité/pannes.

---

## 14. MODULE TRANSPORT & LOGISTIQUE (KAKO LOGISTIQUE)

- **Flotte** : camions/remorques (KL04 tableau de disponibilité — statut Disponible/Immobilisé ; **aucun camion non disponible ne peut être affecté**).
- **Fiche de course (KL01)** validée par DFI avant départ ; **check-list départ (KL02)** ; **fiche d'immobilisation (KL03)**.
- **Carburant** : avance par course (km × consommation) + péages + frais ; vérification au réservoir ; calcul **consommation moyenne**.
- **Rentabilité par voyage** : revenu − (carburant + chauffeur + péages) = résultat net.
- Circuit de données Likasi → Kolwezi (NS-2025-03) : fiche course chaque soir avant 18 h ; saisie comptable le lendemain avant 9 h ; rapport hebdo lundi ; validation DFI lundi avant 12 h.
- **RH chauffeurs** : avance de route, prime de course, **avance sur salaire plafonnée à 50 %** (déduite automatiquement) ; état de paie > 10 000 USD ⇒ Président.

---

## 15. MODULE HÔTELLERIE (GUEST HOUSE RELAX)

- **Chambres** : numéro, catégorie, tarif, capacité, état (Libre/Occupée/Sale/En nettoyage/Maintenance).
- **Réservations** : directe / téléphone / entreprise / en ligne ; check-in, check-out, annulations, no-show.
- **Occupation** : disponibles, occupées, **taux d'occupation**, revenu moyen/chambre.
- **Facture unique** regroupant hébergement + restaurant + bar + blanchisserie + autres.
- **Restaurant** : POS (table/chambre/à emporter), gestion des **recettes** (déduction automatique des matières premières du stock), **food cost** ; **contrôle cuisine par ratio coût/CA** (alerte si dépassement > seuil cible).
- **Bar** : POS, suivi bouteilles (stock initial → vendu → théorique → **écart**), contrôle des pertes (casse/offerts/consommation interne).
- **Housekeeping** : statuts chambres, suivi du personnel d'entretien.
- **Reçus manuels (VT03)** numérotés en temps réel → **régularisation en factures DGI chaque matin** (accès DGI limité au comptable).
- **Cession du soir** : commis caisse → agent centralisateur GHR (VT05) → caisse centrale.

---

## 16. MODULE RH & PAIE

- Dossier employé (contrat, fonction, département), pointage (présence/absence/congés).
- **Paie** : salaire, primes, heures supplémentaires, **retenues** (IPR, CNSS), avances sur salaire (plafond paramétrable, ex. 50 %).
- **Gestion disciplinaire** : avertissements, mises à pied, suspensions, historique.

---

## 17. MODULE CONTRÔLE BUDGÉTAIRE

- Budget **annuel** et **mensuel** par société/centre de coûts (incl. **budget département technique HORIZON — MT03**).
- **Comptabilité d'engagement** : `Budget → Engagé (réquisition validée) → Réalisé (facture) → Payé`.
- Avant validation d'une réquisition, **contrôle du disponible budgétaire** (= budget − engagé) ; **alerte/blocage** en cas de dépassement.
- Restitution : Budget / Réalisé / Écart / Taux de consommation ; réconciliation mensuelle (G09).

---

## 18. MODULE TABLEAU DE BORD DFI ⭐

> Reprend et connecte le prototype dashboard DFI à de vraies données (aujourd'hui en `localStorage`, mono-poste).

- **Vue « Aujourd'hui »** : les **~33 tâches journalières** attendues (par entité, responsable, **heure limite**), statut (OK / RETARD / ANOMALIE / MANQUANT / EN ATTENTE / N-A), **taux de conformité**.
- **Indicateurs journaliers par entité** : courses, tonnage, CA, encaissements, stocks, créances, occupation chambres, recettes hôtel/resto/bar…
- **Avances en cours** : encours USD/CDF, **retards**, **bloquées** (lien direct §6.8).
- **Créances** : échues > 7 j à relancer, > 30 j escaladées.
- **Suivi hebdomadaire** : 9 rapports du lundi + 12 points de contrôle (réconciliations, inventaires vendredi, ratio cuisine GHR, avances apurées, ratio maintenance HORIZON).
- **Actions & relances DFI** : journal de traçabilité (problème → action → réponse → résolution).
- **Rapport DG** : génération d'une synthèse copiable/exportable.
- **Alertes** : clients en retard, stocks faibles, véhicules en panne, avances non justifiées, dépassements budgétaires, écarts de caisse.
- Cadence cible : 17h30 caisses → 18h00 statuts → 18h30 relances → 19h00 vue complète.

---

## 19. MODULE CONSOLIDATION GROUPE

- Agrégation multi-sociétés : CA, résultat, trésorerie, créances, dettes, endettement — par société et **consolidé**.
- **Élimination des opérations intra-groupe** (ventes inter-sociétés, transferts, comptes courants) grâce au marquage des tiers intra-groupe (§4.4) — condition d'un résultat consolidé juste.
- Consolidation **multi-devises** (conversion au taux de clôture, gestion des écarts).
- Vues : tableau par société (résultat, tréso, endettement), résultat consolidé, KPI par activité (tonnage/marge PLANET-DAKAM, disponibilité/utilisation HORIZON, CA/marge par magasin KAKO, revenu/km KAKO Logistique, taux d'occupation/food cost GHR).

---

## 20. EXIGENCES NON FONCTIONNELLES

- **Performance** : réponse < 2 s sur les écrans courants ; états lourds en tâche de fond.
- **Disponibilité** : visée 99 % en heures ouvrées ; mode dégradé selon §3.3.
- **Sauvegarde** : automatique quotidienne, chiffrée, restauration testée.
- **Sécurité** : §3.4 ; conformité à la séparation des tâches.
- **Traçabilité** : §4.8.
- **Ergonomie** : interface en **français**, simple pour des utilisateurs peu informatisés ; cohérente avec les formulaires papier connus.
- **Scalabilité** : ajout de sociétés/sites sans refonte.
- **Maintenabilité** : code documenté, tests automatisés sur la logique comptable et les règles de workflow.

---

## 21. PLAN DE DÉPLOIEMENT (PHASES)

> Approche incrémentale. Chaque phase est livrée, recettée et mise en production avant la suivante.

**V1 — Le verrou financier (cœur)**
Référentiel · Plan comptable & exercices · Multi-devise USD/CDF · Utilisateurs/rôles/droits · **Centre de décaissement & avances (G01→G04)** · Caisse & trésorerie (G05/G06/G08) · Comptabilité OHADA (moteur d'écritures + balance/GL) · **Dashboard DFI** · Audit/traçabilité.
→ *Fait travailler toutes les sociétés dès le jour 1 et pose le modèle de données central.*

**V2 — Commerce & Distribution**
Achats complets · Stocks multi-dépôts & inventaires · Ventes/POS · Créances & recouvrement (G07). (PLANET, DAKAM, KAKO)

**V3 — Opérations industrielles**
Location d'engins + prestations (HORIZON) · Transport + carburant + rentabilité voyage (KAKO Logistique) · Maintenance.

**V4 — Hospitality**
Hôtel · Restaurant (recettes & food cost) · Bar · Housekeeping (GHR).

**V5 — Pilotage groupe**
Contrôle budgétaire (engagement) · **Consolidation avec élimination intra-groupe** · KPI par activité · **Application mobile « Centre d'approbation »** · Intégrations DGI / mobile money avancées.

---

## 22. ANNEXES

### A. Catalogue des documents existants (à numériser)
- **Standards G01–G09** : G01 Réquisition · G02 Ordre de Dépense · G03 Bon de Réception de Fonds · G04 Justification d'Avance · G05 Journal de Caisse · G06 Cession de Fonds · G07 Suivi des Créances · G08 Clôture de Caisse · G09 Réconciliation Mensuelle.
- **Spécifiques** : Logistique (KL01 Fiche de Course, KL02 Check-list Départ, KL03 Immobilisation, KL04 Disponibilité Flotte ; KS01 Transfert inter-sites) ; Stock (ST01 Registre journalier, ST02 Inventaire hebdo, ST03 Réconciliation, ST04 Stock boissons) ; Ventes (VT01 Retail, VT02 Hébergement, VT03 Reçus manuels, VT04 Commandes DAKAM, VT05 Bordereau consolidé GHR) ; Maintenance (MT01 Fiche prestation, MT02 Suivi prestations, MT03 Budget technique, MT04 Fiche technique camion).

### B. Schémas comptables types (extraits)
Voir §6.10. À compléter en atelier : ventes, encaissements, paie, dotations, change.

### C. Grille de validation & seuils paramétrables
Paliers décaissement (1 000 / 10 000 USD) ; délais d'avance (2 h / 24 h / 15 j…) ; créances (+7 j / +30 j) ; avance salaire (50 %) ; apurement GCK (15 j) / facture GCK (5 j).

### D. Acteurs nommés
Président · DG Arsène · DFI · Admin Huguette · DT Ruffin · Caissière centrale Eliane MUSOLO · Caissier-vendeur Patient KAPEND (Kolwezi) · Comptables : Raphael TSHIBWABWA (PLANET+GHR), Raphael KYUNGU (KAKO Likasi+HORIZON), Jacques MALIGIJA (DAKAM), Franck MUTWALE (KAKO Kolwezi+KAKO Logistique).

### E. Décisions de la Direction (arbitrées le 2026-06-22)
1. **Devise pivot = USD** ✅. Les opérations peuvent être saisies en USD ou en CDF ; la conversion se fait au **taux du jour, défini quotidiennement par le DFI** (table des taux journaliers). Les montants sont conservés dans la devise de saisie **et** en équivalent USD (pivot).
2. **Mode hors-ligne requis** ✅ : connexion instable selon les sites. Architecture conçue pour résister aux coupures avec synchronisation (modèle de données sync-friendly : identifiants UUID, horodatages, journal append-only). Le hors-ligne complet du POS sera traité en V2.
3. **Seuils « à définir par la DG »** ✅ : implémentés comme **paramètres configurables par société/rôle** (table `parametres`) ; valeurs chiffrées à fournir par la Direction.

### F. Questions encore ouvertes (n'empêchent pas de démarrer la V1)
4. **Reprise de données** : balances d'ouverture, plan comptable existant, en-cours d'avances/créances.
5. **Hébergement** : cloud (VPS) vs serveur local au siège de Likasi (à confirmer selon §3.3).
6. **Équipe & calendrier** de développement (interne/prestataire), budget.
