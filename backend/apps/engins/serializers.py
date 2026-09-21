"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.engins.models import Engin
from apps.engins.models import PrestationEngin


class EnginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Engin
        fields = ('id', 'societe_id', 'nom', 'categorie', 'immatriculation', 'tarif_mensuel_usd', 'tarif_heure_supp_usd', 'consommation_l_heure', 'statut', 'motif_immobilisation', 'immobilise_depuis', 'actif', 'created_by', 'created_at')
        read_only_fields = fields


class PrestationEnginSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrestationEngin
        fields = ('id', 'societe_id', 'engin_id', 'date_prestation', 'poste', 'operateur', 'heure_debut', 'heure_fin', 'index_debut', 'index_fin', 'affectation', 'created_by', 'created_at')
        read_only_fields = fields


