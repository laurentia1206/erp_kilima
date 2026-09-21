"""Contexte de traçabilité isolé par requête, jamais repris depuis un en-tête client."""
from contextvars import ContextVar
from datetime import datetime, timezone
import ipaddress
import json
import re
import uuid

from django.db import connections, transaction

current = ContextVar('kilima_audit_request', default=None)


def context():
    request=current.get()
    if request is None:
        return {'origine':'systeme', 'methode':'', 'chemin':''}
    actor=getattr(request,'audit_actor',None) or getattr(getattr(request,'user',None),'id',None)
    try: actor=uuid.UUID(str(actor)).hex if actor else None
    except (ValueError,TypeError): actor=None
    try: address=str(ipaddress.ip_address(request.META.get('REMOTE_ADDR','')))
    except ValueError: address=None
    route=getattr(getattr(request,'resolver_match',None),'route',None) or request.path
    return {'utilisateur_id':actor, 'adresse_ip':address,
            'requete_id':request.audit_request_id.hex, 'methode':request.method[:12],
            'chemin':route[:255], 'origine':'application'}


def value(key):
    if key=='horodatage':return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(' ')
    return context().get(key)


def postgres_context(execute, sql, params, many, execution_context):
    # Un contexte explicite pour chaque écriture évite les fuites lors de la
    # réutilisation des connexions, y compris hors requête HTTP.
    if re.match(r'^\s*(INSERT|UPDATE|DELETE|WITH)\b',str(sql),re.I):
        raw=execution_context['connection'].connection
        with raw.cursor() as cursor:
            cursor.execute("SELECT set_config('kilima.audit_context', %s, false)", [json.dumps(context())])
    return execute(sql,params,many,execution_context)


def register_connection(sender=None, connection=None, **kwargs):
    if connection.vendor=='sqlite':
        connection.connection.create_function('kilima_audit',1,value)
    elif connection.vendor=='postgresql' and postgres_context not in connection.execute_wrappers:
        connection.execute_wrappers.append(postgres_context)


def install():
    from django.db.backends.signals import connection_created
    connection_created.connect(register_connection,dispatch_uid='kilima-audit-context')
    for connection in connections.all():
        if connection.connection is not None:register_connection(connection=connection)


class AuditContextMiddleware:
    def __init__(self,get_response):self.get_response=get_response

    def __call__(self,request):
        request.audit_request_id=uuid.uuid4()
        marker=current.set(request)
        try:
            request.audit_defer_security=True
            if request.path.startswith('/api/') and request.method in ('POST','PUT','PATCH','DELETE'):
                with transaction.atomic():
                    response=self.get_response(request)
                    if response.status_code>=400:transaction.set_rollback(True)
            else:response=self.get_response(request)
            request.audit_defer_security=False
            from .audit import security_event
            for action,user,details in getattr(request,'audit_security_queue',[]):
                if action=='CONNEXION_REUSSIE' and response.status_code>=400:continue
                security_event(request,action,user,details)
            if request.path.startswith('/api/') and response.status_code in (401,403) and not getattr(request,'audit_security_recorded',False):
                security_event(request,'ACCES_REFUSE',None,{'statut':response.status_code})
            if request.path.startswith('/api/') and response.status_code>=500:
                # Ni contenu métier, ni exception/trace Python, ni paramètres URL.
                security_event(request,'ERREUR_SERVEUR',None,{'statut':response.status_code})
            response['X-Request-ID']=str(request.audit_request_id)
            return response
        finally:current.reset(marker)
