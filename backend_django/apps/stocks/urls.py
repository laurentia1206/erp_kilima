from django.urls import path, include
from apps.stocks import views as depots_views
from apps.stocks import inventaires_views as inventaires_views

urlpatterns = [
    path("stock/depots", depots_views.depots),
    path("stock/depots/<uuid:depot_id>", depots_views.maj_depot),
    path("stock/depots-etat", depots_views.etat_depot),
    path("stock/transferts", depots_views.transferts),
    path("stock/inventaires", inventaires_views.inventaires),
    path("stock/inventaires/<uuid:inventaire_id>/decision", inventaires_views.decision),
]
