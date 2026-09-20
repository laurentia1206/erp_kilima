"""Schémas explicites des ressources ; mutations via les actions métier validées."""
from rest_framework import serializers
from apps.stocks.models import Depot
from apps.stocks.models import InventaireDepot
from apps.stocks.models import TransfertDepot
from apps.stocks.models import StockDepot
from apps.commercial.models import PointVente


class DepotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Depot
        fields = ('id', 'societe_id', 'code', 'libelle', 'type', 'actif', 'created_by', 'created_at')
        read_only_fields = fields

    def to_representation(self, instance):
        d = instance
        soldes = StockDepot.objects.filter(depot_id=d.id)
        valeur = round(sum(float(s.valeur) for s in soldes), 2)
        refs = sum(1 for s in soldes if float(s.qte) > 0)
        pv = PointVente.objects.filter(depot_id=d.id, actif=True).first()
        return {"id": str(d.id), "code": d.code, "libelle": d.libelle,
                "type": d.type, "actif": bool(d.actif),
                "point_vente": pv.libelle if pv else None,
                "valeur_stock_usd": valeur, "nb_references": refs}


class InventaireDepotSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventaireDepot
        fields = ('id', 'societe_id', 'numero', 'statut', 'valide_par', 'valide_at', 'depot_id', 'date_inventaire', 'valeur_theorique', 'valeur_reelle', 'ecart_valeur', 'note', 'ecriture_id', 'created_by', 'created_at')
        read_only_fields = fields


class TransfertDepotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransfertDepot
        fields = ('id', 'societe_id', 'numero', 'depot_source_id', 'depot_cible_id', 'date_transfert', 'note', 'created_by', 'created_at')
        read_only_fields = fields


