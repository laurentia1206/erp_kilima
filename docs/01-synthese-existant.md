# Synthèse de l'existant — Groupe KILIMA HOLDINGS

> Établie le 2026-06-22 à partir des documents déposés dans `entrants/` :
> manuels de procédures (6 sociétés), fiches de poste, notes de service,
> documents standardisés G01–G09, documents spécifiques, dashboard DFI, et le prototype `sysco_erp`.

## 0. Constat majeur : vous avez déjà un « ERP papier » mûr

Contrairement à ce que laissait penser l'échange ChatGPT, vous ne partez pas de zéro. Vous avez déjà :
- un **système documentaire standardisé complet** (G01–G09 + documents spécifiques codifiés) ;
- des **procédures écrites par société** avec règles, seuils et délais précis ;
- une **grille de validation des décaissements** claire et quasi uniforme ;
- un **prototype comptable OHADA fonctionnel** (`sysco_erp`) ;
- un **prototype de dashboard DFI** (suivi opérationnel quotidien) ;
- et vous utilisez **déjà Odoo** (déploiement par phases, module logistique prévu en « Phase 4 »).

Le travail n'est donc pas d'inventer un ERP, mais de **numériser et faire respecter automatiquement un système qui existe déjà sur papier/Excel**.

## 1. Périmètre du groupe (7 entités + caisse centrale)

| Entité | Métier | Stock ? | Particularité |
|---|---|---|---|
| **PLANET Sarl** | Distribution **à la commission** (chaux/gravier GCK) | Non | Ne reverse à GCK qu'**après encaissement client**, au prorata |
| **DAKAM Sarl** | Achat/revente ciment en gros | Non (stock chez GCK) | 2 circuits de vente, n° commande GCK obligatoire ; entité « stratégique » |
| **KAKO Sarl — Likasi** | Quincaillerie + ciment détail | Oui (papier+Excel) | Retail + Business |
| **KAKO Sarl — Kolwezi** | Idem | Oui (système IT) | Caissier = vendeur → contrôle hebdo obligatoire |
| **KAKO Logistique** | Transport (15 camions) | Non | Avance carburant vérifiée au réservoir, jamais en espèces |
| **Ets HORIZON** | Location d'engins miniers | Non | Facturation mensuelle sur fiches de prestation ; validation demande DG+DT |
| **Guest House Relax** | Hôtel + resto + bar | Boissons seulement | Reçus manuels → régularisation DGI quotidienne ; contrôle cuisine par ratio |
| **Caisse centrale** | Eliane MUSOLO | — | Encaisse/décaisse pour **toutes** les sociétés |

Structure financière **très centralisée** : tout converge vers le **DFI** (vous). Tous les comptables et caissiers reportent au DFI. Plusieurs comptables gèrent 2 sociétés.

## 2. La colonne vertébrale : circuit de décaissement (documents G01→G04)

C'est le cœur du système et la vraie douleur à automatiser.

```
G01 Réquisition  →  Validation demande (e-mail)  →  G02 Ordre de Dépense  →
G03 Bon de Réception de Fonds  →  Exécution/achat  →  G04 Justification d'avance  →
Retour solde  →  Comptabilisation
```

- **G01 Requisition Form** : N°, entité, département, priorité (Normal/Urgent/Top Urgent), lignes (imputation, article, qté, PU, total), total **USD/CDF**, 3 fournisseurs suggérés.
- **G02 Ordre de Dépense** : autorisation de décaissement, réf G01, imputations comptables, montant USD/CDF, montant en lettres, **paliers de validation** (voir §3), signatures Caissier/DFI/Bénéficiaire.
- **G03 Bon de Réception de Fonds** : accusé du bénéficiaire, mode Caisse/Banque.
- **G04 Fiche de Justification d'Avance** : avance reçue, lignes de dépense + reçus, total justifié, **solde non utilisé retourné**, contrôle **Avance = Dépenses + Solde** (OK / ÉCART).

Documents de caisse/contrôle : **G05** journal de caisse journalier (USD+CDF, écart théorique/physique), **G06** bordereau de cession entre caisses, **G07** suivi des créances (escalade DG à +30j), **G08** clôture de caisse (comptage par coupures), **G09** réconciliation mensuelle (Budget/Réalisé/Écart + rapprochements OHADA 51/52/57/425/467).

## 3. Règles de gestion automatisables (les vraies, chiffrées)

**Grille de validation des décaissements** (identique pour 5 sociétés sur 6) :

| Palier (USD) | Approbateurs sortie de fonds |
|---|---|
| ≤ 1 000 | DFI seul |
| 1 001 – 10 000 | DFI + DG Arsène + Admin Huguette + Président (conjoints) |
| > 10 000 | Président seul |

**Deux validations distinctes** : (1) validation de la *demande* — standard DG + Admin Huguette ; **HORIZON = DG + DT Ruffin** (technique) ; (2) validation de la *sortie de fonds* selon la grille. La validation **e-mail fait foi**.

**Avances à justifier** :
- Délais : **2h** (course camion KAKO Log., achats marché GHR) · **24h** (pièces/maintenance, boissons, divers) · lendemain matin (chauffeurs) · fin de mois (forfait entretien GHR).
- Contrôle d'équilibre : **Avance = Dépenses justifiées + Solde retourné**.
- **Blocage automatique** : toute avance non justifiée dans les délais ⇒ blocage de toute nouvelle avance au bénéficiaire jusqu'à régularisation (levée possible par le DFI).

**Autres règles** : créances escalade DG à **+30j**, relance à **+7j** ; écart de caisse ≠ 0 ⇒ signalement DFI immédiat ; apurement avance GCK ≤ **15j** (alerte 10j), facture GCK ≤ **5j** (DAKAM) ; avance sur salaire chauffeur plafond **50%** ; état de paie chauffeurs > 10 000 USD ⇒ Président.

**Seuils « à définir par la DG »** (trous à combler, à rendre paramétrables) : seuil d'écart de caisse à escalader, ratio cible cuisine GHR, seuil d'écart d'inventaire, seuil commande importante DAKAM.

## 4. Multi-devise USD/CDF — natif, au niveau ligne

Quasiment **tous** les documents ont des colonnes doublées **Montant USD + Montant CDF** (G01–G06, G08, journaux, registres ventes, comptage par coupures). L'ERP doit être **bi-devise au niveau de chaque ligne**, pas seulement au total. Seuils de validation libellés en USD.

## 5. Tableau de bord DFI — pilotage opérationnel quotidien

Ce n'est **pas** un dashboard comptable, mais un **outil de conformité quotidienne** :
- **33 tâches journalières** attendues (par entité, responsable, heure limite) avec statut OK/RETARD/ANOMALIE/MANQUANT/EN ATTENTE/N-A, et **taux de conformité**.
- Suivi hebdomadaire : 9 rapports du lundi + 12 points de contrôle (réconciliations, inventaires, ratio cuisine, avances apurées, créances >7j, ratio maintenance HORIZON).
- **Avances en cours** : encours USD, retards, bloquées.
- **Actions & relances DFI** : journal de traçabilité.
- Cadence type : 17h30 caisses → 18h00 statuts → 18h30 relances → 19h00 vue complète + rapport DG.

## 6. Matrice des rôles (déduite des fiches de poste & notes)

| Rôle ERP | Pouvoir |
|---|---|
| **Président** | Validation paliers > 10 000 ; co-signataire 1 001–10 000 ; fixe les plafonds |
| **DG (Arsène)** | Supervision groupe ; validation finale ; co-signataire ; valide la *demande* |
| **DFI (vous)** | **Autorise les sorties de fonds** ; valide paiements/achats/avances ; reçoit escalades ; supérieur unique des comptables/caissiers ; accès toutes sociétés |
| **Admin (Huguette)** | Co-validation demande + palier 1 001–10 000 |
| **DT (Ruffin)** | Co-validation des demandes techniques (HORIZON) |
| **Comptable (par société)** | Saisie compta, prépare/exécute paiements, réconciliations, états, fiscalité — **limité à ses sociétés** |
| **Caissier central (Eliane)** | Encaisse/décaisse **uniquement sur ordre validé** ; tient journaux ; ne décide jamais |
| **Caissier+Vendeur (Patient)** | Caisse + vente comptoir + facturation cash ; contrôle hebdo indépendant obligatoire |
| **Resp. Inventaire & IT** | Contrôle physique caisse hebdo + signe PV ; inventaire ; IT local |
| **Assistant technique** | Saisie fiches course / prestations |

**Séparation des tâches à câbler en dur** : créer la réquisition (DFI/acheteur) ≠ exécuter le décaissement (caissier) ≠ comptabiliser (comptable) ≠ contrôler (resp. inventaire). Interdire l'auto-validation (cas Eliane « seule à vérifier sa propre caisse »).

## 7. État du prototype `sysco_erp`

**À garder (vraie valeur intellectuelle)** : la logique comptable OHADA — validation D=C, calcul de balance avec audit automatique des anomalies par nature de compte, TFT méthode indirecte SYSCOHADA, KPI. Le frontend donne une bonne maquette d'UX.

**À refondre (la stack n'est pas production-ready)** :
1. **Aucune authentification** — tables `users`/`user_tenants` présentes mais jamais branchées ; API ouverte (CORS `*`).
2. **Isolation tenant non sécurisée** — le tenant est un simple entier dans l'URL : n'importe qui lit/écrit n'importe quelle société.
3. **Intégrité transactionnelle** — création d'écriture non atomique ; SQLite mono-écrivain inadapté au multi-utilisateur concurrent.
4. **Logique d'états dispersée** — Bilan/Résultat calculés en JavaScript côté front, non auditables.
5. Aucune table pour réquisitions/avances/workflow/multi-devise au niveau ligne.

Le **dashboard DFI** (`KILIMA_DFI_Dashboard_4.html`) est un **second produit autonome** (données en `localStorage`, un seul poste), à connecter à un vrai backend.

## 8. Fait stratégique : vous utilisez déjà Odoo

Les notes de service mentionnent un **plan de restructuration avec déploiement Odoo par phases** (module logistique en Phase 4). Cela ouvre une question d'architecture majeure — voir [02-strategie-make-or-buy.md](02-strategie-make-or-buy.md).
