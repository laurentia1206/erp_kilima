"""Restrictions transversales : les rôles métier demeurent nécessaires."""
from rest_framework.permissions import BasePermission
from .models import PermissionModule, SuperAdministrateur

MODULES = {
    'approbations':'Réquisitions et validations', 'tresorerie':'Trésorerie',
    'comptabilite':'Comptabilité', 'stocks':'Stocks et articles',
    'commercial':'Achats, ventes et point de vente', 'hotel':'Hôtel et cuisine',
    'transport':'Transport', 'maintenance':'Parc et maintenance', 'engins':'Engins',
    'groupe':'Gestion du groupe', 'rh':'Ressources humaines', 'pilotage':'Pilotage',
    'editions':'Documents et exports généraux', 'administration':'Administration',
    'audit':'Journal de traçabilité',
}
ACTIONS = ('consulter','creer','modifier','supprimer','executer','exporter')


def est_super_admin(user):
    return bool(user and getattr(user,'actif',False) and getattr(user,'id',None)
                and SuperAdministrateur.objects.filter(utilisateur_id=user.id).exists())


def module_de_vue(view,request=None):
    source=view.__class__.__module__
    name=view.__class__.__name__
    if source=='core.admin_views': return 'administration'
    if source=='core.audit_views': return 'audit'
    if source=='core.config_views':
        if name=='PieceJointeViewSet' and request is not None:
            from .models import PieceJointe
            kind=request.query_params.get('document_type') or (request.data.get('document_type') if isinstance(request.data,dict) else None)
            if view.kwargs.get('piece_id'):
                kind=PieceJointe.objects.filter(id=view.kwargs['piece_id']).values_list('document_type',flat=True).first()
            return {'requisition':'approbations','ordre_depense':'tresorerie','avance':'tresorerie','justification':'tresorerie',
                    'ecriture':'comptabilite','facture':'commercial','devis':'commercial','commande':'commercial',
                    'reception':'commercial','course':'transport','document_flotte':'maintenance'}.get(kind,'administration')
        return 'administration'
    if source=='core.views':
        return {'TiersViewSet':'commercial','TauxChangeViewSet':'comptabilite',
                'CompteBancaireViewSet':'tresorerie','EtatComptableViewSet':'comptabilite'}.get(name)
    if source.startswith('apps.'):
        if name in ('ArticleViewSet','StockViewSet'): return 'stocks'
        if source=='apps.approbations.views':
            if name in ('OrdreDepenseViewSet','AvanceViewSet','BlocageViewSet'): return 'tresorerie'
            if name=='DashboardViewSet': return 'pilotage'
        return source.split('.')[1]
    return None


def action_de_vue(request,view):
    action=getattr(view,'action','') or ''
    if any(word in action for word in ('export','download','telecharger','imprimer','pdf','xlsx')): return 'exporter'
    if request.method in ('GET','HEAD','OPTIONS'): return 'consulter'
    return {'create':'creer','update':'modifier','partial_update':'modifier','destroy':'supprimer'}.get(action,'executer')


class PermissionsModules(BasePermission):
    message='Cette opération est désactivée dans vos permissions. Contactez le super administrateur.'

    def has_permission(self,request,view):
        if getattr(request.user,'id',None):
            change=SuperAdministrateur.objects.filter(utilisateur_id=request.user.id,changer_mot_de_passe=True).exists()
            if change and not (view.__class__.__module__=='core.views' and view.__class__.__name__ in ('MeView','SocieteViewSet')) and not (view.__class__.__module__=='core.admin_views' and getattr(view,'action',None)=='mot_de_passe'):
                self.message='Changez votre mot de passe provisoire dans votre espace de super administration.'
                return False
        if not getattr(request.user,'id',None): return True
        if est_super_admin(request.user):
            source=view.__class__.__module__;name=view.__class__.__name__
            allowed=(source=='core.admin_views' or source=='core.audit_views'
                or source=='core.views' and name in ('MeView','SocieteViewSet')
                or source=='core.config_views' and (name in ('UtilisateurViewSet','RoleViewSet','AffectationViewSet')
                    or name=='SocieteViewSet' and getattr(view,'action',None)=='list'))
            if not allowed:self.message='Le super administrateur gère uniquement les utilisateurs et leurs habilitations. Les opérations des sociétés lui sont interdites.'
            return allowed
        module=module_de_vue(view,request)
        if not module: return True
        rule=PermissionModule.objects.filter(utilisateur_id=request.user.id,module=module).first()
        if rule is None: return True
        return rule.consulter and bool(getattr(rule,action_de_vue(request,view)))
