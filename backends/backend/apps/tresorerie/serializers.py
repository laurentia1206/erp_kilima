"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.tresorerie.models import Caisse
from apps.tresorerie.models import MouvementCaisse
from apps.tresorerie.models import SessionCaisse
from apps.tresorerie.models import Transfert


class CaisseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caisse
        fields = ('id', 'societe_id', 'libelle', 'compte_comptable', 'est_principale', 'actif')
        read_only_fields = fields


class MouvementCaisseSerializer(serializers.ModelSerializer):
    class Meta:
        model = MouvementCaisse
        fields = ('id', 'caisse_id', 'session_id', 'numero', 'reference', 'billetage', 'tiers_id', 'tiers_nom', 'date_mouvement', 'heure', 'sens', 'nature', 'devise', 'taux_jour', 'montant', 'montant_usd', 'reference_type', 'reference_id', 'libelle', 'created_by')
        read_only_fields = fields


class SessionCaisseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionCaisse
        fields = ('id', 'caisse', 'date_ouverture', 'ouvert_par', 'fond_initial_usd', 'fond_initial_cdf', 'statut', 'date_cloture', 'cloture_par', 'solde_theorique_usd', 'solde_theorique_cdf', 'solde_physique_usd', 'solde_physique_cdf', 'ecart_usd', 'ecart_cdf', 'billetage_cloture', 'commentaire_cloture')
        read_only_fields = fields


class TransfertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transfert
        fields = ('id', 'numero', 'societe_id', 'source_type', 'source_id', 'dest_type', 'dest_id', 'devise', 'taux_jour', 'montant', 'montant_usd', 'motif', 'statut', 'initie_par', 'created_at', 'valide_par', 'valide_at', 'motif_rejet', 'source_mouvement_id', 'dest_mouvement_id')
        read_only_fields = fields


