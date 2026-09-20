"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.maintenance.models import DocumentFlotte
from apps.maintenance.models import PlanEntretien


class DocumentFlotteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFlotte
        fields = ('id', 'societe_id', 'camion_id', 'engin_id', 'chauffeur_id', 'type_document', 'libelle', 'numero', 'date_emission', 'date_expiration', 'note', 'created_by', 'created_at')
        read_only_fields = fields


class PlanEntretienSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanEntretien
        fields = ('id', 'societe_id', 'camion_id', 'engin_id', 'libelle', 'periodicite_type', 'periodicite_valeur', 'derniere_date', 'derniere_valeur', 'note', 'actif', 'created_by', 'created_at')
        read_only_fields = fields


