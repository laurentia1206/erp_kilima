from django.urls import path, include
from apps.transport import carburant_views as carburant_views
from apps.transport import views as transport_views

urlpatterns = [
    path("transport/config", transport_views.config_transport),
    path("transport/camions", transport_views.camions),
    path("transport/camions/<uuid:camion_id>", transport_views.maj_camion),
    path("transport/chauffeurs", transport_views.chauffeurs),
    path("transport/contrats", transport_views.contrats),
    path("transport/contrats/<uuid:contrat_id>", transport_views.modifier_contrat),
    path("transport/courses", transport_views.courses),
    path("transport/courses/<uuid:course_id>/prendre-en-charge", transport_views.prendre_en_charge),
    path("transport/courses/<uuid:course_id>/lier-requisition", transport_views.lier_requisition),
    path("transport/courses/<uuid:course_id>/valider", transport_views.valider_course),
    path("transport/courses/<uuid:course_id>/depart", transport_views.depart_course),
    path("transport/courses/<uuid:course_id>/arrivee", transport_views.arrivee_course),
    path("transport/courses/<uuid:course_id>/retour", transport_views.retour_course),
    path("transport/courses/<uuid:course_id>/annuler", transport_views.annuler_course),
    path("transport/facturer", transport_views.facturer_courses),
    path("transport/interventions", transport_views.interventions),
    path("transport/interventions/<uuid:intervention_id>/demarrer", transport_views.demarrer_intervention),
    path("transport/interventions/<uuid:intervention_id>/terminer", transport_views.terminer_intervention),
    path("transport/rapport", transport_views.rapport_transport),
    path("carburant/pleins", carburant_views.pleins),
    path("carburant/pleins/<uuid:plein_id>", carburant_views.maj_plein),
    path("carburant/rapport", carburant_views.rapport),
]
