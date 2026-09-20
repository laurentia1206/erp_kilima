"""Modèles : Opérations intersociétés. Noms de tables historiques conservés."""
from __future__ import annotations
import uuid
from django.db import models


class ReceptionInter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    societe_id = models.UUIDField()
    commande_id = models.UUIDField()
    numero = models.CharField(max_length=32)
    date_reception = models.DateField()
    note = models.CharField(max_length=255, null=True, blank=True)
    statut = models.CharField(max_length=16, default="confirmee")
    confirme_par = models.UUIDField(null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "reception_inter"



class LigneReceptionInter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reception_id = models.UUIDField()
    ligne_commande_id = models.UUIDField()
    qte_bon = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    qte_mauvais = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    qte_manquante = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    class Meta:
        managed = True
        db_table = "ligne_reception_inter"

