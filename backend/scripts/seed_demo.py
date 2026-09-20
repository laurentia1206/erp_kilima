"""Amorçage de démonstration (réutilisable pour le dev et les tests d'intégration).

Crée le minimum pour faire tourner le circuit de décaissement de bout en bout :
rôles, société PLANET, paliers de validation, comptes, une caisse, un
bénéficiaire, et des utilisateurs (un par rôle).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app import models
from app.security import hash_password

MOT_DE_PASSE_DEMO = "demo1234"

ROLES = [
    ("PRESIDENT", "Président", 100), ("DG", "Directeur Général", 90),
    ("DFI", "Directeur Financier", 80), ("ADMIN", "Administratrice", 70),
    ("DT", "Directeur Technique", 70), ("COMPTABLE", "Comptable", 40),
    ("CAISSIER_CENTRAL", "Caissier central", 30),
]

UTILISATEURS = [
    ("president@kilima.cd", "MALIGIJA", "PRESIDENT"),
    ("dg@kilima.cd", "Arsène", "DG"),
    ("dfi@kilima.cd", "DFI", "DFI"),
    ("admin@kilima.cd", "Huguette", "ADMIN"),
    ("caissier@kilima.cd", "MUSOLO", "CAISSIER_CENTRAL"),
    ("comptable@kilima.cd", "TSHIBWABWA", "COMPTABLE"),
]


def seed_demo(db: Session) -> dict:
    # Rôles
    roles = {}
    for code, lib, niv in ROLES:
        r = models.Role(code=code, libelle=lib, niveau=niv)
        db.add(r)
        roles[code] = r
    db.flush()

    # Société PLANET
    pla = models.Societe(code="PLA", nom="PLANET Sarl", ville="Likasi")
    db.add(pla)
    db.flush()

    # Plan comptable SYSCOHADA révisé complet
    from app.plan_comptable import charger_plan
    charger_plan(db, pla.id)

    # Journaux standard
    for code, lib, typ in [("AN", "À-nouveaux", "ouverture"), ("AC", "Achats", "achat"),
                           ("VE", "Ventes", "vente"), ("BQ", "Banque", "banque"),
                           ("CA", "Caisse", "caisse"), ("OD", "Opérations diverses", "od"),
                           ("VI", "Virements internes", "od")]:
        db.add(models.Journal(societe_id=pla.id, code=code, libelle=lib, type=typ))

    # Axes analytiques par défaut (configurables) + sections
    axes_seed = {
        ("CENTRE", "Centre de coût"): [("ADMIN", "Administration"), ("DIR", "Direction"),
                                       ("TRANSP", "Transport"), ("MAGASIN", "Magasin"),
                                       ("HOTEL", "Hôtellerie")],
        ("ACTIVITE", "Activité / métier"): [("CIMENT", "Ciment"), ("QUINC", "Quincaillerie"),
                                            ("TRANSP", "Transport"), ("LOCAT", "Location d'engins"),
                                            ("HOTEL", "Hôtellerie-restauration")],
    }
    for (acode, alib), sections in axes_seed.items():
        axe = models.AxeAnalytique(societe_id=pla.id, code=acode, libelle=alib)
        db.add(axe)
        db.flush()
        for scode, slib in sections:
            db.add(models.SectionAnalytique(axe_id=axe.id, societe_id=pla.id, code=scode, libelle=slib))

    # Articles (ciment) + tiers commerciaux pour la démo
    db.add(models.Article(societe_id=pla.id, code="CIM50", designation="Ciment gris 50 kg",
                          unite="sac", prix_achat=11, prix_vente=14, taux_tva=16,
                          compte_achat="601", compte_vente="701", compte_stock="31"))
    db.add(models.Article(societe_id=pla.id, code="CIMT", designation="Ciment en vrac (tonne)",
                          unite="tonne", prix_achat=210, prix_vente=250, taux_tva=16,
                          compte_achat="601", compte_vente="701", compte_stock="31"))
    db.add(models.Tiers(societe_id=pla.id, type="fournisseur", code="F-CIMEN", nom="Cimenterie de Lukala"))
    db.add(models.Tiers(societe_id=pla.id, type="client", code="C-KAKO", nom="KAKO Sarl (groupe)", intra_groupe=True))
    db.add(models.Tiers(societe_id=pla.id, type="client", code="C-BTP", nom="Entreprise BTP Katanga"))

    # Caisses (dont un POS, pour tester les transferts) + compte bancaire
    # La caisse centrale est la destination des cessions POS ; la caisse POS est une
    # « caisse temporaire » avec son propre compte (5711) soldé à la remise.
    caisse = models.Caisse(societe_id=pla.id, libelle="Caisse centrale", compte_comptable="571",
                           est_principale=True)
    db.add(caisse)
    caisse_pos = models.Caisse(societe_id=pla.id, libelle="Caisse POS Kolwezi", compte_comptable="5711")
    db.add(caisse_pos)
    banque = models.CompteBancaire(societe_id=pla.id, banque="RAWBANK", numero_compte="01-2345-6789",
                                   devise="USD", compte_comptable="521")
    db.add(banque)

    # Bénéficiaire d'avance
    benef = models.Tiers(societe_id=pla.id, type="agent", code="AG001", nom="Agent Démo")
    db.add(benef)
    db.flush()

    # Listes de prix + point de vente (préparation POS)
    lp_detail = models.ListePrix(societe_id=pla.id, code="DETAIL", libelle="Tarif détail")
    lp_gros = models.ListePrix(societe_id=pla.id, code="GROS", libelle="Tarif gros")
    db.add_all([lp_detail, lp_gros])
    db.flush()
    db.add(models.PointVente(societe_id=pla.id, code="POS-KLZ", libelle="POS Kolwezi",
                             liste_prix_id=lp_detail.id, caisse_id=caisse_pos.id))

    # Utilisateurs (tous affectés à PLANET avec leur rôle)
    users = {}
    user_objs = {}
    for email, nom, role_code in UTILISATEURS:
        u = models.Utilisateur(email=email, nom=nom, password_hash=hash_password(MOT_DE_PASSE_DEMO))
        db.add(u)
        db.flush()
        db.add(models.UtilisateurSociete(utilisateur_id=u.id, societe_id=pla.id,
                                         role_id=roles[role_code].id))
        users[role_code] = email
        user_objs[role_code] = u

    # Paliers — validation de la demande (DG + Admin)
    pv_dem = models.PalierValidation(societe_id=None, type_document="requisition",
                                     etape="demande", montant_min_usd=Decimal("0"),
                                     montant_max_usd=None, libelle="Demande — DG + Admin")
    db.add(pv_dem)
    db.flush()
    db.add(models.PalierApprobateur(palier_id=pv_dem.id, role_id=roles["DG"].id, mode="conjoint", ordre=1))
    db.add(models.PalierApprobateur(palier_id=pv_dem.id, role_id=roles["ADMIN"].id, mode="conjoint", ordre=2))

    # Paliers — sortie de fonds
    p1 = models.PalierValidation(societe_id=None, type_document="ordre_depense",
                                 etape="sortie_fonds", montant_min_usd=Decimal("0"),
                                 montant_max_usd=Decimal("1000"), libelle="≤1000 — DFI")
    p2 = models.PalierValidation(societe_id=None, type_document="ordre_depense",
                                 etape="sortie_fonds", montant_min_usd=Decimal("1000.01"),
                                 montant_max_usd=Decimal("10000"), libelle="1001-10000")
    p3 = models.PalierValidation(societe_id=None, type_document="ordre_depense",
                                 etape="sortie_fonds", montant_min_usd=Decimal("10000.01"),
                                 montant_max_usd=None, libelle=">10000 — Président")
    db.add_all([p1, p2, p3])
    db.flush()
    db.add(models.PalierApprobateur(palier_id=p1.id, role_id=roles["DFI"].id, mode="seul", ordre=1))
    for i, rc in enumerate(["DFI", "DG", "ADMIN", "PRESIDENT"], start=1):
        db.add(models.PalierApprobateur(palier_id=p2.id, role_id=roles[rc].id, mode="conjoint", ordre=i))
    db.add(models.PalierApprobateur(palier_id=p3.id, role_id=roles["PRESIDENT"].id, mode="seul", ordre=1))

    # ── Paramètres / seuils configurables (groupe) ──
    PARAMS = [
        ("seuil_palier_1_usd", "1000", "Plafond palier 1 (DFI seul)"),
        ("seuil_palier_2_usd", "10000", "Plafond palier 2 (validation conjointe)"),
        ("delai_justif_defaut_h", "24", "Délai de justification d'avance par défaut (heures)"),
        ("creance_relance_j", "7", "Relance créance dès N jours de retard"),
        ("creance_escalade_dg_j", "30", "Escalade DG des créances à N jours"),
        ("avance_salaire_max_pct", "50", "Plafond avance sur salaire (% du brut)"),
        ("apurement_gck_j", "15", "Apurement avance GCK sous N jours (DAKAM)"),
        ("seuil_ecart_caisse_usd", "0", "[A DEFINIR PAR LA DG] Ecart de caisse a escalader"),
        ("ratio_cuisine_cible_pct", "0", "[A DEFINIR PAR LA DG] Ratio cout cuisine / CA cible (GHR)"),
        ("delai_justif.course", "2", "Avance course camion - heures (KAKO Log.)"),
        ("delai_justif.marche", "2", "Avance achats marche - heures (GHR)"),
        ("delai_justif.pieces", "24", "Avance pieces/maintenance - heures"),
        ("delai_justif.boissons", "24", "Avance boissons/divers - heures"),
    ]
    for cle, val, desc in PARAMS:
        db.add(models.Parametre(societe_id=None, cle=cle, valeur=val, type_valeur="number", description=desc))

    # ── Dossiers de démonstration en attente (pour peupler le Centre d'approbation) ──
    from datetime import date
    an = date.today().year
    comptable = user_objs["COMPTABLE"]

    def _req(seq, objet, montant, prio, statut):
        r = models.Requisition(numero=f"REQ-PLA-{an}-{seq:06d}", societe_id=pla.id,
                               initiateur_id=comptable.id, objet=objet, priorite=prio, devise="USD",
                               montant_total=Decimal(montant), montant_total_usd=Decimal(montant),
                               statut=statut)
        r.lignes.append(models.RequisitionLigne(ordre=0, description=objet, quantite=1,
                                                prix_unitaire=Decimal(montant), montant=Decimal(montant),
                                                devise="USD", montant_usd=Decimal(montant)))
        db.add(r)
        db.flush()
        return r

    # Deux réquisitions en attente de validation de la demande (DG + Admin)
    _req(1, "Fournitures de bureau", "800", "normal", "soumise")
    _req(2, "Réparation génératrice", "3000", "urgent", "soumise")

    # Une réquisition déjà validée + ordre de dépense en attente de sortie de fonds (5 000 USD)
    r3 = _req(3, "Achat ciment", "5000", "normal", "demande_validee")
    db.add(models.OrdreDepense(
        numero=f"ODP-PLA-{an}-000001", requisition_id=r3.id, societe_id=pla.id,
        beneficiaire_tiers_id=benef.id, motif="Achat ciment (5 000 USD)", mode_paiement="caisse",
        devise="USD", montant_autorise=Decimal("5000"), montant_autorise_usd=Decimal("5000"),
        palier_applique="1001-10000", statut="a_valider"))

    # Cale les compteurs pour éviter toute collision avec la numérotation automatique
    db.add(models.SequenceCompteur(societe_id=pla.id, type_piece="requisition", annee=an, dernier_numero=3))
    db.add(models.SequenceCompteur(societe_id=pla.id, type_piece="ordre_depense", annee=an, dernier_numero=1))

    db.commit()
    return {
        "societe_id": str(pla.id),
        "caisse_id": str(caisse.id),
        "beneficiaire_id": str(benef.id),
        "users": users,
        "password": MOT_DE_PASSE_DEMO,
    }
