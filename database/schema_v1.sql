-- =====================================================================
--  ERP GROUPE KILIMA HOLDINGS — SCHÉMA BASE DE DONNÉES (V1)
--  SGBD : PostgreSQL 14+
--  Périmètre V1 : Référentiel · Multi-devise · Compta OHADA ·
--                 Décaissement & avances · Caisse/Trésorerie · Audit
--  Conventions :
--    - Clés primaires UUID (synchronisation multi-site / hors-ligne)
--    - Horodatage created_at / updated_at sur les tables mutables
--    - Aucune suppression physique des données financières (statuts + audit)
--    - Devise pivot = USD. Tout montant est stocké dans sa devise de saisie
--      ET en équivalent USD (montant_usd), au taux du jour fixé par le DFI.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- Fonction générique de mise à jour de updated_at
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- 1. RÉFÉRENTIEL — SOCIÉTÉS, SITES, ORGANISATION
-- =====================================================================

CREATE TABLE societe (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code          TEXT NOT NULL UNIQUE,          -- PLA, DAK, KAL, KAK, KLO, HOR, GHR
    nom           TEXT NOT NULL,
    rccm          TEXT,
    id_nat        TEXT,
    nif           TEXT,
    adresse       TEXT,
    ville         TEXT DEFAULT 'Likasi',
    pays          TEXT DEFAULT 'RDC',
    devise_tenue  TEXT NOT NULL DEFAULT 'USD',   -- devise pivot
    referentiel   TEXT NOT NULL DEFAULT 'SYSCOHADA',
    actif         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE site (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id  UUID NOT NULL REFERENCES societe(id),
    code        TEXT NOT NULL,
    nom         TEXT NOT NULL,
    ville       TEXT,
    actif       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(societe_id, code)
);

CREATE TABLE departement (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id  UUID NOT NULL REFERENCES societe(id),
    nom         TEXT NOT NULL,
    actif       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE centre_cout (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id  UUID NOT NULL REFERENCES societe(id),
    code        TEXT NOT NULL,
    nom         TEXT NOT NULL,
    actif       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(societe_id, code)
);

-- =====================================================================
-- 2. UTILISATEURS, RÔLES, DROITS (multi-société)
-- =====================================================================

CREATE TABLE role (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code     TEXT NOT NULL UNIQUE,   -- PRESIDENT, DG, DFI, ADMIN, DT, COMPTABLE, CAISSIER, ...
    libelle  TEXT NOT NULL,
    niveau   INTEGER NOT NULL DEFAULT 0   -- pour le tri hiérarchique des validations
);

CREATE TABLE utilisateur (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT NOT NULL UNIQUE,
    nom            TEXT NOT NULL,
    prenom         TEXT,
    password_hash  TEXT NOT NULL,
    telephone      TEXT,             -- notifications WhatsApp/SMS
    actif          BOOLEAN NOT NULL DEFAULT TRUE,
    last_login     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Affectation d'un utilisateur à une société avec un rôle (un comptable peut gérer 2 sociétés)
CREATE TABLE utilisateur_societe (
    utilisateur_id  UUID NOT NULL REFERENCES utilisateur(id) ON DELETE CASCADE,
    societe_id      UUID NOT NULL REFERENCES societe(id) ON DELETE CASCADE,
    role_id         UUID NOT NULL REFERENCES role(id),
    site_id         UUID REFERENCES site(id),   -- optionnel : restriction au site
    PRIMARY KEY (utilisateur_id, societe_id, role_id)
);

-- =====================================================================
-- 3. MULTI-DEVISE — TAUX DE CHANGE JOURNALIER (fixé par le DFI)
-- =====================================================================

CREATE TABLE taux_change (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date_taux     DATE NOT NULL,
    devise        TEXT NOT NULL DEFAULT 'CDF',   -- devise non-pivot
    -- 1 USD = <taux_usd_vers_devise> CDF (ex. 2800)
    taux_usd      NUMERIC(18,6) NOT NULL CHECK (taux_usd > 0),
    defini_par    UUID NOT NULL REFERENCES utilisateur(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(date_taux, devise)
);
-- Conversion : montant_usd = (devise='USD') ? montant : montant / taux_usd

-- =====================================================================
-- 4. COMPTABILITÉ — PLAN DE COMPTE, EXERCICES, PÉRIODES, JOURNAUX
-- =====================================================================

CREATE TABLE compte (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id  UUID NOT NULL REFERENCES societe(id),
    numero      TEXT NOT NULL,
    intitule    TEXT NOT NULL,
    classe      TEXT,
    categorie   TEXT,
    sens_ohada  TEXT,         -- debiteur / crediteur
    rubrique    TEXT,
    auxiliaire  BOOLEAN NOT NULL DEFAULT FALSE,   -- comptes 401/411/4091/425/467...
    actif       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(societe_id, numero)
);
CREATE INDEX idx_compte_societe ON compte(societe_id, numero);

CREATE TABLE exercice (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id  UUID NOT NULL REFERENCES societe(id),
    annee       INTEGER NOT NULL,
    date_debut  DATE NOT NULL,
    date_fin    DATE NOT NULL,
    statut      TEXT NOT NULL DEFAULT 'ouvert' CHECK (statut IN ('ouvert','clos')),
    UNIQUE(societe_id, annee)
);

-- Verrouillage des périodes (clôture mensuelle) — interdit l'antidatage
CREATE TABLE periode (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exercice_id  UUID NOT NULL REFERENCES exercice(id),
    mois         INTEGER NOT NULL CHECK (mois BETWEEN 1 AND 12),
    statut       TEXT NOT NULL DEFAULT 'ouverte' CHECK (statut IN ('ouverte','cloturee')),
    cloture_par  UUID REFERENCES utilisateur(id),
    cloture_at   TIMESTAMPTZ,
    UNIQUE(exercice_id, mois)
);

CREATE TABLE journal (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id      UUID NOT NULL REFERENCES societe(id),
    code            TEXT NOT NULL,   -- VT, AC, BQ, CA, OD, AN
    libelle         TEXT NOT NULL,
    type            TEXT NOT NULL,
    compte_default  TEXT,
    actif           BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(societe_id, code)
);

-- =====================================================================
-- 5. TIERS (clients, fournisseurs, agents bénéficiaires d'avances)
-- =====================================================================

CREATE TABLE tiers (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id         UUID REFERENCES societe(id),     -- NULL = tiers groupe partagé
    type               TEXT NOT NULL CHECK (type IN ('client','fournisseur','agent')),
    code               TEXT NOT NULL,
    nom                TEXT NOT NULL,
    compte_auxiliaire  TEXT,           -- compte OHADA rattaché (411x, 401x, 4091x, 425/467)
    utilisateur_id     UUID REFERENCES utilisateur(id), -- si l'agent est un utilisateur
    intra_groupe       BOOLEAN NOT NULL DEFAULT FALSE,
    societe_liee_id    UUID REFERENCES societe(id),      -- si intra_groupe : société du groupe
    limite_credit_usd  NUMERIC(18,2),
    conditions_paiement TEXT,
    actif              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(societe_id, type, code)
);

-- =====================================================================
-- 6. PARAMÈTRES & RÈGLES DE VALIDATION (configurables)
-- =====================================================================

-- Paramètres clé/valeur (seuils « à définir par la DG », délais par défaut, etc.)
CREATE TABLE parametre (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id   UUID REFERENCES societe(id),   -- NULL = paramètre global groupe
    cle          TEXT NOT NULL,
    valeur       TEXT NOT NULL,
    type_valeur  TEXT NOT NULL DEFAULT 'number' CHECK (type_valeur IN ('number','text','bool','json')),
    description  TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by   UUID REFERENCES utilisateur(id),
    UNIQUE(societe_id, cle)
);

-- Paliers de validation des décaissements (grille paramétrable par société/type de document)
CREATE TABLE palier_validation (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id     UUID REFERENCES societe(id),    -- NULL = règle groupe par défaut
    type_document  TEXT NOT NULL,                  -- 'ordre_depense' (sortie de fonds), 'requisition' (demande)
    etape          TEXT NOT NULL,                  -- 'demande' ou 'sortie_fonds'
    montant_min_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
    montant_max_usd NUMERIC(18,2),                 -- NULL = pas de plafond
    libelle        TEXT,
    ordre          INTEGER NOT NULL DEFAULT 0
);

-- Approbateurs requis pour un palier (multi-signataires : mode conjoint ou seul)
CREATE TABLE palier_approbateur (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    palier_id   UUID NOT NULL REFERENCES palier_validation(id) ON DELETE CASCADE,
    role_id     UUID NOT NULL REFERENCES role(id),
    mode        TEXT NOT NULL DEFAULT 'conjoint' CHECK (mode IN ('conjoint','seul')),
    ordre       INTEGER NOT NULL DEFAULT 0
);

-- Compteurs de séquences (numérotation REQ-PLA-2026-000125, AVJ-2026-..., etc.)
CREATE TABLE sequence_compteur (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id      UUID REFERENCES societe(id),
    type_piece      TEXT NOT NULL,    -- REQ, ODP, BRF, AVJ, JUST, CES
    annee           INTEGER NOT NULL,
    dernier_numero  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(societe_id, type_piece, annee)
);

-- =====================================================================
-- 7. PIÈCES JOINTES (devis, proformas, reçus, photos)
-- =====================================================================

CREATE TABLE piece_jointe (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_type   TEXT NOT NULL,    -- 'requisition','justification','justification_ligne',...
    document_id     UUID NOT NULL,
    nom_fichier     TEXT NOT NULL,
    chemin_stockage TEXT NOT NULL,
    mime_type       TEXT,
    taille_octets   BIGINT,
    uploaded_by     UUID REFERENCES utilisateur(id),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pj_document ON piece_jointe(document_type, document_id);

-- =====================================================================
-- 7bis. CAISSES & COMPTES BANCAIRES
--   (définis ici car référencés par le décaissement ; détail tréso §9)
-- =====================================================================

CREATE TABLE caisse (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id         UUID NOT NULL REFERENCES societe(id),
    site_id            UUID REFERENCES site(id),
    libelle            TEXT NOT NULL,
    compte_comptable   TEXT,          -- 57x
    responsable_id     UUID REFERENCES utilisateur(id),
    actif              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE compte_bancaire (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id        UUID NOT NULL REFERENCES societe(id),
    banque            TEXT NOT NULL,
    numero_compte     TEXT,
    devise            TEXT NOT NULL DEFAULT 'USD',
    compte_comptable  TEXT,           -- 52x
    actif             BOOLEAN NOT NULL DEFAULT TRUE
);

-- =====================================================================
-- 8. DÉCAISSEMENT & AVANCES À JUSTIFIER  (cœur de la V1)
--    G01 Réquisition → G02 Ordre de dépense → G03 Bon de réception →
--    Avance → G04 Justification
-- =====================================================================

-- G01 — RÉQUISITION
CREATE TABLE requisition (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero          TEXT NOT NULL UNIQUE,             -- REQ-PLA-2026-000125
    societe_id      UUID NOT NULL REFERENCES societe(id),
    site_id         UUID REFERENCES site(id),
    departement_id  UUID REFERENCES departement(id),
    centre_cout_id  UUID REFERENCES centre_cout(id),
    initiateur_id   UUID NOT NULL REFERENCES utilisateur(id),
    date_requisition DATE NOT NULL DEFAULT CURRENT_DATE,
    objet           TEXT NOT NULL,
    justification   TEXT,
    mode_decaissement TEXT NOT NULL DEFAULT 'avance' CHECK (mode_decaissement IN ('avance','paiement_direct')),
    priorite        TEXT NOT NULL DEFAULT 'normal' CHECK (priorite IN ('normal','urgent','top_urgent')),
    devise          TEXT NOT NULL DEFAULT 'USD',
    taux_jour       NUMERIC(18,6),                    -- taux utilisé si devise=CDF
    montant_total   NUMERIC(18,2) NOT NULL DEFAULT 0,
    montant_total_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
    statut          TEXT NOT NULL DEFAULT 'brouillon'
                    CHECK (statut IN ('brouillon','soumise','demande_validee','rejetee',
                                      'en_attente_info','transformee','cloturee')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_requisition_societe ON requisition(societe_id, statut);

CREATE TABLE requisition_ligne (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requisition_id  UUID NOT NULL REFERENCES requisition(id) ON DELETE CASCADE,
    ordre           INTEGER NOT NULL DEFAULT 0,
    compte_impute   TEXT,
    code_article    TEXT,
    description     TEXT NOT NULL,
    unite           TEXT,
    quantite        NUMERIC(18,3) NOT NULL DEFAULT 1,
    prix_unitaire   NUMERIC(18,2) NOT NULL DEFAULT 0,
    montant         NUMERIC(18,2) NOT NULL DEFAULT 0,
    devise          TEXT NOT NULL DEFAULT 'USD',
    montant_usd     NUMERIC(18,2) NOT NULL DEFAULT 0
);

-- 3 fournisseurs suggérés (G01)
CREATE TABLE requisition_fournisseur (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requisition_id  UUID NOT NULL REFERENCES requisition(id) ON DELETE CASCADE,
    tiers_id        UUID REFERENCES tiers(id),
    nom_libre       TEXT,             -- si fournisseur hors base
    rang            INTEGER NOT NULL DEFAULT 1
);

-- Fil d'échange sur une réquisition (renvoi pour précisions, réponses)
CREATE TABLE requisition_commentaire (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requisition_id UUID NOT NULL REFERENCES requisition(id) ON DELETE CASCADE,
    auteur_id      UUID NOT NULL REFERENCES utilisateur(id),
    type           TEXT NOT NULL DEFAULT 'commentaire',  -- precision_demandee | reponse | commentaire
    message        TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_req_comm ON requisition_commentaire(requisition_id);

-- VALIDATIONS / APPROBATIONS — journal générique multi-signataires
-- Sert à la validation de la DEMANDE (requisition) et de la SORTIE DE FONDS (ordre_depense)
CREATE TABLE validation (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_type   TEXT NOT NULL,    -- 'requisition' | 'ordre_depense' | 'justification'
    document_id     UUID NOT NULL,
    etape           TEXT NOT NULL,    -- 'demande' | 'sortie_fonds' | 'controle'
    palier_id       UUID REFERENCES palier_validation(id),
    role_attendu_id UUID REFERENCES role(id),
    utilisateur_id  UUID REFERENCES utilisateur(id),
    decision        TEXT NOT NULL DEFAULT 'en_attente'
                    CHECK (decision IN ('en_attente','valide','rejete')),
    mode            TEXT NOT NULL DEFAULT 'conjoint' CHECK (mode IN ('conjoint','seul')),
    commentaire     TEXT,
    canal           TEXT,             -- 'in_app' | 'email' (la validation e-mail fait foi)
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_validation_document ON validation(document_type, document_id);
CREATE INDEX idx_validation_attente ON validation(utilisateur_id, decision);

-- G02 — ORDRE DE DÉPENSE (autorisation de décaissement)
CREATE TABLE ordre_depense (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero              TEXT NOT NULL UNIQUE,         -- ODP-PLA-2026-000087
    requisition_id      UUID NOT NULL REFERENCES requisition(id),
    societe_id          UUID NOT NULL REFERENCES societe(id),
    beneficiaire_tiers_id UUID NOT NULL REFERENCES tiers(id),
    motif               TEXT,
    mode_paiement       TEXT NOT NULL DEFAULT 'caisse' CHECK (mode_paiement IN ('caisse','banque')),
    mode_decaissement   TEXT NOT NULL DEFAULT 'avance' CHECK (mode_decaissement IN ('avance','paiement_direct')),
    devise              TEXT NOT NULL DEFAULT 'USD',
    taux_jour           NUMERIC(18,6),
    montant_autorise    NUMERIC(18,2) NOT NULL,
    montant_autorise_usd NUMERIC(18,2) NOT NULL,
    montant_lettres     TEXT,
    palier_applique     TEXT,         -- info : palier déterminé (<=1000 / 1001-10000 / >10000)
    statut              TEXT NOT NULL DEFAULT 'a_valider'
                        CHECK (statut IN ('a_valider','valide','transmis_caisse','execute','paye','rejete','cloture')),
    created_by          UUID REFERENCES utilisateur(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ordre_depense_ligne (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ordre_depense_id  UUID NOT NULL REFERENCES ordre_depense(id) ON DELETE CASCADE,
    compte_impute     TEXT NOT NULL,
    libelle           TEXT,
    montant           NUMERIC(18,2) NOT NULL,
    devise            TEXT NOT NULL DEFAULT 'USD',
    montant_usd       NUMERIC(18,2) NOT NULL
);

-- G03 — BON DE RÉCEPTION DE FONDS
CREATE TABLE bon_reception (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero            TEXT NOT NULL UNIQUE,           -- BRF-PLA-2026-000087
    ordre_depense_id  UUID NOT NULL REFERENCES ordre_depense(id),
    caisse_id         UUID REFERENCES caisse(id),
    compte_bancaire_id UUID REFERENCES compte_bancaire(id),
    receveur_tiers_id UUID NOT NULL REFERENCES tiers(id),
    caissier_id       UUID NOT NULL REFERENCES utilisateur(id),
    date_reception    TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode              TEXT NOT NULL DEFAULT 'caisse' CHECK (mode IN ('caisse','banque')),
    devise            TEXT NOT NULL DEFAULT 'USD',
    taux_jour         NUMERIC(18,6),
    montant           NUMERIC(18,2) NOT NULL,
    montant_usd       NUMERIC(18,2) NOT NULL,
    montant_lettres   TEXT,
    statut            TEXT NOT NULL DEFAULT 'emis' CHECK (statut IN ('emis','annule'))
);

-- AVANCE (cycle de vie de l'avance à justifier, alimentée à la remise des fonds)
CREATE TABLE avance (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero              TEXT NOT NULL UNIQUE,         -- AVJ-2026-000125
    ordre_depense_id    UUID NOT NULL REFERENCES ordre_depense(id),
    bon_reception_id    UUID REFERENCES bon_reception(id),
    beneficiaire_tiers_id UUID NOT NULL REFERENCES tiers(id),
    societe_id          UUID NOT NULL REFERENCES societe(id),
    type_avance         TEXT,         -- course, marche, pieces, boissons, forfait, gck...
    devise              TEXT NOT NULL DEFAULT 'USD',
    montant_avance      NUMERIC(18,2) NOT NULL,
    montant_avance_usd  NUMERIC(18,2) NOT NULL,
    date_octroi         TIMESTAMPTZ NOT NULL DEFAULT now(),
    delai_justif_heures INTEGER,      -- 2, 24, ... (copié du paramètre selon type)
    echeance_justif     TIMESTAMPTZ,  -- date_octroi + délai
    statut              TEXT NOT NULL DEFAULT 'a_justifier'
                        CHECK (statut IN ('a_justifier','justifiee','validee','comptabilisee',
                                          'en_retard','bloquante','soldee')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_avance_beneficiaire ON avance(beneficiaire_tiers_id, statut);
CREATE INDEX idx_avance_echeance ON avance(echeance_justif, statut);

-- G04 — JUSTIFICATION D'AVANCE
CREATE TABLE justification (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero               TEXT NOT NULL UNIQUE,
    avance_id            UUID NOT NULL REFERENCES avance(id),
    date_justification   DATE NOT NULL DEFAULT CURRENT_DATE,
    montant_justifie     NUMERIC(18,2) NOT NULL DEFAULT 0,
    montant_justifie_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
    solde_retourne       NUMERIC(18,2) NOT NULL DEFAULT 0,   -- trop-perçu rendu en caisse
    solde_retourne_usd   NUMERIC(18,2) NOT NULL DEFAULT 0,
    -- Contrôle d'équilibre : avance = justifié + solde retourné (+/- ecart)
    ecart_usd            NUMERIC(18,2) NOT NULL DEFAULT 0,
    complement_demande   BOOLEAN NOT NULL DEFAULT FALSE,     -- avance < dépenses
    statut               TEXT NOT NULL DEFAULT 'soumise'
                         CHECK (statut IN ('soumise','validee','rejetee')),
    validee_par          UUID REFERENCES utilisateur(id),
    validee_at           TIMESTAMPTZ,
    created_by           UUID REFERENCES utilisateur(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE justification_ligne (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    justification_id  UUID NOT NULL REFERENCES justification(id) ON DELETE CASCADE,
    date_achat        DATE,
    nature            TEXT NOT NULL,
    compte_impute     TEXT,
    fournisseur       TEXT,
    num_piece         TEXT,           -- n° reçu / facture
    devise            TEXT NOT NULL DEFAULT 'USD',
    montant           NUMERIC(18,2) NOT NULL,
    montant_usd       NUMERIC(18,2) NOT NULL,
    a_piece_jointe    BOOLEAN NOT NULL DEFAULT FALSE
);

-- BLOCAGE AUTOMATIQUE des bénéficiaires (avance non justifiée / solde non rendu)
CREATE TABLE blocage_beneficiaire (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tiers_id      UUID NOT NULL REFERENCES tiers(id),
    avance_id     UUID REFERENCES avance(id),
    motif         TEXT NOT NULL,
    actif         BOOLEAN NOT NULL DEFAULT TRUE,
    bloque_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    leve_par      UUID REFERENCES utilisateur(id),   -- DFI uniquement
    leve_motif    TEXT,
    leve_at       TIMESTAMPTZ
);
CREATE INDEX idx_blocage_tiers ON blocage_beneficiaire(tiers_id, actif);

-- =====================================================================
-- 9. CAISSE & TRÉSORERIE  (caisse/compte_bancaire définis en §7bis)
-- =====================================================================

-- G05 — mouvements du journal de caisse (entrées/sorties USD & CDF)
CREATE TABLE mouvement_caisse (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caisse_id          UUID NOT NULL REFERENCES caisse(id),
    date_mouvement     DATE NOT NULL DEFAULT CURRENT_DATE,
    heure              TIMESTAMPTZ NOT NULL DEFAULT now(),
    sens               TEXT NOT NULL CHECK (sens IN ('entree','sortie')),
    nature             TEXT NOT NULL,
    devise             TEXT NOT NULL DEFAULT 'USD',
    taux_jour          NUMERIC(18,6),
    montant            NUMERIC(18,2) NOT NULL CHECK (montant > 0),
    montant_usd        NUMERIC(18,2) NOT NULL,
    reference_type     TEXT,          -- 'bon_reception','justification','cession',...
    reference_id       UUID,
    libelle            TEXT,
    created_by         UUID REFERENCES utilisateur(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mvt_caisse ON mouvement_caisse(caisse_id, date_mouvement);

-- G08 — clôture de caisse (comptage par coupures)
CREATE TABLE cloture_caisse (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caisse_id           UUID NOT NULL REFERENCES caisse(id),
    date_cloture        DATE NOT NULL,
    solde_theorique_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
    solde_theorique_cdf NUMERIC(18,2) NOT NULL DEFAULT 0,
    solde_physique_usd  NUMERIC(18,2) NOT NULL DEFAULT 0,
    solde_physique_cdf  NUMERIC(18,2) NOT NULL DEFAULT 0,
    ecart_usd           NUMERIC(18,2) NOT NULL DEFAULT 0,
    ecart_cdf           NUMERIC(18,2) NOT NULL DEFAULT 0,
    detail_comptage     JSONB,        -- {"USD":{"100":3,...},"CDF":{...}}
    commentaire         TEXT,
    cloture_par         UUID REFERENCES utilisateur(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(caisse_id, date_cloture)
);

-- G06 — cession de fonds entre caisses (vers caisse centrale)
CREATE TABLE cession_fonds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero          TEXT NOT NULL UNIQUE,
    caisse_source_id UUID NOT NULL REFERENCES caisse(id),
    caisse_dest_id  UUID NOT NULL REFERENCES caisse(id),
    date_cession    DATE NOT NULL DEFAULT CURRENT_DATE,
    montant_usd     NUMERIC(18,2) NOT NULL DEFAULT 0,
    montant_cdf     NUMERIC(18,2) NOT NULL DEFAULT 0,
    detail          JSONB,
    cedant_id       UUID REFERENCES utilisateur(id),
    receveur_id     UUID REFERENCES utilisateur(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- 10. COMPTABILITÉ — ÉCRITURES (partie double, tenue en USD pivot)
-- =====================================================================

CREATE TABLE schema_comptable (   -- moteur de schémas paramétrable
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id     UUID REFERENCES societe(id),   -- NULL = schéma groupe
    type_operation TEXT NOT NULL,                 -- 'versement_avance','justification_achat',...
    libelle        TEXT NOT NULL,
    actif          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE schema_comptable_ligne (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_id       UUID NOT NULL REFERENCES schema_comptable(id) ON DELETE CASCADE,
    sens            TEXT NOT NULL CHECK (sens IN ('D','C')),
    compte_param    TEXT NOT NULL,   -- n° de compte ou variable (ex. {compte_charge})
    ordre           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ecriture (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id      UUID NOT NULL REFERENCES societe(id),
    exercice_id     UUID NOT NULL REFERENCES exercice(id),
    periode_id      UUID REFERENCES periode(id),
    journal_id      UUID REFERENCES journal(id),
    numero          TEXT NOT NULL,
    date_ecriture   DATE NOT NULL,
    numero_piece    TEXT,
    libelle         TEXT NOT NULL,
    type_operation  TEXT,
    source_type     TEXT,            -- 'ordre_depense','justification','cession',...
    source_id       UUID,
    statut          TEXT NOT NULL DEFAULT 'valide' CHECK (statut IN ('brouillon','valide')),
    created_by      UUID REFERENCES utilisateur(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ecriture_societe ON ecriture(societe_id, exercice_id);
CREATE INDEX idx_ecriture_date ON ecriture(date_ecriture);

CREATE TABLE ligne_ecriture (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ecriture_id    UUID NOT NULL REFERENCES ecriture(id) ON DELETE CASCADE,
    societe_id     UUID NOT NULL REFERENCES societe(id),
    ordre          INTEGER NOT NULL DEFAULT 0,
    sens           TEXT NOT NULL CHECK (sens IN ('D','C')),
    compte_numero  TEXT NOT NULL,
    tiers_id       UUID REFERENCES tiers(id),
    -- Tenue en USD pivot ; devise d'origine conservée pour la traçabilité
    montant_usd    NUMERIC(18,2) NOT NULL CHECK (montant_usd > 0),
    devise_origine TEXT NOT NULL DEFAULT 'USD',
    montant_origine NUMERIC(18,2),
    taux_jour      NUMERIC(18,6),
    libelle_ligne  TEXT,
    lettrage_code  TEXT             -- rapprochement auxiliaire
);
CREATE INDEX idx_ligne_ecr ON ligne_ecriture(ecriture_id);
CREATE INDEX idx_ligne_compte ON ligne_ecriture(societe_id, compte_numero);
CREATE INDEX idx_ligne_lettrage ON ligne_ecriture(lettrage_code);

-- Soldes d'ouverture (import balance N-1)
CREATE TABLE solde_ouverture (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    societe_id     UUID NOT NULL REFERENCES societe(id),
    exercice_id    UUID NOT NULL REFERENCES exercice(id),
    compte_numero  TEXT NOT NULL,
    si_debit_usd   NUMERIC(18,2) NOT NULL DEFAULT 0,
    si_credit_usd  NUMERIC(18,2) NOT NULL DEFAULT 0,
    source         TEXT DEFAULT 'manuel',
    UNIQUE(societe_id, exercice_id, compte_numero)
);

-- =====================================================================
-- 11. AUDIT & TRAÇABILITÉ (journal immuable — append only)
-- =====================================================================

CREATE TABLE audit_log (
    id               BIGSERIAL PRIMARY KEY,
    utilisateur_id   UUID REFERENCES utilisateur(id),
    action           TEXT NOT NULL,        -- INSERT / UPDATE / VALIDATE / REJECT / LOGIN ...
    table_cible      TEXT NOT NULL,
    enregistrement_id TEXT,
    ancienne_valeur  JSONB,
    nouvelle_valeur  JSONB,
    adresse_ip       TEXT,
    horodatage       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_cible ON audit_log(table_cible, enregistrement_id);
CREATE INDEX idx_audit_user ON audit_log(utilisateur_id, horodatage);
-- Aucune mise à jour/suppression autorisée applicativement (révoquer UPDATE/DELETE en prod).

-- =====================================================================
-- 12. TRIGGERS updated_at
-- =====================================================================
CREATE TRIGGER trg_societe_upd      BEFORE UPDATE ON societe       FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_utilisateur_upd  BEFORE UPDATE ON utilisateur   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_tiers_upd        BEFORE UPDATE ON tiers         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_requisition_upd  BEFORE UPDATE ON requisition   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_ordre_dep_upd    BEFORE UPDATE ON ordre_depense FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_avance_upd       BEFORE UPDATE ON avance        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_justification_upd BEFORE UPDATE ON justification FOR EACH ROW EXECUTE FUNCTION set_updated_at();
