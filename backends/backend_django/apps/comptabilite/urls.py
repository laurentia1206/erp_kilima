from django.urls import path, include
from apps.comptabilite import analytique_views as analytique_views
from apps.comptabilite import views as compta_views
from apps.comptabilite import tva_views as tva_views
from core import views as views

urlpatterns = [
    path("comptabilite/tva-mensuelle", tva_views.PreparationTVAViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='preparation_t_v_a')),
    path("comptabilite/tva-mensuelle/dossier", tva_views.PreparationTVAViewSet.as_view({'get': 'get_dossier', 'post': 'post_dossier'}, http_method_names=['get', 'post', 'options'], detail=False, basename='preparation_t_v_a')),
    path("comptabilite/balance", views.EtatComptableViewSet.as_view({'get': 'balance'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/ecritures", compta_views.EcritureViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='ecriture')),
    path("comptabilite/ecritures/saisie", compta_views.EcritureViewSet.as_view({'post': 'saisie'}, http_method_names=['post', 'options'], detail=False, basename='ecriture')),
    path("comptabilite/ecritures/<uuid:ecriture_id>/valider", compta_views.EcritureViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=True, basename='ecriture')),
    path("comptabilite/grand-livre", compta_views.EtatComptableViewSet.as_view({'get': 'grand_livre'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/plan-comptable", compta_views.CompteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='compte')),
    path("comptabilite/plan-comptable/charger-syscohada", compta_views.CompteViewSet.as_view({'post': 'charger_syscohada'}, http_method_names=['post', 'options'], detail=False, basename='compte')),
    path("comptabilite/plan-comptable/<uuid:compte_id>", compta_views.CompteViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='compte')),
    path("comptabilite/journaux", compta_views.JournalViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='journal')),
    path("comptabilite/lettrage", compta_views.EtatComptableViewSet.as_view({'get': 'get_lettrage', 'post': 'post_lettrage'}, http_method_names=['get', 'post', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/delettrage", compta_views.EtatComptableViewSet.as_view({'post': 'delettrage'}, http_method_names=['post', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/rapprochement", compta_views.RapprochementViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='rapprochement')),
    path("comptabilite/rapprochement/a-pointer", compta_views.RapprochementViewSet.as_view({'get': 'a_pointer'}, http_method_names=['get', 'options'], detail=False, basename='rapprochement')),
    path("comptabilite/rapprochement/<uuid:rappro_id>/annuler", compta_views.RapprochementViewSet.as_view({'post': 'annuler'}, http_method_names=['post', 'options'], detail=True, basename='rapprochement')),
    path("comptabilite/compte-resultat", compta_views.EtatComptableViewSet.as_view({'get': 'compte_resultat'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/bilan", compta_views.EtatComptableViewSet.as_view({'get': 'bilan'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/tft", compta_views.EtatComptableViewSet.as_view({'get': 'tft'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/cockpit", compta_views.EtatComptableViewSet.as_view({'get': 'cockpit'}, http_method_names=['get', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/comptes-config", compta_views.EtatComptableViewSet.as_view({'get': 'get_comptes_config', 'post': 'post_comptes_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='etat_comptable')),
    path("comptabilite/revue-config", compta_views.EtatComptableViewSet.as_view({'get': 'get_revue_config', 'post': 'post_revue_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='etat_comptable')),
    path("analytique/axes", analytique_views.AxeViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='axe')),
    path("analytique/axes/<uuid:axe_id>/sections", analytique_views.AxeViewSet.as_view({'post': 'sections'}, http_method_names=['post', 'options'], detail=True, basename='axe')),
    path("analytique/sections/<uuid:section_id>", analytique_views.SectionViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='section')),
    path("analytique/lignes", analytique_views.AnalytiqueViewSet.as_view({'get': 'lignes'}, http_method_names=['get', 'options'], detail=False, basename='analytique')),
    path("analytique/ventiler", analytique_views.AnalytiqueViewSet.as_view({'post': 'ventiler'}, http_method_names=['post', 'options'], detail=False, basename='analytique')),
    path("analytique/rapport", analytique_views.AnalytiqueViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='analytique')),
]
