"""Consultation et exports d'audit : données relues et filtrées côté serveur."""
from datetime import date, datetime, time, timedelta, timezone
import json
import re
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import Q, Max
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework import serializers

from .models import AuditLog, Societe, Utilisateur, UtilisateurSociete
from .auth import assert_acces_societe, assert_role
from .audit import append_event, clean
from .audit_schema import build_plan, names, statements
from .viewsets import MetierMetadata


def identifier(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError):raise ValidationError('Identifiant invalide.')


def entier(value,default,minimum=1,maximum=10000):
    try:n=int(value) if value is not None else default
    except (ValueError,TypeError):raise ValidationError('Nombre invalide.')
    if not minimum<=n<=maximum:raise ValidationError('Nombre hors limites.')
    return n


def public_record(row,users,detail=False):
    result={'id':row.id,'date':row.horodatage.isoformat()+'Z' if row.horodatage else None,
        'utilisateur_id':str(row.utilisateur_id) if row.utilisateur_id else None,
        'utilisateur':users.get(row.utilisateur_id,str(row.utilisateur_id)) if row.utilisateur_id else 'Système / non identifié',
        'action':row.action,'module':row.module,'categorie':row.categorie,'table':row.table_cible,
        'document':row.enregistrement_id,'adresse_ip':row.adresse_ip,'requete_id':str(row.requete_id) if row.requete_id else None,
        'champs_modifies':row.champs_modifies,'methode':row.methode,'chemin':row.chemin,'origine':row.origine}
    if detail:
        result.update(avant=clean(row.ancienne_valeur,row.table_cible),apres=clean(row.nouvelle_valeur,row.table_cible))
    return result


class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model=AuditLog
        fields=('id','action','table_cible','enregistrement_id','horodatage')
        read_only_fields=fields


class AuditViewSet(ReadOnlyModelViewSet):
    serializer_class=AuditSerializer
    queryset=AuditLog.objects.none()
    http_method_names=['get','options']
    metadata_class=MetierMetadata
    lookup_url_kwarg='audit_id'

    def finalize_response(self,request,response,*args,**kwargs):
        response=super().finalize_response(request,response,*args,**kwargs)
        response['Cache-Control']='no-store'
        return response

    def scoped(self):
        request=self.request
        scope=request.query_params.get('portee','societe')
        from .permissions import est_super_admin
        if est_super_admin(request.user):
            if scope!='global':raise PermissionDenied('Le super administrateur consulte uniquement le journal des utilisateurs.')
            self.company=None
            return AuditLog.objects.filter(table_cible__in=('utilisateur','utilisateur_societe','role','permission_module','super_administrateur','authentification'))
        if scope not in ('societe','partage','global'):raise ValidationError('Portée inconnue.')
        if scope=='global':
            from .permissions import est_super_admin
            if not est_super_admin(request.user) and not UtilisateurSociete.objects.filter(utilisateur_id=request.user.id,role__code='ADMIN_SYS').exists():
                raise PermissionDenied('Les événements globaux sont réservés à ADMIN_SYS.')
            self.company=None
            return AuditLog.objects.filter(societe_id__isnull=True)
        sid=identifier(request.query_params.get('societe_id'))
        assert_role(assert_acces_societe(request.user,sid),{'DFI','ADMIN_SYS'})
        self.company=Societe.objects.get(id=sid)
        if scope=='partage':
            return AuditLog.objects.filter(societe_id__isnull=True,table_cible='tiers',categorie='donnees')
        return AuditLog.objects.filter(societe_id=sid)

    def get_queryset(self):
        q=self.scoped();p=self.request.query_params
        for param,field in [('module','module'),('action','action'),('categorie','categorie'),('table','table_cible'),('document','enregistrement_id')]:
            if p.get(param):q=q.filter(**{field:p[param][:128]})
        for param in ('utilisateur_id','requete_id'):
            if p.get(param):q=q.filter(**{param:identifier(p[param])})
        dates={}
        for key in ('du','au'):
            if p.get(key):
                try:dates[key]=date.fromisoformat(p[key])
                except ValueError:raise ValidationError('Date invalide.')
        if dates.get('du') and dates.get('au') and dates['du']>dates['au']:raise ValidationError('La date de fin précède le début.')
        for key,day in dates.items():
            stamp=datetime.combine(day+(timedelta(days=1) if key=='au' else timedelta()),time.min,tzinfo=ZoneInfo(settings.TIME_ZONE)).astimezone(timezone.utc).replace(tzinfo=None)
            q=q.filter(**{'horodatage__gte' if key=='du' else 'horodatage__lt':stamp})
        if p.get('q'):
            term=p['q'][:100]
            q=q.filter(Q(action__icontains=term)|Q(table_cible__icontains=term)|Q(enregistrement_id__icontains=term))
        if p.get('borne'):q=q.filter(id__lte=entier(p['borne'],1,maximum=2**63-1))
        return q.order_by('-id')

    def list(self,request):
        q=self.get_queryset();page=entier(request.query_params.get('page'),1);size=50
        bound=q.aggregate(n=Max('id'))['n'] or 0
        total=q.count();rows=list(q[(page-1)*size:page*size])
        users=dict(Utilisateur.objects.filter(id__in=[r.utilisateur_id for r in rows if r.utilisateur_id]).values_list('id','nom'))
        # Un nom d'utilisateur du filtre ne doit pas révéler les comptes hors périmètre.
        scope=self.scoped()
        actors=list(Utilisateur.objects.filter(id__in=scope.exclude(utilisateur_id=None).values('utilisateur_id')).order_by('nom').values('id','nom'))
        return Response({'resultats':[public_record(r,users) for r in rows], 'total':total,'page':page,'taille_page':size,'borne':int(request.query_params.get('borne') or bound),
            'utilisateurs':actors,'modules':list(scope.order_by('module').values_list('module',flat=True).distinct()),
            'historique':'Les anciennes traces sans société fiable sont réservées à l’administration ; aucun historique manquant n’est reconstitué.'})

    def retrieve(self,request,*args,**kwargs):
        obj=self.get_object()
        users=dict(Utilisateur.objects.filter(id=obj.utilisateur_id).values_list('id','nom'))
        return Response(public_record(obj,users,True))

    @action(detail=False,methods=['get'])
    def exporter(self,request):
        q=self.get_queryset();fmt=request.query_params.get('format_export','xlsx')
        if fmt not in ('xlsx','pdf'):raise ValidationError('Format attendu : xlsx ou pdf.')
        limit=2000 if fmt=='xlsx' else 500
        rows=list(q[:limit+1])
        if len(rows)>limit:raise ValidationError(f'Export limité à {limit} événements. Réduisez la période ou les filtres.')
        if not rows:raise ValidationError('Aucun événement dans cette sélection.')
        from apps.editions.views import normaliser, pdf, xlsx, identite
        users=dict(Utilisateur.objects.filter(id__in=[r.utilisateur_id for r in rows if r.utilisateur_id]).values_list('id','nom'))
        local=ZoneInfo(settings.TIME_ZONE)
        lines=[]
        for row in rows:
            r=public_record(row,users,True)
            stamp=row.horodatage.replace(tzinfo=timezone.utc).astimezone(local).strftime('%d/%m/%Y %H:%M:%S') if row.horodatage else 'Non daté'
            line=[row.id,stamp,r['utilisateur'],row.action,row.module,row.table_cible,row.enregistrement_id or '',', '.join(row.champs_modifies or [])]
            if fmt=='xlsx':line += [r['utilisateur_id'] or '',row.categorie,row.adresse_ip or '',r['requete_id'] or '',row.methode,row.chemin,json.dumps(r['avant'],ensure_ascii=False),json.dumps(r['apres'],ensure_ascii=False)]
            lines.append(line)
        cols=['N°','Date / heure','Utilisateur','Action','Module','Table','Document','Champs modifiés']
        if fmt=='xlsx':cols+=['ID utilisateur','Type','Adresse IP','Requête','Méthode','Chemin','Avant','Après']
        filters={k:v for k,v in request.query_params.items() if k not in ('page','format_export')}
        description=' · '.join(f'{k} : {v[:100]}' for k,v in filters.items())
        spec=normaliser({'titre':'Journal de traçabilité','sous_titre':description,
            'blocs':[{'type':'texte','texte':f'{len(rows)} événements · Heures {settings.TIME_ZONE} · Export confidentiel. Les champs sensibles sont masqués.'},
                {'type':'table','colonnes':cols,'lignes':lines}]})
        identity=identite(self.company) if self.company else {'nom':'ERP Kilima — Administration','code':'GROUPE','ville':'','references':'Événements globaux'}
        content=xlsx(spec,identity) if fmt=='xlsx' else pdf(spec,identity)
        append_event(request.user.id,'EXPORT_AUDIT','audit_log',new={'format':fmt,'nombre':len(rows),'filtres':filters},societe_id=self.company.id if self.company else None,categorie='consultation',module='audit')
        response=HttpResponse(content,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if fmt=='xlsx' else 'application/pdf')
        response['Content-Disposition']=content_disposition_header(True,'journal-audit.'+fmt)
        response['Cache-Control']='no-store'
        return response

    @action(detail=False,methods=['get'])
    def protection(self,request):
        self.scoped()
        from django.apps import apps
        plan=build_plan(apps)
        expected={name for spec in plan for name in names(spec).values()}
        altered=[]
        with connection.cursor() as cursor:
            if connection.vendor=='sqlite':
                cursor.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'kh_audit_%'")
                found=dict(cursor.fetchall());required=expected|{'kh_audit_no_update','kh_audit_no_delete','kh_audit_no_replace'}
                normalize=lambda s:re.sub(r'\s+',' ',s).strip(' ;').lower()
                for spec in plan:
                    for sql in statements(spec,plan,'sqlite'):
                        name=re.search(r'CREATE TRIGGER "([^"]+)"',sql)[1]
                        if name in found and normalize(found[name])!=normalize(sql):altered.append(name)
                for verb in ('update','delete'):
                    name='kh_audit_no_'+verb
                    sql=f"CREATE TRIGGER {name} BEFORE {verb.upper()} ON audit_log BEGIN SELECT RAISE(ABORT,'Journal audit en lecture seule'); END"
                    if name in found and normalize(found[name])!=normalize(sql):altered.append(name)
                replacement="CREATE TRIGGER kh_audit_no_replace BEFORE INSERT ON audit_log WHEN EXISTS (SELECT 1 FROM audit_log WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Journal audit en lecture seule'); END"
                if 'kh_audit_no_replace' in found and normalize(found['kh_audit_no_replace'])!=normalize(replacement):altered.append('kh_audit_no_replace')
            else:
                cursor.execute("SELECT t.tgname,t.tgenabled,p.prosrc,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid WHERE NOT t.tgisinternal AND t.tgname LIKE 'kh_audit_%%' AND n.nspname=current_schema()")
                found={r[0]:r[1:] for r in cursor.fetchall()};required=expected|{'kh_audit_immutable'}
                normalize=lambda s:re.sub(r'\s+',' ',s).strip(' ;').lower()
                for spec in plan:
                    sqls=statements(spec,plan,'postgresql')
                    for i in range(0,len(sqls),2):
                        name=re.search(r'CREATE FUNCTION "([^"]+)"',sqls[i])[1]
                        if name not in found:continue
                        enabled,body,definition=found[name]
                        expected_body=sqls[i].split('$audit$')[1]
                        # PostgreSQL ajoute le schéma aux noms ; le corps et le mode
                        # d'exécution sont vérifiés, ainsi que l'absence de filtre WHEN.
                        if enabled not in ('O','A') or normalize(body)!=normalize(expected_body) or ' WHEN ' in definition.upper():altered.append(name)
                if 'kh_audit_immutable' in found:
                    enabled,body,definition=found['kh_audit_immutable']
                    if enabled not in ('O','A') or normalize(body)!=normalize("BEGIN RAISE EXCEPTION 'Journal audit en lecture seule'; END;") or any(word not in definition.upper() for word in ('BEFORE','UPDATE','DELETE','TRUNCATE','FOR EACH STATEMENT')):altered.append('kh_audit_immutable')
        missing=sorted(required-set(found))
        return Response({'active':not missing and not altered,'tables':len(plan),'declencheurs':len(required),
            'absents':missing,'modifies':altered,'limite':'La protection bloque les modifications et suppressions courantes. Un administrateur disposant des droits sur la base ou le disque peut la retirer ; conserver des sauvegardes hors du serveur.'})
