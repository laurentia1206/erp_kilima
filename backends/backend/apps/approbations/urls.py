from django.urls import path, include
from apps.approbations import views as decaissements_views

urlpatterns = [
    path("requisitions", decaissements_views.RequisitionViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='requisition')),
    path("requisitions/<uuid:requisition_id>/detail", decaissements_views.RequisitionViewSet.as_view({'get': 'retrieve'}, http_method_names=['get', 'options'], detail=True, basename='requisition')),
    path("requisitions/<uuid:requisition_id>/commentaires", decaissements_views.RequisitionViewSet.as_view({'get': 'commentaires'}, http_method_names=['get', 'options'], detail=True, basename='requisition')),
    path("requisitions/<uuid:requisition_id>/demander-precisions", decaissements_views.RequisitionViewSet.as_view({'post': 'demander_precisions'}, http_method_names=['post', 'options'], detail=True, basename='requisition')),
    path("requisitions/<uuid:requisition_id>/repondre", decaissements_views.RequisitionViewSet.as_view({'post': 'repondre'}, http_method_names=['post', 'options'], detail=True, basename='requisition')),
    path("requisitions/<uuid:requisition_id>/valider-demande", decaissements_views.RequisitionViewSet.as_view({'post': 'valider_demande'}, http_method_names=['post', 'options'], detail=True, basename='requisition')),
    path("ordres-depense", decaissements_views.OrdreDepenseViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='ordre_depense')),
    path("ordres-depense/<uuid:ordre_id>/valider", decaissements_views.OrdreDepenseViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=True, basename='ordre_depense')),
    path("ordres-depense/<uuid:ordre_id>/executer", decaissements_views.OrdreDepenseViewSet.as_view({'post': 'executer'}, http_method_names=['post', 'options'], detail=True, basename='ordre_depense')),
    path("ordres-depense/<uuid:ordre_id>/bon-sortie", decaissements_views.OrdreDepenseViewSet.as_view({'get': 'bon_sortie'}, http_method_names=['get', 'options'], detail=True, basename='ordre_depense')),
    path("avances", decaissements_views.AvanceViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='avance')),
    path("avances/justifier", decaissements_views.AvanceViewSet.as_view({'post': 'justifier'}, http_method_names=['post', 'options'], detail=False, basename='avance')),
    path("avances/verifier-retards", decaissements_views.AvanceViewSet.as_view({'post': 'verifier_retards'}, http_method_names=['post', 'options'], detail=False, basename='avance')),
    path("avances/blocages/<uuid:blocage_id>/lever", decaissements_views.BlocageViewSet.as_view({'post': 'lever'}, http_method_names=['post', 'options'], detail=True, basename='blocage')),
    path("approbations", decaissements_views.CentreApprobationViewSet.as_view({'get': 'centre_approbation'}, http_method_names=['get', 'options'], detail=False, basename='centre_approbation')),
    path("dashboard", decaissements_views.DashboardViewSet.as_view({'get': 'dashboard'}, http_method_names=['get', 'options'], detail=False, basename='dashboard')),
]
