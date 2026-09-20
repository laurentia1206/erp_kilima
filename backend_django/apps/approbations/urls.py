from django.urls import path, include
from apps.approbations import views as decaissements_views

urlpatterns = [
    path("requisitions", decaissements_views.requisitions),
    path("requisitions/<uuid:requisition_id>/detail", decaissements_views.requisition_detail),
    path("requisitions/<uuid:requisition_id>/commentaires", decaissements_views.requisition_commentaires),
    path("requisitions/<uuid:requisition_id>/demander-precisions", decaissements_views.demander_precisions),
    path("requisitions/<uuid:requisition_id>/repondre", decaissements_views.repondre),
    path("requisitions/<uuid:requisition_id>/valider-demande", decaissements_views.valider_demande),
    path("ordres-depense", decaissements_views.ordres_depense),
    path("ordres-depense/<uuid:ordre_id>/valider", decaissements_views.valider_sortie),
    path("ordres-depense/<uuid:ordre_id>/executer", decaissements_views.executer),
    path("ordres-depense/<uuid:ordre_id>/bon-sortie", decaissements_views.bon_sortie),
    path("avances", decaissements_views.lister_avances),
    path("avances/justifier", decaissements_views.justifier),
    path("avances/verifier-retards", decaissements_views.verifier_retards),
    path("avances/blocages/<uuid:blocage_id>/lever", decaissements_views.lever_blocage),
    path("approbations", decaissements_views.centre_approbation),
    path("dashboard", decaissements_views.dashboard),
]
