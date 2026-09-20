from django.urls import path, include
from apps.rh import finances as rh_finances
from apps.rh import paie_mensuelle_views as rh_mensuel_views
from apps.rh import paie_views as rh_paie_views
from apps.rh import views as rh_views

urlpatterns = [
    path('rh/paies', rh_mensuel_views.periodes),
    path('rh/paies/<uuid:periode_id>', rh_mensuel_views.detail),
    path('rh/paies/<uuid:periode_id>/preparer', rh_mensuel_views.preparer),
    path('rh/paies/<uuid:periode_id>/decision', rh_mensuel_views.decision),
    path('rh/bulletins/<uuid:bulletin_id>/payer', rh_mensuel_views.payer),
    path('rh/contrats/<uuid:contrat_id>/composition', rh_mensuel_views.composition),
    path('rh/simuler', rh_paie_views.simuler),
    path('rh/simulations', rh_paie_views.simulations),
    path('rh/decomptes', rh_paie_views.decomptes),
    path('rh/politique', rh_finances.parametres),
    path('rh/avances-a-justifier', rh_finances.sources),
    path('rh/dettes', rh_finances.dettes),
    path('rh/dettes/<uuid:dette_id>/decision', rh_finances.decision),
    path('rh/dettes/<uuid:dette_id>/accord', rh_finances.accord),
    path('rh/a-payer', rh_finances.a_payer),
    path('rh/dettes/<uuid:dette_id>/verser', rh_finances.verser),
    path('rh/organisation', rh_views.organisation),
    path('rh/agents', rh_views.agents),
    path('rh/agents/<uuid:agent_id>/dossier', rh_views.dossier),
    path('rh/agents/<uuid:agent_id>/documents', rh_views.documents),
    path('rh/documents/<uuid:document_id>', rh_views.document),
    path('rh/pointages', rh_views.pointages),
    path('rh/pointages/<uuid:pointage_id>/decision', rh_views.pointage_decision),
    path('rh/demandes', rh_views.demandes),
]
