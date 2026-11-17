"""Hôtel : pièce d'identité obligatoire (enregistrée ET jointe) avant le
check-in, et changement de chambre tant que le client n'est pas arrivé."""
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role
from apps.hotel.models import Chambre, Sejour


class HotelIdentiteTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QH', nom='Guest House test')
        self.recep = Utilisateur.objects.create(email='recep@test.local',
                                                nom='Réception',
                                                password_hash='unused')
        role, _ = Role.objects.get_or_create(code='RECEPTIONNISTE',
                                             defaults={'libelle': 'Réception'})
        _inserer_affectation(self.recep.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(self.recep)
        self.ch1 = Chambre.objects.create(societe_id=self.soc.id, numero='101',
                                          tarif_nuit_usd=40)
        self.ch2 = Chambre.objects.create(societe_id=self.soc.id, numero='102',
                                          tarif_nuit_usd=55)

    def _reserver(self, chambre, jours=0, **extra):
        arrivee = date.today() + timedelta(days=jours)
        corps = {'chambre_id': str(chambre.id), 'client_nom': 'MUKENDI Alain',
                 'date_arrivee': arrivee.isoformat(),
                 'date_depart_prevue': (arrivee + timedelta(days=2)).isoformat(),
                 **extra}
        return self.client.post(
            f'/api/hotel/sejours?societe_id={self.soc.id}', corps, format='json')

    def _joindre(self, sejour_id):
        return self.client.post(
            '/api/pieces-jointes',
            {'document_type': 'sejour', 'document_id': str(sejour_id),
             'file': SimpleUploadedFile('passeport.jpg', b'fake-scan',
                                        content_type='image/jpeg')},
            format='multipart')

    def test_walk_in_exige_la_piece(self):
        r = self._reserver(self.ch1, arrivee_immediate=True)
        self.assertEqual(r.status_code, 422)
        self.assertIn("pièce", r.json()['detail'])
        r = self._reserver(self.ch1, arrivee_immediate=True,
                           piece_type='passeport', piece_numero='OP1234567')
        self.assertEqual(r.status_code, 201, r.content)
        corps = r.json()
        self.assertEqual(corps['statut'], 'arrivee')
        self.assertEqual(corps['piece_type'], 'passeport')
        self.assertEqual(corps['piece_numero'], 'OP1234567')

    def test_checkin_exige_piece_enregistree_et_jointe(self):
        r = self._reserver(self.ch1)
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()['id']
        url = f'/api/hotel/sejours/{sid}/checkin?societe_id={self.soc.id}'
        # 1. Ni enregistrée ni jointe.
        r = self.client.post(url, {}, format='json')
        self.assertEqual(r.status_code, 422)
        self.assertIn('pièce', r.json()['detail'])
        # 2. Enregistrée (via PATCH) mais pas jointe.
        r = self.client.patch(f'/api/hotel/sejours/{sid}?societe_id={self.soc.id}',
                              {'piece_type': 'carte_electeur',
                               'piece_numero': 'CE-998877'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(url, {}, format='json')
        self.assertEqual(r.status_code, 422)
        self.assertIn('joignez', r.json()['detail'])
        # 3. Jointe -> check-in accepté.
        self.assertEqual(self._joindre(sid).status_code, 201)
        r = self.client.post(url, {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['statut'], 'arrivee')
        # Type inconnu refusé.
        self.assertEqual(self.client.patch(
            f'/api/hotel/sejours/{sid}?societe_id={self.soc.id}',
            {'piece_type': 'badge', 'piece_numero': 'X'},
            format='json').status_code, 422)

    def test_changement_de_chambre_avant_arrivee(self):
        r = self._reserver(self.ch1, jours=3)
        sid = r.json()['id']
        # Un autre séjour occupe la chambre 102 sur les mêmes dates.
        self._reserver(self.ch2, jours=3)
        patch = f'/api/hotel/sejours/{sid}?societe_id={self.soc.id}'
        r = self.client.patch(patch, {'chambre_id': str(self.ch2.id)},
                              format='json')
        self.assertEqual(r.status_code, 409)
        # Libération de la 102 puis changement : tarif recalé sur la chambre.
        Sejour.objects.filter(chambre_id=self.ch2.id).exclude(id=sid)\
            .update(statut='annulee')
        r = self.client.patch(patch, {'chambre_id': str(self.ch2.id)},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['chambre'], '102')
        self.assertEqual(r.json()['tarif_nuit_usd'], 55.0)
        # Après l'arrivée, la chambre ne se change plus par ce circuit.
        s = Sejour.objects.get(id=sid)
        s.statut = 'arrivee'
        s.save(update_fields=['statut'])
        r = self.client.patch(patch, {'chambre_id': str(self.ch1.id)},
                              format='json')
        self.assertEqual(r.status_code, 409)
