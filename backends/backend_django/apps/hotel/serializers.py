"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.hotel.models import Chambre
from apps.hotel.models import ConsommationCuisine
from apps.hotel.models import FicheTechnique
from apps.hotel.models import Sejour
from core.models import Tiers


class ChambreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chambre
        fields = ('id', 'societe_id', 'numero', 'categorie', 'tarif_nuit_usd', 'capacite', 'etat', 'note', 'actif', 'created_by', 'created_at')
        read_only_fields = fields


class ConsommationCuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsommationCuisine
        fields = ('id', 'societe_id', 'numero', 'depot_id', 'date_conso', 'cout_total', 'ca_total', 'nb_plats', 'ecriture_id', 'created_by', 'created_at')
        read_only_fields = fields


class FicheTechniqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = FicheTechnique
        fields = ('id', 'societe_id', 'article_id', 'portions', 'note', 'actif', 'created_by', 'created_at')
        read_only_fields = fields


class SejourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sejour
        fields = ('id', 'societe_id', 'numero', 'chambre_id', 'tiers_id', 'client_nom', 'client_telephone', 'nb_personnes', 'date_arrivee', 'date_depart_prevue', 'date_depart', 'tarif_nuit_usd', 'statut', 'source', 'note', 'facture_id', 'created_by', 'created_at')
        read_only_fields = fields


class TiersSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tiers
        fields = ('id', 'societe_id', 'type', 'code', 'nom', 'compte_auxiliaire', 'utilisateur_id', 'intra_groupe', 'limite_credit_usd', 'points_fidelite', 'societe_liee_id', 'actif')
        read_only_fields = fields


