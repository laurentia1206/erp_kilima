"""Activation nominative du premier administrateur, sans mot de passe ajouté."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Utilisateur, SuperAdministrateur
from core.admin_views import verrou_admin


class Command(BaseCommand):
    help='Activer le premier super administrateur sur un compte existant et actif.'

    def add_arguments(self,parser): parser.add_argument('email')

    def handle(self,*args,**options):
        with transaction.atomic():
            verrou_admin()
            if SuperAdministrateur.objects.exists(): raise CommandError('Un super administrateur existe déjà. Utilisez son espace de gestion.')
            users=Utilisateur.objects.filter(email__iexact=options['email'].strip(),actif=True)
            if users.count()!=1: raise CommandError('Il faut un compte existant, actif et identifié sans ambiguïté.')
            SuperAdministrateur.objects.create(utilisateur=users.get())
        self.stdout.write(self.style.SUCCESS('Premier super administrateur activé. Reconnectez ce compte.'))
