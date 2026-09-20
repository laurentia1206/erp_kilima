from django.urls import path, include
from apps.tresorerie import beneficiaires as beneficiaires
from apps.tresorerie import views as caisse_views
from core import views as views

urlpatterns = [
    path("beneficiaires", beneficiaires.beneficiaires),
    path("caisses", caisse_views.caisses),
    path("caisses/<uuid:caisse_id>", caisse_views.maj_caisse),
    path("comptes-bancaires", views.lister_banques),
    path("caisse/journal", caisse_views.caisse_journal),
    path("caisse/session/<uuid:session_id>/rapport-z", caisse_views.rapport_z),
    path("caisse/mouvement/<uuid:mvt_id>/bon", caisse_views.bon_mouvement),
    path("caisse/<uuid:caisse_id>/ouvrir", caisse_views.ouvrir),
    path("caisse/<uuid:caisse_id>/session", caisse_views.session_courante),
    path("caisse/<uuid:caisse_id>/mouvement", caisse_views.mouvement),
    path("caisse/<uuid:caisse_id>/operation", caisse_views.operation),
    path("caisse/<uuid:caisse_id>/journal", caisse_views.journal_session),
    path("caisse/<uuid:caisse_id>/cloturer", caisse_views.cloturer),
    path("transferts", caisse_views.transferts),
    path("transferts/<uuid:transfert_id>/valider", caisse_views.valider_transfert),
    path("transferts/<uuid:transfert_id>/rejeter", caisse_views.rejeter_transfert),
]
