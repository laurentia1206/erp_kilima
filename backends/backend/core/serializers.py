"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.tresorerie.models import CompteBancaire
from apps.approbations.models import PalierValidation
from core.models import Parametre
from core.models import PieceJointe
from core.models import Role
from core.models import Societe
from core.models import TauxChange
from core.models import Tiers
from core.models import Utilisateur
from core.models import UtilisateurSociete



class CompteBancaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompteBancaire
        fields = ('id', 'societe_id', 'banque', 'numero_compte', 'devise', 'compte_comptable', 'actif')
        read_only_fields = fields




class PalierValidationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PalierValidation
        fields = ('id', 'societe_id', 'type_document', 'etape', 'montant_min_usd', 'montant_max_usd', 'libelle', 'ordre')
        read_only_fields = fields




class ParametreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parametre
        fields = ('id', 'societe', 'cle', 'valeur', 'type_valeur', 'description')
        read_only_fields = fields




class PieceJointeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PieceJointe
        fields = ('id', 'document_type', 'document_id', 'nom_fichier', 'chemin_stockage', 'mime_type', 'taille_octets', 'uploaded_by', 'uploaded_at')
        read_only_fields = fields




class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ('id', 'code', 'libelle', 'niveau', 'herite_de')
        read_only_fields = fields




class SocieteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Societe
        fields = ('id', 'code', 'nom', 'rccm', 'id_nat', 'nif', 'ville', 'devise_tenue', 'actif', 'created_at')
        read_only_fields = fields




class TauxChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TauxChange
        fields = ('id', 'date_taux', 'devise', 'taux_usd', 'defini_par_id', 'created_at')
        read_only_fields = fields




class TiersSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tiers
        fields = ('id', 'societe_id', 'type', 'code', 'nom', 'compte_auxiliaire', 'utilisateur_id', 'intra_groupe', 'limite_credit_usd', 'points_fidelite', 'societe_liee_id', 'actif')
        read_only_fields = fields




class UtilisateurSerializer(serializers.ModelSerializer):
    class Meta:
        model = Utilisateur
        fields = ('id', 'email', 'nom', 'prenom', 'telephone', 'actif', 'last_login', 'created_at')
        read_only_fields = fields




class UtilisateurSocieteSerializer(serializers.ModelSerializer):
    class Meta:
        model = UtilisateurSociete
        fields = ('utilisateur', 'societe', 'role', 'site_id')
        read_only_fields = fields


