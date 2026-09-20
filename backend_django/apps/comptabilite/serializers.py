"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.comptabilite.models import AxeAnalytique
from apps.comptabilite.models import Compte
from apps.comptabilite.models import Ecriture
from apps.comptabilite.models import Journal
from apps.comptabilite.models import PreparationTVA
from apps.comptabilite.models import RapprochementBancaire
from apps.comptabilite.models import SectionAnalytique


class AxeAnalytiqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = AxeAnalytique
        fields = ('id', 'societe_id', 'code', 'libelle', 'actif')
        read_only_fields = fields


class CompteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compte
        fields = ('id', 'societe_id', 'numero', 'intitule', 'classe', 'auxiliaire', 'actif')
        read_only_fields = fields


class EcritureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ecriture
        fields = ('id', 'societe_id', 'exercice_id', 'journal_id', 'numero', 'date_ecriture', 'numero_piece', 'libelle', 'type_operation', 'source_type', 'source_id', 'statut', 'created_by', 'created_at')
        read_only_fields = fields


class JournalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Journal
        fields = ('id', 'societe_id', 'code', 'libelle', 'type', 'actif')
        read_only_fields = fields


class PreparationTVASerializer(serializers.ModelSerializer):
    class Meta:
        model = PreparationTVA
        fields = ('id', 'societe_id', 'mois', 'donnees', 'revision', 'updated_by', 'updated_at')
        read_only_fields = fields


class RapprochementBancaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = RapprochementBancaire
        fields = ('id', 'societe_id', 'compte', 'date_releve', 'solde_releve_usd', 'solde_comptable_usd', 'solde_rapproche_usd', 'ecart_usd', 'statut', 'created_by', 'created_at')
        read_only_fields = fields


class SectionAnalytiqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = SectionAnalytique
        fields = ('id', 'axe_id', 'societe_id', 'code', 'libelle', 'actif')
        read_only_fields = fields


