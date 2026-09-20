"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.rh.models import RHAgent
from apps.rh.models import RHBulletin
from apps.rh.models import RHContrat
from apps.rh.models import RHDecompte
from apps.rh.models import RHDemande
from apps.rh.models import RHDette
from apps.rh.models import RHDocument
from apps.rh.models import RHPaieMois
from apps.rh.models import RHPointage
from apps.rh.models import RHPolitique
from apps.rh.models import RHSimulation


class RHAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHAgent
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'matricule', 'nom', 'nom_normalise', 'utilisateur', 'tiers', 'equipe', 'horaire', 'poste', 'date_engagement', 'date_sortie', 'telephone', 'email', 'adresse', 'numero_cnss', 'nif')
        read_only_fields = fields

    def to_representation(self, instance):
        a = instance
        prive = self.context.get('prive', False)
        d={'id':str(a.id),'matricule':a.matricule,'nom':a.nom,'poste':a.poste,
           'equipe_id':str(a.equipe_id) if a.equipe_id else '', 'equipe':a.equipe.nom if a.equipe else '',
           'horaire_id':str(a.horaire_id) if a.horaire_id else '', 'horaire':a.horaire.nom if a.horaire else '',
           'date_engagement':a.date_engagement,'date_sortie':a.date_sortie,'revision':a.revision}
        if prive:
            d.update({k:getattr(a,k) for k in ('telephone','email','adresse','numero_cnss','nif')})
            d['utilisateur_id']=str(a.utilisateur_id) if a.utilisateur_id else ''
            d['tiers_id']=str(a.tiers_id) if a.tiers_id else ''
        return d


class RHBulletinSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHBulletin
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'periode', 'agent', 'contrat', 'saisie', 'resultat', 'empreinte_sources', 'ecriture_id', 'net_comptable_usd')
        read_only_fields = fields


class RHContratSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHContrat
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'reference', 'type_contrat', 'debut', 'fin', 'salaire', 'base_salaire', 'devise', 'categorie', 'convention', 'remuneration')
        read_only_fields = fields


class RHDecompteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHDecompte
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'contrat', 'date_depart', 'motif', 'parametres', 'resultat', 'statut', 'controle_note')
        read_only_fields = fields


class RHDemandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHDemande
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'nature', 'motif', 'debut', 'fin', 'type_conge', 'montant', 'devise', 'statut', 'decision_note', 'decide_par', 'decide_at')
        read_only_fields = fields


class RHDetteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHDette
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'demande', 'avance_source', 'accord', 'nature', 'montant', 'devise', 'salaire_reference', 'plafond_pct', 'echeancier', 'motif', 'statut', 'decisions', 'verse_at', 'mouvement_id', 'ecriture_id')
        read_only_fields = fields


class RHDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHDocument
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'nom', 'nature', 'mime', 'empreinte')
        read_only_fields = fields


class RHPaieMoisSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHPaieMois
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'mois', 'parametres', 'statut', 'decisions')
        read_only_fields = fields


class RHPointageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHPointage
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'agent', 'jour', 'nature', 'debut', 'fin', 'pause_debut', 'pause_fin', 'minutes', 'minutes_nuit', 'horaire_prevu', 'note', 'statut', 'valide_par', 'valide_at')
        read_only_fields = fields


class RHPolitiqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHPolitique
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'plafond_avance_pct', 'delai_recouvrement_jours')
        read_only_fields = fields


class RHSimulationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RHSimulation
        fields = ('id', 'societe', 'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'nom', 'parametres', 'resultat')
        read_only_fields = fields


