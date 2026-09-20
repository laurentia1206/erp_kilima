-- SYSCO ERP v2.0 — Schéma SQLite
-- Architecture multi-tenant · Module Comptabilité OHADA

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── SOCIÉTÉS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    nom         TEXT NOT NULL,
    rccm        TEXT,
    id_nat      TEXT,
    nif         TEXT,
    adresse     TEXT,
    ville       TEXT DEFAULT 'Lubumbashi',
    pays        TEXT DEFAULT 'RDC',
    devise      TEXT DEFAULT 'USD',
    referentiel TEXT DEFAULT 'SYSCOHADA',
    logo_b64    TEXT,
    actif       INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ── UTILISATEURS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    nom           TEXT NOT NULL,
    prenom        TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT DEFAULT 'comptable',
    actif         INTEGER DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now')),
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS user_tenants (
    user_id   INTEGER REFERENCES users(id)   ON DELETE CASCADE,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    role      TEXT DEFAULT 'comptable',
    PRIMARY KEY (user_id, tenant_id)
);

-- ── EXERCICES ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exercices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
    annee      INTEGER NOT NULL,
    date_debut TEXT NOT NULL,
    date_fin   TEXT NOT NULL,
    statut     TEXT DEFAULT 'ouvert',
    UNIQUE(tenant_id, annee)
);

-- ── PLAN DE COMPTE ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comptes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    numero      TEXT NOT NULL,
    intitule    TEXT NOT NULL,
    classe      TEXT,
    categorie   TEXT,
    sens_ohada  TEXT,
    rubrique    TEXT,
    actif       INTEGER DEFAULT 1,
    UNIQUE(tenant_id, numero)
);

CREATE INDEX IF NOT EXISTS idx_comptes_tenant ON comptes(tenant_id, numero);

-- ── JOURNAUX OHADA ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS journaux (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    code            TEXT NOT NULL,
    libelle         TEXT NOT NULL,
    type            TEXT NOT NULL,
    compte_default  TEXT,
    actif           INTEGER DEFAULT 1,
    UNIQUE(tenant_id, code)
);

-- ── ÉCRITURES ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ecritures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id),
    exercice_id    INTEGER NOT NULL REFERENCES exercices(id),
    journal_id     INTEGER REFERENCES journaux(id),
    numero         TEXT NOT NULL,
    date_ecriture  TEXT NOT NULL,
    numero_piece   TEXT,
    libelle        TEXT NOT NULL,
    type_operation TEXT,
    statut         TEXT DEFAULT 'valide',
    user_id        INTEGER REFERENCES users(id),
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ecr_tenant   ON ecritures(tenant_id, exercice_id);
CREATE INDEX IF NOT EXISTS idx_ecr_date     ON ecritures(date_ecriture);
CREATE INDEX IF NOT EXISTS idx_ecr_journal  ON ecritures(journal_id);

-- ── LIGNES D'ÉCRITURE ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lignes_ecriture (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ecriture_id  INTEGER NOT NULL REFERENCES ecritures(id) ON DELETE CASCADE,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    sens         TEXT NOT NULL CHECK(sens IN ('D','C')),
    compte_numero TEXT NOT NULL,
    montant      REAL NOT NULL CHECK(montant > 0),
    libelle_ligne TEXT,
    ordre        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_lignes_ecr    ON lignes_ecriture(ecriture_id);
CREATE INDEX IF NOT EXISTS idx_lignes_compte ON lignes_ecriture(tenant_id, compte_numero);

-- ── SOLDES D'OUVERTURE ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS soldes_ouverture (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    exercice_id   INTEGER NOT NULL REFERENCES exercices(id),
    compte_numero TEXT NOT NULL,
    si_debit      REAL DEFAULT 0,
    si_credit     REAL DEFAULT 0,
    source        TEXT DEFAULT 'manuel',
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(tenant_id, exercice_id, compte_numero)
);

CREATE INDEX IF NOT EXISTS idx_si_tenant ON soldes_ouverture(tenant_id, exercice_id);

-- ── RÈGLES D'AUDIT OHADA ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regles_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    libelle     TEXT NOT NULL,
    description TEXT,
    severite    TEXT DEFAULT 'warning',
    actif       INTEGER DEFAULT 1
);

INSERT OR IGNORE INTO regles_audit(code,libelle,description,severite) VALUES
('ACT_CRED', 'Actif à solde créditeur',
 'Un compte actif ne peut pas avoir de solde créditeur. Indique une erreur d''imputation ou une avance reçue non comptabilisée séparément.',
 'critique'),
('PAS_DEB', 'Passif à solde débiteur',
 'Un compte passif à solde débiteur indique un paiement en trop ou une erreur d''imputation. Nécessite une vérification.',
 'warning'),
('CAISSE_CRED', 'Caisse créditrice',
 'Un solde créditeur sur un compte de caisse (51x) est physiquement impossible. Il ne peut y avoir moins que zéro en caisse.',
 'critique'),
('CHARG_CRED', 'Charge à solde créditeur',
 'Un compte de charge (6x) à solde créditeur peut indiquer une reprise, un avoir ou une erreur. À vérifier selon la nature.',
 'warning'),
('PROD_DEB', 'Produit à solde débiteur',
 'Un compte de produit (7x) à solde débiteur est anormal. Peut indiquer un avoir accordé ou une erreur d''imputation.',
 'warning'),
('CC_ASS_DEB', 'Compte courant associé débiteur',
 'Art. 54 AUDSCGIE : un compte courant d''associé débiteur constitue une avance qui nécessite une convention formelle approuvée en AG.',
 'warning'),
('AMORT_DEB', 'Amortissement à solde débiteur',
 'Les comptes d''amortissement (28x, 29x) doivent toujours être créditeurs en SYSCOHADA. Un solde débiteur indique une erreur.',
 'critique');

-- ── MODULES ERP ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erp_modules (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     TEXT NOT NULL UNIQUE,
    libelle  TEXT NOT NULL,
    version  TEXT DEFAULT '1.0',
    actif    INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO erp_modules(code,libelle,actif) VALUES
('compta',  'Comptabilité OHADA',        1),
('balance', 'Balance & États financiers', 1),
('audit',   'Audit OHADA',               1),
('tft',     'Tableau de flux (TFT)',      1),
('immo',    'Immobilisations',            0),
('paie',    'Paie & RH',                 0),
('stock',   'Gestion des stocks',         0),
('ventes',  'Gestion commerciale',        0),
('achats',  'Gestion des achats',         0);
