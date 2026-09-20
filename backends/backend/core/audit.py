"""Événements métier et sécurité, et masquage des informations confidentielles."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import uuid

from django.apps import apps
from django.conf import settings
from django.db import connection
from .audit_context import context, current
from .audit_schema import HR_PUBLIC, SENSITIVE, PARENTS


def clean(value, table='', key=''):
    private=any(s in key.lower() for s in SENSITIVE) or (table.startswith('core_rh') and key and key not in HR_PUBLIC and key!='champs_modifies') or (table=='parametre' and key=='valeur')
    if private:return '[masqué]' if value is not None else None
    if isinstance(value,dict):return {str(k):clean(v,table,str(k)) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v,table) for v in value[:100]]
    if isinstance(value,(datetime,uuid.UUID,Decimal)):return str(value)
    if isinstance(value,bytes):return '[masqué]'
    if isinstance(value,str):return value[:2000]
    return value


def target_scope(table, ident, visited=()):
    if not ident or table in visited:return None
    model=next((m for m in apps.get_models() if m._meta.db_table==table or m._meta.model_name==table),None)
    if not model:return None
    try:
        obj=model.objects.filter(pk=ident).first()
    except (ValueError,TypeError):return None
    if obj is None:return None
    if table=='societe':return obj.pk
    if hasattr(obj,'societe_id'):return obj.societe_id
    if table in PARENTS:
        field,parent=PARENTS[table]
        return target_scope(parent,getattr(obj,field,None),(*visited,table))
    return None


def append_event(user_id, action, table, ident=None, old=None, new=None, *, societe_id=None, categorie='metier', module=None):
    from .models import AuditLog
    c=context()
    model=next((m for m in apps.get_models() if m._meta.db_table==table or m._meta.model_name==table),None)
    if model:table=model._meta.db_table
    sid=societe_id if societe_id is not None else target_scope(table,ident)
    return AuditLog.objects.create(utilisateur_id=user_id or c.get('utilisateur_id'),action=action,table_cible=table,
        enregistrement_id=str(ident)[:64] if ident else None,ancienne_valeur=clean(old,table),nouvelle_valeur=clean(new,table),
        horodatage=datetime.now(timezone.utc).replace(tzinfo=None),societe_id=sid,
        module=module or (model._meta.app_label if model else 'core'),categorie=categorie,
        adresse_ip=c.get('adresse_ip'),requete_id=c.get('requete_id'),methode=c.get('methode',''),
        chemin=c.get('chemin',''),origine=c.get('origine','systeme'))


def security_event(request, action, user=None, details=None):
    if current.get() is None:return  # Appels directs de services hors HTTP : pas de contexte inventé.
    if getattr(request,'audit_defer_security',False):
        if not hasattr(request,'audit_security_queue'):request.audit_security_queue=[]
        request.audit_security_queue.append((action,user,details))
        return
    request.audit_security_recorded=True
    from .models import UtilisateurSociete
    user=user or getattr(request,'user',None)
    user_id=getattr(user,'id',None)
    if user_id:request.audit_actor=user_id
    scopes=list(UtilisateurSociete.objects.filter(utilisateur_id=user_id).values_list('societe_id',flat=True).distinct()) if user_id else []
    # Une tentative sans compte connu reste globale, réservée à ADMIN_SYS.
    for sid in scopes or [None]:
        append_event(user_id,action,'authentification',None,new=details or {},societe_id=sid,categorie='securite',module='securite')


def identity_fingerprint(value):
    return hmac.new(settings.SECRET_KEY.encode(),str(value).strip().casefold()[:254].encode(),hashlib.sha256).hexdigest()
