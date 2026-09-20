-- =====================================================================
--  ERP KILIMA HOLDINGS — DONNÉES D'AMORÇAGE (V1)
--  À exécuter APRÈS schema_v1.sql.
--  Contient : sociétés, sites, rôles, grille de paliers de validation
--  (avec exception HORIZON), et paramètres/seuils configurables.
--  NB : KAKO modélisée comme UNE société à 2 agences (Likasi, Kolwezi) — À CONFIRMER.
-- =====================================================================

-- ── SOCIÉTÉS (6) ─────────────────────────────────────────────────────
INSERT INTO societe (code, nom, ville) VALUES
  ('PLA', 'PLANET Sarl',            'Likasi'),
  ('DAK', 'DAKAM Sarl',             'Likasi'),
  ('KAK', 'KAKO Sarl',              'Likasi'),
  ('KLO', 'KAKO Logistique',        'Likasi'),
  ('HOR', 'Ets HORIZON',            'Likasi'),
  ('GHR', 'Guest House Relax',      'Likasi');

-- ── SITES / AGENCES ──────────────────────────────────────────────────
INSERT INTO site (societe_id, code, nom, ville)
SELECT id, 'LIK', 'Likasi', 'Likasi' FROM societe WHERE code='KAK'
UNION ALL SELECT id, 'KOL', 'Kolwezi', 'Kolwezi' FROM societe WHERE code='KAK'
UNION ALL SELECT id, 'LIK', 'Likasi', 'Likasi' FROM societe WHERE code='KLO'
UNION ALL SELECT id, 'KOL', 'Kolwezi', 'Kolwezi' FROM societe WHERE code='KLO';

-- ── RÔLES ────────────────────────────────────────────────────────────
INSERT INTO role (code, libelle, niveau) VALUES
  ('PRESIDENT',         'Président',                       100),
  ('DG',                'Directeur Général',                90),
  ('DFI',               'Directeur Financier',              80),
  ('ADMIN',             'Administratrice',                  70),
  ('DT',                'Directeur Technique',              70),
  ('COMPTABLE',         'Comptable',                        40),
  ('CAISSIER_CENTRAL',  'Caissier central',                 30),
  ('CAISSIER_VENDEUR',  'Caissier-vendeur (point de vente)',30),
  ('RESP_INV_IT',       'Responsable Inventaire & IT',      35),
  ('ASSISTANT_TECH',    'Assistant technique',              20),
  ('VENDEUR',           'Vendeur',                          20),
  ('ADMIN_SYS',         'Administrateur système',           10);

-- ── GRILLE DE VALIDATION DES SORTIES DE FONDS (groupe, societe_id NULL) ──
-- Palier 1 : ≤ 1 000 USD → DFI seul
INSERT INTO palier_validation (societe_id, type_document, etape, montant_min_usd, montant_max_usd, libelle, ordre)
VALUES (NULL,'ordre_depense','sortie_fonds',0,1000,'≤ 1 000 USD — DFI seul',1);
-- Palier 2 : 1 001 – 10 000 USD → DFI + DG + ADMIN + PRESIDENT (conjoint)
INSERT INTO palier_validation (societe_id, type_document, etape, montant_min_usd, montant_max_usd, libelle, ordre)
VALUES (NULL,'ordre_depense','sortie_fonds',1000.01,10000,'1 001–10 000 USD — DFI+DG+Admin+Président',2);
-- Palier 3 : > 10 000 USD → PRESIDENT
INSERT INTO palier_validation (societe_id, type_document, etape, montant_min_usd, montant_max_usd, libelle, ordre)
VALUES (NULL,'ordre_depense','sortie_fonds',10000.01,NULL,'> 10 000 USD — Président',3);

-- Approbateurs du palier 1
INSERT INTO palier_approbateur (palier_id, role_id, mode, ordre)
SELECT pv.id, r.id, 'seul', 1
FROM palier_validation pv JOIN role r ON r.code='DFI'
WHERE pv.societe_id IS NULL AND pv.type_document='ordre_depense' AND pv.etape='sortie_fonds' AND pv.montant_min_usd=0;

-- Approbateurs du palier 2 (conjoints)
INSERT INTO palier_approbateur (palier_id, role_id, mode, ordre)
SELECT pv.id, r.id, 'conjoint', x.ordre
FROM palier_validation pv
JOIN (VALUES ('DFI',1),('DG',2),('ADMIN',3),('PRESIDENT',4)) AS x(code,ordre) ON TRUE
JOIN role r ON r.code = x.code
WHERE pv.societe_id IS NULL AND pv.type_document='ordre_depense' AND pv.etape='sortie_fonds' AND pv.montant_min_usd=1000.01;

-- Approbateur du palier 3
INSERT INTO palier_approbateur (palier_id, role_id, mode, ordre)
SELECT pv.id, r.id, 'seul', 1
FROM palier_validation pv JOIN role r ON r.code='PRESIDENT'
WHERE pv.societe_id IS NULL AND pv.type_document='ordre_depense' AND pv.etape='sortie_fonds' AND pv.montant_min_usd=10000.01;

-- ── VALIDATION DE LA DEMANDE ─────────────────────────────────────────
-- Standard groupe (tous montants) : DG + ADMIN conjoints
INSERT INTO palier_validation (societe_id, type_document, etape, montant_min_usd, montant_max_usd, libelle, ordre)
VALUES (NULL,'requisition','demande',0,NULL,'Validation demande — DG + Admin',1);
INSERT INTO palier_approbateur (palier_id, role_id, mode, ordre)
SELECT pv.id, r.id, 'conjoint', x.ordre
FROM palier_validation pv
JOIN (VALUES ('DG',1),('ADMIN',2)) AS x(code,ordre) ON TRUE
JOIN role r ON r.code = x.code
WHERE pv.societe_id IS NULL AND pv.type_document='requisition' AND pv.etape='demande';

-- Exception HORIZON : validation demande = DG + DT (technique)
INSERT INTO palier_validation (societe_id, type_document, etape, montant_min_usd, montant_max_usd, libelle, ordre)
SELECT id,'requisition','demande',0,NULL,'Validation demande HORIZON — DG + DT',1 FROM societe WHERE code='HOR';
INSERT INTO palier_approbateur (palier_id, role_id, mode, ordre)
SELECT pv.id, r.id, 'conjoint', x.ordre
FROM palier_validation pv
JOIN societe s ON s.id = pv.societe_id AND s.code='HOR'
JOIN (VALUES ('DG',1),('DT',2)) AS x(code,ordre) ON TRUE
JOIN role r ON r.code = x.code
WHERE pv.type_document='requisition' AND pv.etape='demande';

-- ── PARAMÈTRES & SEUILS CONFIGURABLES (groupe) ───────────────────────
INSERT INTO parametre (societe_id, cle, valeur, type_valeur, description) VALUES
  (NULL,'seuil_palier_1_usd','1000','number','Plafond palier 1 (DFI seul)'),
  (NULL,'seuil_palier_2_usd','10000','number','Plafond palier 2 (validation conjointe)'),
  (NULL,'delai_justif_defaut_h','24','number','Délai de justification d''avance par défaut (heures)'),
  (NULL,'creance_relance_j','7','number','Relance créance dès N jours de retard'),
  (NULL,'creance_escalade_dg_j','30','number','Escalade DG des créances à N jours'),
  (NULL,'avance_salaire_max_pct','50','number','Plafond avance sur salaire (% du brut mensuel)'),
  (NULL,'apurement_gck_j','15','number','Apurement avance GCK sous N jours (DAKAM)'),
  (NULL,'facture_gck_j','5','number','Récupération facture GCK sous N jours ouvrables (DAKAM)'),
  -- Seuils « À DÉFINIR PAR LA DG » — valeurs provisoires à confirmer
  (NULL,'seuil_ecart_caisse_usd','0','number','[À DÉFINIR PAR LA DG] Écart de caisse à escalader'),
  (NULL,'ratio_cuisine_cible_pct','0','number','[À DÉFINIR PAR LA DG] Ratio coût cuisine / CA cible (GHR)'),
  (NULL,'seuil_ecart_inventaire_usd','0','number','[À DÉFINIR PAR LA DG] Écart d''inventaire à signaler'),
  (NULL,'seuil_commande_importante_usd','0','number','[À DÉFINIR PAR LA DG] Seuil commande importante (DAKAM)');

-- ── DÉLAIS DE JUSTIFICATION SPÉCIFIQUES PAR TYPE D'AVANCE (groupe) ────
INSERT INTO parametre (societe_id, cle, valeur, type_valeur, description) VALUES
  (NULL,'delai_justif.course','2','number','Avance course camion — heures (KAKO Log.)'),
  (NULL,'delai_justif.marche','2','number','Avance achats marché — heures (GHR)'),
  (NULL,'delai_justif.pieces','24','number','Avance pièces/maintenance — heures'),
  (NULL,'delai_justif.boissons','24','number','Avance boissons/divers — heures'),
  (NULL,'delai_justif.forfait','720','number','Forfait entretien mensuel — heures (≈30 j, GHR)');
