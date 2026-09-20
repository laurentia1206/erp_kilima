"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.transport.models import Camion
from apps.transport.models import Chauffeur
from apps.transport.models import ContratTransport
from apps.transport.models import Course
from apps.maintenance.models import InterventionCamion
from apps.transport.models import PleinCarburant


class CamionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camion
        fields = ('id', 'societe_id', 'immatriculation', 'marque', 'capacite_tonnes', 'consommation_l_100km', 'type', 'proprietaire_tiers_id', 'remuneration_mode', 'remuneration_valeur', 'statut', 'motif_immobilisation', 'immobilise_depuis', 'actif')
        read_only_fields = fields


class ChauffeurSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chauffeur
        fields = ('id', 'societe_id', 'nom', 'telephone', 'numero_permis', 'tiers_id', 'actif')
        read_only_fields = fields


class ContratTransportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContratTransport
        fields = ('id', 'societe_id', 'numero', 'libelle', 'client_tiers_id', 'date_debut', 'date_fin', 'statut', 'note', 'created_by', 'created_at')
        read_only_fields = fields


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ('id', 'societe_id', 'numero', 'date_course', 'client_tiers_id', 'contrat_id', 'camion_id', 'chauffeur_id', 'origine', 'destination', 'marchandise', 'tonnage_prevu', 'tonnage_livre', 'unite', 'tarif_mode', 'prix_unitaire', 'statut', 'commande_origine_id', 'heure_depart', 'heure_retour', 'km_depart', 'km_retour', 'incidents', 'requisition_id', 'st_mode', 'st_valeur', 'st_cout', 'st_facture_id', 'facture_id', 'valide_par', 'created_by', 'created_at')
        read_only_fields = fields


class InterventionCamionSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterventionCamion
        fields = ('id', 'societe_id', 'camion_id', 'engin_id', 'numero', 'type', 'statut', 'date_prevue', 'description', 'prestataire', 'cout_estime', 'cout_reel', 'immobilise', 'date_signalement', 'date_fin', 'requisition_id', 'plan_id', 'created_by', 'created_at')
        read_only_fields = fields


class PleinCarburantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PleinCarburant
        fields = ('id', 'societe_id', 'camion_id', 'engin_id', 'course_id', 'date_plein', 'litres', 'prix_litre_usd', 'montant_usd', 'compteur', 'fournisseur', 'note', 'created_by', 'created_at')
        read_only_fields = fields


