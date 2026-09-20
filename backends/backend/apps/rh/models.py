"""Dossiers RH cloisonnés par employeur ; aucune écriture financière implicite."""
import uuid
from django.db import models


class RHBase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe = models.ForeignKey('core.Societe', on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    created_by = models.UUIDField()
    updated_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class RHEquipe(RHBase):
    nom = models.CharField(max_length=120)
    responsable = models.ForeignKey('core.Utilisateur', null=True, blank=True, on_delete=models.PROTECT)
    class Meta:
        db_table = 'core_rhequipe'
        constraints = [models.UniqueConstraint(fields=['societe', 'nom'], name='rh_equipe_nom_unique')]


class RHHoraire(RHBase):
    nom = models.CharField(max_length=120)
    # Jours 0=lundi ... 6=dimanche, début/fin HH:MM, lendemain, pause début/fin.
    semaine = models.JSONField(default=list)
    note = models.TextField(blank=True)
    class Meta:
        db_table = 'core_rhhoraire'
        constraints = [models.UniqueConstraint(fields=['societe', 'nom'], name='rh_horaire_nom_unique')]


class RHAgent(RHBase):
    matricule = models.CharField(max_length=40)
    nom = models.CharField(max_length=180)
    nom_normalise = models.CharField(max_length=180)
    utilisateur = models.ForeignKey('core.Utilisateur', null=True, blank=True, on_delete=models.PROTECT)
    tiers = models.ForeignKey('core.Tiers', null=True, blank=True, on_delete=models.PROTECT)
    equipe = models.ForeignKey(RHEquipe, null=True, blank=True, on_delete=models.PROTECT)
    horaire = models.ForeignKey(RHHoraire, null=True, blank=True, on_delete=models.PROTECT)
    poste = models.CharField(max_length=150, blank=True)
    date_engagement = models.DateField()
    date_sortie = models.DateField(null=True, blank=True)
    telephone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    adresse = models.TextField(blank=True)
    numero_cnss = models.CharField(max_length=80, blank=True)
    nif = models.CharField(max_length=80, blank=True)
    class Meta:
        db_table = 'core_rhagent'
        constraints = [
            models.UniqueConstraint(fields=['societe', 'matricule'], name='rh_matricule_unique'),
            models.UniqueConstraint(fields=['societe', 'utilisateur'], name='rh_utilisateur_unique'),
            models.UniqueConstraint(fields=['societe', 'tiers'], name='rh_tiers_unique'),
        ]


class RHContrat(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    reference = models.CharField(max_length=80)
    type_contrat = models.CharField(max_length=20)
    debut = models.DateField()
    fin = models.DateField(null=True, blank=True)
    salaire = models.DecimalField(max_digits=18, decimal_places=2)
    base_salaire = models.CharField(max_length=8)  # brut / net, jamais converti implicitement
    devise = models.CharField(max_length=3)
    categorie = models.CharField(max_length=120, blank=True)
    convention = models.TextField(blank=True)
    remuneration = models.JSONField(default=dict)
    class Meta:
        db_table = 'core_rhcontrat'
        constraints = [models.UniqueConstraint(fields=['societe', 'reference'], name='rh_contrat_reference_unique')]


class RHEvenement(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    nature = models.CharField(max_length=24)
    date = models.DateField()
    titre = models.CharField(max_length=180)
    contenu = models.TextField()

    class Meta:
        db_table = 'core_rhevenement'


class RHDocument(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    nom = models.CharField(max_length=180)
    nature = models.CharField(max_length=30)
    mime = models.CharField(max_length=80)
    empreinte = models.CharField(max_length=64)
    contenu = models.BinaryField()
    class Meta:
        db_table = 'core_rhdocument'
        constraints = [models.UniqueConstraint(fields=['agent', 'empreinte'], name='rh_document_unique')]


class RHPointage(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    jour = models.DateField()
    nature = models.CharField(max_length=20)
    debut = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    pause_debut = models.DateTimeField(null=True, blank=True)
    pause_fin = models.DateTimeField(null=True, blank=True)
    minutes = models.PositiveIntegerField(default=0)
    minutes_nuit = models.PositiveIntegerField(default=0)
    horaire_prevu = models.JSONField(default=dict)
    note = models.TextField(blank=True)
    statut = models.CharField(max_length=20, default='brouillon')
    valide_par = models.UUIDField(null=True, blank=True)
    valide_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = 'core_rhpointage'
        constraints = [models.UniqueConstraint(fields=['agent', 'jour'], name='rh_pointage_jour_unique')]


class RHDemande(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    nature = models.CharField(max_length=24)  # congé / avance sur salaire
    motif = models.TextField()
    debut = models.DateField(null=True, blank=True)
    fin = models.DateField(null=True, blank=True)
    type_conge = models.CharField(max_length=24, blank=True)
    montant = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    devise = models.CharField(max_length=3, blank=True)
    statut = models.CharField(max_length=20, default='soumis')
    decision_note = models.TextField(blank=True)
    decide_par = models.UUIDField(null=True, blank=True)
    decide_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'core_rhdemande'


class RHPolitique(RHBase):
    plafond_avance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=30)
    delai_recouvrement_jours = models.PositiveIntegerField(default=30)
    class Meta:
        db_table = 'core_rhpolitique'
        constraints = [models.UniqueConstraint(fields=['societe'], name='rh_politique_societe_unique')]


class RHDette(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    demande = models.OneToOneField(RHDemande, null=True, blank=True, on_delete=models.PROTECT)
    avance_source = models.OneToOneField('tresorerie.Avance', null=True, blank=True, on_delete=models.PROTECT)
    accord = models.ForeignKey(RHDocument, on_delete=models.PROTECT)
    nature = models.CharField(max_length=30)
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    devise = models.CharField(max_length=3)
    salaire_reference = models.DecimalField(max_digits=18, decimal_places=2)
    plafond_pct = models.DecimalField(max_digits=5, decimal_places=2)
    echeancier = models.JSONField(default=list)
    motif = models.TextField()
    statut = models.CharField(max_length=24, default='attente_dfi')
    decisions = models.JSONField(default=list)
    verse_at = models.DateTimeField(null=True, blank=True)
    mouvement_id = models.UUIDField(null=True, blank=True)
    ecriture_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = 'core_rhdette'


class RHSimulation(RHBase):
    nom = models.CharField(max_length=180)
    parametres = models.JSONField(default=dict)
    resultat = models.JSONField(default=dict)

    class Meta:
        db_table = 'core_rhsimulation'


class RHDecompte(RHBase):
    agent = models.ForeignKey(RHAgent, on_delete=models.PROTECT)
    contrat = models.ForeignKey(RHContrat, on_delete=models.PROTECT)
    date_depart = models.DateField()
    motif = models.CharField(max_length=30)
    parametres = models.JSONField(default=dict)
    resultat = models.JSONField(default=dict)
    statut = models.CharField(max_length=24, default='preparation')
    controle_note = models.TextField(blank=True)

    class Meta:
        db_table = 'core_rhdecompte'


class RHPaieMois(RHBase):
    mois = models.CharField(max_length=7)
    parametres = models.JSONField(default=dict)
    statut = models.CharField(max_length=20, default='brouillon')
    decisions = models.JSONField(default=list)
    class Meta:
        db_table = 'core_rhpaiemois'
        constraints=[models.UniqueConstraint(fields=['societe','mois'],name='rh_paie_mois_unique')]


class RHBulletin(RHBase):
    periode = models.ForeignKey(RHPaieMois,on_delete=models.PROTECT)
    agent = models.ForeignKey(RHAgent,on_delete=models.PROTECT)
    contrat = models.ForeignKey(RHContrat,on_delete=models.PROTECT)
    saisie = models.JSONField(default=dict)
    resultat = models.JSONField(default=dict)
    empreinte_sources = models.CharField(max_length=64)
    ecriture_id = models.UUIDField(null=True,blank=True)
    net_comptable_usd = models.DecimalField(max_digits=18,decimal_places=2,default=0)
    class Meta:
        db_table = 'core_rhbulletin'
        constraints=[models.UniqueConstraint(fields=['periode','agent'],name='rh_bulletin_mois_agent_unique')]


class RHRetenue(RHBase):
    bulletin = models.ForeignKey(RHBulletin,on_delete=models.PROTECT)
    dette = models.ForeignKey(RHDette,on_delete=models.PROTECT)
    montant = models.DecimalField(max_digits=18,decimal_places=2)
    montant_usd = models.DecimalField(max_digits=18,decimal_places=2,default=0)
    mois_echeance = models.CharField(max_length=7)
    class Meta:
        db_table = 'core_rhretenue'
        constraints=[models.UniqueConstraint(fields=['bulletin','dette'],name='rh_retenue_bulletin_dette_unique')]


class RHPaiement(RHBase):
    bulletin = models.OneToOneField(RHBulletin,on_delete=models.PROTECT)
    mode = models.CharField(max_length=12)
    date = models.DateField()
    reference = models.CharField(max_length=64)
    montant = models.DecimalField(max_digits=18,decimal_places=2)
    devise = models.CharField(max_length=3)
    ecriture_id = models.UUIDField()
    mouvement_id = models.UUIDField(null=True,blank=True)
    compte_bancaire = models.ForeignKey('tresorerie.CompteBancaire',null=True,blank=True,on_delete=models.PROTECT)

    class Meta:
        db_table = 'core_rhpaiement'
