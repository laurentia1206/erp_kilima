"""Espace global de gestion des habilitations, réservé aux super administrateurs."""
import hashlib
import json
import bcrypt
from django.db import transaction
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from rest_framework.response import Response
from rest_framework import serializers
from .viewsets import MetierModelViewSet
from .models import Utilisateur, Societe, Role, UtilisateurSociete, PermissionModule, SuperAdministrateur
from .serializers import UtilisateurSerializer
from .permissions import est_super_admin, MODULES, ACTIONS


def verrou_admin():
    # Ligne système stable : sérialise promotions/révocations concurrentes.
    Role.objects.select_for_update().get(code='ADMIN_SYS')


def configuration(user):
    rules={r.module:{key:getattr(r,key) for key in ACTIONS} for r in PermissionModule.objects.filter(utilisateur=user)}
    data={'super_administrateur':SuperAdministrateur.objects.filter(utilisateur=user).exists(), 'permissions':rules}
    data['revision']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return data


class RegleSerializer(serializers.Serializer):
    module=serializers.ChoiceField(choices=list(MODULES))
    consulter=serializers.BooleanField()
    creer=serializers.BooleanField()
    modifier=serializers.BooleanField()
    supprimer=serializers.BooleanField()
    executer=serializers.BooleanField()
    exporter=serializers.BooleanField()


class PermissionsSerializer(serializers.Serializer):
    revision=serializers.CharField(max_length=64)
    permissions=RegleSerializer(many=True)

    def validate_permissions(self,rules):
        if len({r['module'] for r in rules})!=len(rules): raise ValidationError('Module en double.')
        return rules


class StatutSerializer(serializers.Serializer):
    revision=serializers.CharField(max_length=64)
    super_administrateur=serializers.BooleanField()


class AdministrationSystemeViewSet(MetierModelViewSet):
    queryset=Utilisateur.objects.none()
    serializer_class=UtilisateurSerializer
    lookup_url_kwarg='utilisateur_id'

    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if not est_super_admin(request.user): raise PermissionDenied('Espace réservé au super administrateur du système.')

    def finalize_response(self,request,response,*args,**kwargs):
        response=super().finalize_response(request,response,*args,**kwargs)
        response['Cache-Control']='no-store'
        return response

    def list(self,request):
        supers=set(SuperAdministrateur.objects.values_list('utilisateur_id',flat=True))
        users=[]
        for u in Utilisateur.objects.order_by('nom','prenom'):
            users.append({'id':str(u.id),'nom':u.nom,'prenom':u.prenom,'email':u.email,'actif':u.actif,
                'super_administrateur':u.id in supers,'last_login':u.last_login,
                'affectations':[{'societe':a.societe.nom,'societe_id':str(a.societe_id),'role':a.role.code}
                    for a in UtilisateurSociete.objects.filter(utilisateur=u).select_related('societe','role')]})
        return Response({'utilisateurs':users,'roles':Role.objects.count(),
            'modules':MODULES,'actions':ACTIONS,
            'capacites':{'audit':['consulter','exporter'],'editions':['consulter','exporter']}})

    @action(detail=False,methods=['post'])
    def mot_de_passe(self,request):
        from .audit import security_event
        old=request.data.get('ancien','');new=request.data.get('nouveau','')
        if not isinstance(old,str) or not isinstance(new,str) or not 12<=len(new)<=128 or len(new.encode())>72:
            raise ValidationError('Choisissez un mot de passe de 12 caractères minimum (72 octets maximum).')
        with transaction.atomic():
            u=Utilisateur.objects.select_for_update().get(id=request.user.id)
            if not bcrypt.checkpw(old.encode()[:72],u.password_hash.encode()):
                security_event(request._request,'MOT_DE_PASSE_ECHEC',request.user,{'raison':'verification_refusee'})
                raise ValidationError('Mot de passe actuel incorrect.')
            if old==new: raise ValidationError('Choisissez un nouveau mot de passe différent.')
            u.password_hash=bcrypt.hashpw(new.encode(),bcrypt.gensalt()).decode();u.save(update_fields=['password_hash'])
            SuperAdministrateur.objects.filter(utilisateur=u).update(changer_mot_de_passe=False)
        security_event(request._request,'MOT_DE_PASSE_MODIFIE',request.user)
        from .auth import creer_token
        return Response({'ok':True,'access_token':creer_token(u.id,u.password_hash)})

    def retrieve(self,request,utilisateur_id):
        u=Utilisateur.objects.filter(id=utilisateur_id).first()
        if not u: raise NotFound('Utilisateur introuvable.')
        return Response({'id':str(u.id),'nom':u.nom,'email':u.email,**configuration(u)})

    def partial_update(self,request,utilisateur_id):
        serializer=PermissionsSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            verrou_admin()
            if not est_super_admin(request.user): raise PermissionDenied()
            u=Utilisateur.objects.select_for_update().filter(id=utilisateur_id).first()
            if not u: raise NotFound('Utilisateur introuvable.')
            if configuration(u)['revision']!=serializer.validated_data['revision']:
                raise ValidationError('Les droits ont changé. Rechargez la fiche avant de les modifier.')
            if SuperAdministrateur.objects.filter(utilisateur=u).exists():
                raise ValidationError('Le super administrateur gère uniquement les utilisateurs. Ses droits métier sont bloqués tant que ce statut est actif.')
            rules=serializer.validated_data['permissions']
            PermissionModule.objects.filter(utilisateur=u).exclude(module__in=[r['module'] for r in rules]).delete()
            for rule in rules:
                values={k:rule[k] for k in ACTIONS}
                if all(values.values()): PermissionModule.objects.filter(utilisateur=u,module=rule['module']).delete()
                else: PermissionModule.objects.update_or_create(utilisateur=u,module=rule['module'],defaults=values)
        return Response(configuration(u))

    @action(detail=True,methods=['post'])
    def statut(self,request,utilisateur_id):
        serializer=StatutSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        grant=serializer.validated_data['super_administrateur']
        with transaction.atomic():
            verrou_admin()
            if not est_super_admin(request.user): raise PermissionDenied()
            u=Utilisateur.objects.select_for_update().filter(id=utilisateur_id).first()
            if not u: raise NotFound('Utilisateur introuvable.')
            if configuration(u)['revision']!=serializer.validated_data['revision']: raise ValidationError('Les droits ont changé. Rechargez la fiche.')
            if not u.actif: raise ValidationError('Activez le compte avant de modifier ce statut.')
            if not grant and u.id==request.user.id: raise ValidationError('Vous ne pouvez pas retirer votre propre statut. Un autre super administrateur doit intervenir.')
            if grant: SuperAdministrateur.objects.get_or_create(utilisateur=u)
            else:
                if not SuperAdministrateur.objects.filter(utilisateur__actif=True).exclude(utilisateur=u).exists():
                    raise ValidationError('Conservez au moins un super administrateur actif.')
                SuperAdministrateur.objects.filter(utilisateur=u).delete()
        return Response(configuration(u))
