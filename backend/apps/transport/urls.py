from django.urls import path, include
from apps.transport import carburant_views as carburant_views
from apps.transport import views as transport_views

urlpatterns = [
    path("transport/config", transport_views.TransportViewSet.as_view({'get': 'get_config', 'post': 'post_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='transport')),
    path("transport/camions", transport_views.CamionViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='camion')),
    path("transport/camions/<uuid:camion_id>", transport_views.CamionViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='camion')),
    path("transport/chauffeurs", transport_views.ChauffeurViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='chauffeur')),
    path("transport/contrats", transport_views.ContratViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='contrat')),
    path("transport/contrats/<uuid:contrat_id>", transport_views.ContratViewSet.as_view({'put': 'update'}, http_method_names=['put', 'options'], detail=True, basename='contrat')),
    path("transport/courses", transport_views.CourseViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='course')),
    path("transport/courses/<uuid:course_id>/prendre-en-charge", transport_views.CourseViewSet.as_view({'post': 'prendre_en_charge'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/lier-requisition", transport_views.CourseViewSet.as_view({'post': 'lier_requisition'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/valider", transport_views.CourseViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/depart", transport_views.CourseViewSet.as_view({'post': 'depart'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/arrivee", transport_views.CourseViewSet.as_view({'post': 'arrivee'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/retour", transport_views.CourseViewSet.as_view({'post': 'retour'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/courses/<uuid:course_id>/annuler", transport_views.CourseViewSet.as_view({'post': 'annuler'}, http_method_names=['post', 'options'], detail=True, basename='course')),
    path("transport/facturer", transport_views.TransportViewSet.as_view({'post': 'facturer'}, http_method_names=['post', 'options'], detail=False, basename='transport')),
    path("transport/interventions", transport_views.InterventionViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='intervention')),
    path("transport/interventions/<uuid:intervention_id>/demarrer", transport_views.InterventionViewSet.as_view({'post': 'demarrer'}, http_method_names=['post', 'options'], detail=True, basename='intervention')),
    path("transport/interventions/<uuid:intervention_id>/terminer", transport_views.InterventionViewSet.as_view({'post': 'terminer'}, http_method_names=['post', 'options'], detail=True, basename='intervention')),
    path("transport/rapport", transport_views.TransportViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='transport')),
    path("carburant/pleins", carburant_views.PleinViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='plein')),
    path("carburant/pleins/<uuid:plein_id>", carburant_views.PleinViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='plein')),
    path("carburant/rapport", carburant_views.CarburantViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='carburant')),
    path("carburant/vehicules", carburant_views.CarburantViewSet.as_view({'get': 'vehicules'}, http_method_names=['get', 'options'], detail=False, basename='carburant')),
]
