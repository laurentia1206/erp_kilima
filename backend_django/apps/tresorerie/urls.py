from django.urls import path, include
from apps.tresorerie import beneficiaires as beneficiaires
from apps.tresorerie import views as caisse_views
from core import views as views

urlpatterns = [
    path("beneficiaires", beneficiaires.BeneficiaireViewSet.as_view({'get': 'get_beneficiaires', 'post': 'post_beneficiaires'}, http_method_names=['get', 'post', 'options'], detail=False, basename='beneficiaire')),
    path("caisses", caisse_views.CaisseViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='caisse')),
    path("caisses/<uuid:caisse_id>", caisse_views.CaisseViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='caisse')),
    path("comptes-bancaires", views.CompteBancaireViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='compte_bancaire')),
    path("caisse/journal", caisse_views.JournalCaisseViewSet.as_view({'get': 'caisse_journal'}, http_method_names=['get', 'options'], detail=False, basename='journal_caisse')),
    path("caisse/session/<uuid:session_id>/rapport-z", caisse_views.SessionCaisseViewSet.as_view({'get': 'rapport_z'}, http_method_names=['get', 'options'], detail=True, basename='session_caisse')),
    path("caisse/mouvement/<uuid:mvt_id>/bon", caisse_views.MouvementCaisseViewSet.as_view({'get': 'bon'}, http_method_names=['get', 'options'], detail=True, basename='mouvement_caisse')),
    path("caisse/<uuid:caisse_id>/ouvrir", caisse_views.CaisseViewSet.as_view({'post': 'ouvrir'}, http_method_names=['post', 'options'], detail=True, basename='caisse')),
    path("caisse/<uuid:caisse_id>/session", caisse_views.CaisseViewSet.as_view({'get': 'session'}, http_method_names=['get', 'options'], detail=True, basename='caisse')),
    path("caisse/<uuid:caisse_id>/mouvement", caisse_views.CaisseViewSet.as_view({'post': 'mouvement'}, http_method_names=['post', 'options'], detail=True, basename='caisse')),
    path("caisse/<uuid:caisse_id>/operation", caisse_views.CaisseViewSet.as_view({'post': 'operation'}, http_method_names=['post', 'options'], detail=True, basename='caisse')),
    path("caisse/<uuid:caisse_id>/journal", caisse_views.CaisseViewSet.as_view({'get': 'journal'}, http_method_names=['get', 'options'], detail=True, basename='caisse')),
    path("caisse/<uuid:caisse_id>/cloturer", caisse_views.CaisseViewSet.as_view({'post': 'cloturer'}, http_method_names=['post', 'options'], detail=True, basename='caisse')),
    path("transferts", caisse_views.TransfertViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='transfert')),
    path("transferts/<uuid:transfert_id>/valider", caisse_views.TransfertViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=True, basename='transfert')),
    path("transferts/<uuid:transfert_id>/rejeter", caisse_views.TransfertViewSet.as_view({'post': 'rejeter'}, http_method_names=['post', 'options'], detail=True, basename='transfert')),
]
