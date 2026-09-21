"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.tresorerie.models import Avance
from apps.tresorerie.models import BlocageBeneficiaire
from apps.approbations.models import OrdreDepense
from apps.approbations.models import Requisition


class AvanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Avance
        fields = ('id', 'numero', 'ordre_depense_id', 'bon_reception_id', 'beneficiaire_tiers_id', 'societe_id', 'type_avance', 'devise', 'montant_avance', 'montant_avance_usd', 'date_octroi', 'delai_justif_heures', 'echeance_justif', 'statut', 'created_at')
        read_only_fields = fields


class BlocageBeneficiaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlocageBeneficiaire
        fields = ('id', 'tiers_id', 'avance_id', 'motif', 'actif', 'bloque_at', 'leve_par', 'leve_motif', 'leve_at')
        read_only_fields = fields


class OrdreDepenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdreDepense
        fields = ('id', 'numero', 'requisition_id', 'societe_id', 'beneficiaire_tiers_id', 'motif', 'mode_paiement', 'mode_decaissement', 'devise', 'taux_jour', 'montant_autorise', 'montant_autorise_usd', 'montant_paye_usd', 'montant_lettres', 'palier_applique', 'statut', 'created_by', 'created_at')
        read_only_fields = fields


class RequisitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Requisition
        fields = ('id', 'numero', 'societe_id', 'site_id', 'initiateur_id', 'date_requisition', 'objet', 'justification', 'mode_decaissement', 'nature', 'priorite', 'devise', 'taux_jour', 'montant_total', 'montant_total_usd', 'statut', 'created_at')
        read_only_fields = fields


