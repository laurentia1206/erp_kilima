from django.urls import path, include
from apps.maintenance import documents_views as documents_views
from apps.maintenance import views as maintenance_views

urlpatterns = [
    path("maintenance/parc", maintenance_views.parc),
    path("maintenance/plans", maintenance_views.plans),
    path("maintenance/plans/<uuid:plan_id>", maintenance_views.maj_plan),
    path("maintenance/plans/<uuid:plan_id>/planifier", maintenance_views.planifier),
    path("flotte/documents", documents_views.documents),
    path("flotte/documents/<uuid:document_id>", documents_views.maj_document),
]
