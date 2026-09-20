# Modèle de données — V1 (Le verrou financier)

> Schéma PostgreSQL : [`database/schema_v1.sql`](../database/schema_v1.sql) · Amorçage : [`database/seed_v1.sql`](../database/seed_v1.sql)
> Version 1.0 — 2026-06-22.

Ce document explique le modèle de données de la V1 et les conventions de conception. Le SQL est la source de vérité.

## 1. Périmètre couvert
Référentiel (sociétés, sites, organisation) · Utilisateurs/rôles/droits multi-société · Multi-devise (taux journalier) · Plan comptable / exercices / **clôture de période** · Tiers · **Décaissement & avances (G01→G04)** · Caisse & trésorerie (G05/G06/G08) · Écritures comptables OHADA · Paramètres/seuils configurables · **Audit immuable**.

## 2. Conventions structurantes (vos 3 décisions intégrées)

### 2.1 Synchronisation / hors-ligne
- **Clés primaires `UUID`** générées côté base (`gen_random_uuid()`) → permettent la création de pièces hors-ligne sur un site, sans collision d'identifiants, puis synchronisation.
- **`created_at` / `updated_at`** systématiques (déclencheurs `set_updated_at`) → résolution de conflits et réplication.
- **`audit_log` en append-only** (clé `BIGSERIAL`, jamais d'UPDATE/DELETE) → historique inaltérable même après resynchronisation.
- *Note* : la V1 fonctionne en serveur central ; la conception ci-dessus rend la couche de synchronisation hors-ligne (POS, réception) réalisable en V2 sans refonte du modèle.

### 2.2 Multi-devise (USD pivot, taux journalier du DFI)
- Table **`taux_change`** : le DFI saisit chaque jour le taux `1 USD = X CDF` (`taux_usd`), tracé (`defini_par`, `date_taux`).
- **Tout montant monétaire** est stocké dans sa **devise de saisie** (`devise`, `montant`) **et** en **équivalent USD** (`montant_usd`), avec le `taux_jour` appliqué.
  Conversion : `montant_usd = (devise='USD') ? montant : montant / taux_usd`.
- Les **écritures comptables sont tenues en USD pivot** (`ligne_ecriture.montant_usd`), la devise d'origine étant conservée pour la traçabilité (`devise_origine`, `montant_origine`, `taux_jour`).
- Les **paliers de validation s'évaluent sur l'équivalent USD** (`montant_autorise_usd`).

### 2.3 Seuils configurables
- Table **`parametre`** (clé/valeur, portée groupe si `societe_id IS NULL`, sinon par société) : tous les seuils et délais y sont stockés, y compris les 4 seuils « à définir par la DG » (valeur provisoire `0`, description `[À DÉFINIR PAR LA DG]`).
- Tables **`palier_validation`** + **`palier_approbateur`** : encodent la grille de validation de façon **paramétrable** (voir §4).

## 3. Le cœur : circuit de décaissement (mapping documents → tables)

| Document papier | Table(s) | Rôle |
|---|---|---|
| **G01** Réquisition | `requisition`, `requisition_ligne`, `requisition_fournisseur` | Demande de sortie de fonds |
| Validation demande / sortie | `validation` (journal générique multi-signataires) | Approbations, e-mail/in-app |
| **G02** Ordre de dépense | `ordre_depense`, `ordre_depense_ligne` | Autorisation de décaissement |
| **G03** Bon de réception de fonds | `bon_reception` | Remise effective des fonds |
| Avance (cycle de vie) | `avance` | Suivi de l'avance à justifier |
| **G04** Justification d'avance | `justification`, `justification_ligne` | Reddition de comptes |
| Blocage automatique | `blocage_beneficiaire` | Blocage si avance non justifiée |
| **G05** Journal de caisse | `mouvement_caisse` | Entrées/sorties USD & CDF |
| **G06** Cession de fonds | `cession_fonds` | Transfert entre caisses |
| **G08** Clôture de caisse | `cloture_caisse` | Comptage par coupures, écart |

### 3.1 Logique de blocage automatique (à coder dans le backend)
Avant d'octroyer une nouvelle avance à un bénéficiaire (`tiers`), le système vérifie :
1. Aucune ligne active dans `blocage_beneficiaire` (`actif = TRUE`) pour ce `tiers_id` ;
2. Aucune `avance` de ce bénéficiaire au statut `en_retard` ou `bloquante`.
Un traitement planifié passe les avances dont `echeance_justif < now()` et `statut='a_justifier'` au statut `en_retard`, crée la ligne `blocage_beneficiaire`, et notifie le DFI. **Seul le DFI** peut lever le blocage (`leve_par`, `leve_motif`).

### 3.2 Contrôle d'équilibre de la justification
À la soumission de `justification` : `ecart_usd = montant_avance_usd − (montant_justifie_usd + solde_retourne_usd)`.
- `ecart_usd = 0` → conforme ;
- `solde_retourne_usd > 0` → trop-perçu : l'avance ne se solde qu'après mouvement de caisse de retour ;
- dépenses > avance → `complement_demande = TRUE` → nouvelle réquisition de complément.

## 4. Moteur de validation paramétrable (grille amorcée)

Le `seed_v1.sql` configure la grille réelle du groupe :

**Sortie de fonds** (`type_document='ordre_depense'`, `etape='sortie_fonds'`) :
- ≤ 1 000 USD → **DFI** (seul)
- 1 001–10 000 USD → **DFI + DG + Admin + Président** (conjoints)
- > 10 000 USD → **Président** (seul)

**Validation de la demande** (`type_document='requisition'`, `etape='demande'`) :
- Standard groupe → **DG + Admin** (conjoints)
- **Exception HORIZON** (`societe_id` = HOR) → **DG + DT** (conjoints)

Ajouter/modifier une règle = insérer dans `palier_validation` + `palier_approbateur`, sans toucher au code. Une règle spécifique société (`societe_id` renseigné) **prime** sur la règle groupe (`societe_id NULL`).

## 5. Comptabilité & automatisation
- `schema_comptable` + `schema_comptable_ligne` : moteur de **schémas d'écritures paramétrables** (ex. `versement_avance` → D 4091 / C 57). Le backend instancie l'écriture (`ecriture` + `ligne_ecriture`) à partir du schéma et des montants.
- `periode` : verrouillage mensuel (statut `cloturee`) → le backend refuse toute écriture sur une période close.
- `solde_ouverture` : import des balances N-1.

## 6. Comment appliquer le schéma
```bash
# PostgreSQL 14+ (à installer sur le serveur)
createdb kilima_erp
psql -d kilima_erp -f database/schema_v1.sql
psql -d kilima_erp -f database/seed_v1.sql
```
> Non encore exécuté ici (PostgreSQL absent du poste). Ordre des dépendances et syntaxe vérifiés manuellement ; à exécuter sur l'environnement cible.

## 7. Points à confirmer
1. **KAKO = 1 société à 2 agences (Likasi, Kolwezi)** — modélisé ainsi (6 sociétés). Si KAKO Likasi et Kolwezi sont **juridiquement distinctes**, il faut 7 sociétés (impacte la consolidation et les transferts). **À trancher.**
2. Comptes comptables précis par caisse/banque (57x / 52x) et comptes auxiliaires des tiers.
3. Liste nominative des utilisateurs et leurs affectations société/rôle (pour amorçage).
