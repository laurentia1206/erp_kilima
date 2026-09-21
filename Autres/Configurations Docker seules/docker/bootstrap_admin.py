"""Premier compte système d'une installation neuve. Aucun remplacement de compte."""
import getpass
import sys

sys.path.insert(0, "/app/backend")
from entrypoint import configure


def main():
    configure()
    import django
    django.setup()
    import bcrypt
    from django.core.validators import validate_email
    from django.db import transaction
    from core.admin_views import verrou_admin
    from core.models import Utilisateur, SuperAdministrateur

    if SuperAdministrateur.objects.exists():
        raise SystemExit("Un super administrateur existe déjà : utiliser son espace de gestion.")
    email = input("Adresse du premier administrateur système : ").strip().lower()
    validate_email(email)
    name = input("Nom affiché : ").strip()
    if not name or len(name) > 128:
        raise SystemExit("Nom requis, 128 caractères maximum.")
    password = getpass.getpass("Mot de passe (12 caractères minimum, 72 octets maximum) : ")
    if len(password) < 12 or len(password.encode()) > 72:
        raise SystemExit("Longueur du mot de passe incorrecte.")
    if password != getpass.getpass("Confirmer le mot de passe : "):
        raise SystemExit("Les mots de passe ne correspondent pas.")
    with transaction.atomic():
        verrou_admin()
        if SuperAdministrateur.objects.exists() or Utilisateur.objects.filter(email__iexact=email).exists():
            raise SystemExit("Compte ou administrateur existant : aucune modification effectuée.")
        user = Utilisateur.objects.create(email=email, nom=name,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())
        SuperAdministrateur.objects.create(utilisateur=user)
    print("Administrateur système créé, sans affectation aux sociétés ni droit métier.")


if __name__ == "__main__":
    main()
