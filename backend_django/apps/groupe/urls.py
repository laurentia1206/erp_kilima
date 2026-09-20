from django.urls import path, include
from apps.groupe import views as intersociete_views

urlpatterns = [
    path("intersociete/commandes/<uuid:commande_id>/receptionner", intersociete_views.receptionner_po),
    path("intersociete/receptions", intersociete_views.receptions_intersociete),
    path("intersociete/receptions/<uuid:reception_id>", intersociete_views.reception_detail_ou_annulation),
    path("intersociete/receptions/<uuid:reception_id>/confirmer", intersociete_views.confirmer_reception),
    path("intersociete/tracer", intersociete_views.tracer),
    path("intersociete/badges", intersociete_views.badges),
    path("intersociete/liaisons", intersociete_views.liaisons),
    path("intersociete/lier", intersociete_views.lier_tiers),
    path("intersociete/positions", intersociete_views.positions),
    path("intersociete/factures", intersociete_views.factures_intragroupe),
    path("intersociete/factures/<uuid:facture_id>/regler", intersociete_views.regler_intersociete),
]
