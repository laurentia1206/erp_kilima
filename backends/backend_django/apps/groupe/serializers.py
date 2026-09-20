"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.commercial.models import Commande
from apps.commercial.models import Facture
from apps.groupe.models import ReceptionInter


class CommandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Commande
        fields = ('id', 'societe_id', 'numero', 'tiers_id', 'date_commande', 'date_livraison_prevue', 'reference_fournisseur', 'total_ht', 'intra_groupe', 'statut', 'destination', 'transporteur_societe_id', 'devis_lie_id', 'created_by', 'created_at')
        read_only_fields = fields


class FactureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ('id', 'societe_id', 'type', 'numero', 'tiers_id', 'date_facture', 'echeance', 'reference', 'total_ht', 'total_frais', 'total_tva', 'total_ttc', 'repartition', 'cout_ventes', 'marge', 'remise_totale', 'note', 'statut', 'intra_groupe', 'reception_id', 'point_vente_id', 'origine_id', 'devis_id', 'facture_liee_id', 'pos_recu_usd', 'pos_monnaie_usd', 'ecriture_id', 'created_by', 'created_at')
        read_only_fields = fields


class ReceptionInterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceptionInter
        fields = ('id', 'societe_id', 'commande_id', 'numero', 'date_reception', 'note', 'statut', 'confirme_par', 'date_confirmation', 'created_by', 'created_at')
        read_only_fields = fields


