from django.urls import path, include
from apps.engins import views as engins_views

urlpatterns = [
    path("engins/config", engins_views.config_engins),
    path("engins/engins", engins_views.engins),
    path("engins/engins/<uuid:engin_id>", engins_views.maj_engin),
    path("engins/prestations", engins_views.prestations),
    path("engins/prestations/<uuid:prestation_id>", engins_views.maj_prestation),
    path("engins/rpe", engins_views.rpe),
    path("engins/facturer", engins_views.facturer),
]
