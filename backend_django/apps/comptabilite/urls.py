from django.urls import path, include
from apps.comptabilite import analytique_views as analytique_views
from apps.comptabilite import views as compta_views
from apps.comptabilite import tva_views as tva_views
from core import views as views

urlpatterns = [
    path("comptabilite/tva-mensuelle", tva_views.preparation),
    path("comptabilite/tva-mensuelle/dossier", tva_views.dossier),
    path("comptabilite/balance", views.balance),
    path("comptabilite/ecritures", compta_views.lister_ecritures),
    path("comptabilite/ecritures/saisie", compta_views.saisir_ecriture),
    path("comptabilite/ecritures/<uuid:ecriture_id>/valider", compta_views.valider_ecriture),
    path("comptabilite/grand-livre", compta_views.grand_livre),
    path("comptabilite/plan-comptable", compta_views.plan_comptable),
    path("comptabilite/plan-comptable/charger-syscohada", compta_views.charger_syscohada),
    path("comptabilite/plan-comptable/<uuid:compte_id>", compta_views.maj_compte),
    path("comptabilite/journaux", compta_views.journaux),
    path("comptabilite/lettrage", compta_views.lettrage),
    path("comptabilite/delettrage", compta_views.delettrer),
    path("comptabilite/rapprochement", compta_views.rapprochement),
    path("comptabilite/rapprochement/a-pointer", compta_views.rappro_a_pointer),
    path("comptabilite/rapprochement/<uuid:rappro_id>/annuler", compta_views.annuler_rapprochement),
    path("comptabilite/compte-resultat", compta_views.compte_resultat),
    path("comptabilite/bilan", compta_views.bilan),
    path("comptabilite/tft", compta_views.tft),
    path("comptabilite/cockpit", compta_views.cockpit),
    path("comptabilite/comptes-config", compta_views.comptes_config),
    path("comptabilite/revue-config", compta_views.revue_config),
    path("analytique/axes", analytique_views.axes),
    path("analytique/axes/<uuid:axe_id>/sections", analytique_views.creer_section),
    path("analytique/sections/<uuid:section_id>", analytique_views.maj_section),
    path("analytique/lignes", analytique_views.lignes_a_ventiler),
    path("analytique/ventiler", analytique_views.ventiler),
    path("analytique/rapport", analytique_views.rapport),
]
