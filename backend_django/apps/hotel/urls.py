from django.urls import path, include
from apps.hotel import cuisine_views as cuisine_views
from apps.hotel import views as hotel_views

urlpatterns = [
    path("hotel/clients", hotel_views.clients),
    path("cuisine/config", cuisine_views.config_cuisine),
    path("cuisine/fiches", cuisine_views.fiches),
    path("cuisine/fiches/<uuid:fiche_id>", cuisine_views.supprimer_fiche),
    path("cuisine/consommations", cuisine_views.consommations),
    path("cuisine/rapport", cuisine_views.rapport_cuisine),
    path("hotel/chambres", hotel_views.chambres),
    path("hotel/chambres/<uuid:chambre_id>", hotel_views.maj_chambre),
    path("hotel/sejours", hotel_views.sejours),
    path("hotel/sejours/<uuid:sejour_id>", hotel_views.maj_sejour),
    path("hotel/sejours/<uuid:sejour_id>/checkin", hotel_views.checkin),
    path("hotel/sejours/<uuid:sejour_id>/annuler", hotel_views.annuler_sejour),
    path("hotel/sejours/<uuid:sejour_id>/folio", hotel_views.folio),
    path("hotel/sejours/<uuid:sejour_id>/lignes", hotel_views.ajouter_ligne),
    path("hotel/sejours/<uuid:sejour_id>/lignes/<uuid:ligne_id>", hotel_views.supprimer_ligne),
    path("hotel/sejours/<uuid:sejour_id>/checkout", hotel_views.checkout),
    path("hotel/planning", hotel_views.planning),
    path("hotel/rapport", hotel_views.rapport_hotel),
]
