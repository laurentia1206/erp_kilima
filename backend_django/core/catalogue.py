"""Contrôles des créations de fiches, sans fusionner les données historiques."""
import unicodedata
from django.db import connection
from django.db.models import F, Q
from rest_framework.exceptions import APIException
from .models import Societe, Tiers


def tiers_visibles(sid):
    return Tiers.objects.filter(Q(societe_id=sid) | Q(societe_id__isnull=True))


def tiers_disponible(tiers, sid):
    return bool(tiers and tiers.actif and (tiers.societe_id is None or str(tiers.societe_id) == str(sid)))


def normaliser(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).casefold().split())


class DoublonCatalogue(APIException):
    status_code = 409
    default_code = 'doublon_catalogue'


def verrouiller_catalogue(sid):
    # Appelé dans la transaction de création. SQLite n'a pas de verrou de ligne.
    if connection.vendor == 'sqlite':
        Societe.objects.filter(id=sid).update(nom=F('nom'))
    else:
        Societe.objects.select_for_update().get(id=sid)


def verifier_doublon(query, payload, champ_nom, exclure_id=None):
    if exclure_id:
        query = query.exclude(id=exclure_id)
    code = normaliser(payload.get('code'))
    nom = normaliser(payload.get(champ_nom))
    barcode = str(payload.get('code_barres') or '').strip()
    proches = []
    for obj in query:
        meme_code = bool(code and normaliser(obj.code) == code)
        meme_barcode = bool(barcode and barcode == str(getattr(obj, 'code_barres', '') or '').strip())
        meme_nom = bool(nom and normaliser(getattr(obj, champ_nom)) == nom)
        if meme_code or meme_barcode:
            raise DoublonCatalogue({'detail':f'Une fiche existe déjà avec ce code ou code-barres : {obj.code} — {getattr(obj, champ_nom)}. Sélectionnez-la plutôt que la recréer.',
                                    'existing_id':str(obj.id), 'can_confirm_similar':False})
        if meme_nom:
            proches.append(obj)
    if proches and payload.get('confirmer_homonyme') is not True:
        raise DoublonCatalogue({'detail':'Une fiche porte déjà ce nom dans cette société. Sélectionnez-la ou confirmez explicitement qu’il s’agit d’une fiche distincte.',
                                'existing_id':str(proches[0].id), 'can_confirm_similar':True})
