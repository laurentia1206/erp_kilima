"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.stocks.models import Article
from apps.commercial.models import Commande
from apps.commercial.models import Devis
from apps.commercial.models import Facture
from apps.commercial.models import ListePrix
from apps.commercial.models import PointVente
from apps.commercial.models import Reception
from core.models import Tiers


class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ('id', 'societe_id', 'code', 'designation', 'unite', 'prix_achat', 'prix_vente', 'assujetti_tva', 'taux_tva', 'categorie', 'nature', 'code_barres', 'taux_commission', 'points_fidelite', 'compte_achat', 'compte_vente', 'compte_stock', 'gere_stock', 'stock_qte', 'stock_valeur', 'actif')
        read_only_fields = fields

    def to_representation(self, instance):
        a = instance
        qte = float(a.stock_qte or 0)
        val = float(a.stock_valeur or 0)
        return {"id": str(a.id), "code": a.code, "designation": a.designation,
                "unite": a.unite, "prix_achat": float(a.prix_achat),
                "prix_vente": float(a.prix_vente), "assujetti_tva": bool(a.assujetti_tva),
                "taux_tva": float(a.taux_tva), "categorie": a.categorie,
                "nature": a.nature or "marchandise",
                "code_barres": a.code_barres, "taux_commission": float(a.taux_commission),
                "points_fidelite": float(a.points_fidelite), "compte_achat": a.compte_achat,
                "compte_vente": a.compte_vente, "compte_stock": a.compte_stock,
                "gere_stock": bool(a.gere_stock), "actif": bool(a.actif),
                "stock_qte": round(qte, 3), "stock_valeur": round(val, 2),
                "cump": round(val / qte, 2) if qte else 0.0}


class CommandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Commande
        fields = ('id', 'societe_id', 'numero', 'tiers_id', 'date_commande', 'date_livraison_prevue', 'reference_fournisseur', 'total_ht', 'intra_groupe', 'statut', 'destination', 'transporteur_societe_id', 'devis_lie_id', 'created_by', 'created_at')
        read_only_fields = fields


class DevisSerializer(serializers.ModelSerializer):
    class Meta:
        model = Devis
        fields = ('id', 'societe_id', 'numero', 'tiers_id', 'date_devis', 'validite', 'statut', 'remise_globale_pct', 'total_ht', 'total_tva', 'total_ttc', 'remise_totale', 'conditions', 'note', 'reference_producteur', 'date_confirmation', 'commande_origine_id', 'created_by', 'created_at')
        read_only_fields = fields


class FactureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ('id', 'societe_id', 'type', 'numero', 'tiers_id', 'date_facture', 'echeance', 'reference', 'total_ht', 'total_frais', 'total_tva', 'total_ttc', 'repartition', 'cout_ventes', 'marge', 'remise_totale', 'note', 'statut', 'intra_groupe', 'reception_id', 'point_vente_id', 'origine_id', 'devis_id', 'facture_liee_id', 'pos_recu_usd', 'pos_monnaie_usd', 'ecriture_id', 'created_by', 'created_at')
        read_only_fields = fields


class ListePrixSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListePrix
        fields = ('id', 'societe_id', 'code', 'libelle', 'actif')
        read_only_fields = fields


class PointVenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointVente
        fields = ('id', 'societe_id', 'depot_id', 'code', 'libelle', 'liste_prix_id', 'caisse_id', 'actif')
        read_only_fields = fields


class ReceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reception
        fields = ('id', 'societe_id', 'numero', 'commande_id', 'date_reception', 'total_valeur', 'total_frais', 'repartition', 'statut', 'ecriture_id', 'created_by', 'created_at')
        read_only_fields = fields


class TiersSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tiers
        fields = ('id', 'societe_id', 'type', 'code', 'nom', 'compte_auxiliaire', 'utilisateur_id', 'intra_groupe', 'limite_credit_usd', 'points_fidelite', 'societe_liee_id', 'actif')
        read_only_fields = fields

    def to_representation(self, instance):
        t = instance
        return {"id": str(t.id), "type": t.type, "code": t.code, "nom": t.nom,
                "societe_id": str(t.societe_id) if t.societe_id else None, "actif": bool(t.actif),
                "intra_groupe": bool(t.intra_groupe),
                "limite_credit_usd": float(t.limite_credit_usd)
                if t.limite_credit_usd is not None else None,
                "points_fidelite": float(t.points_fidelite or 0)}


