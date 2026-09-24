"""Installation Docker neuve : premier compte système, sans remplacement."""
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

    # Identifiants prédéfinis
    email = "admin@kilimaholdings.com".strip().lower()
    validate_email(email)

    name = "Admin KilimaHoldings"

    password = "fV4MtM7@8wAQFi7"
    if len(password) < 12 or len(password.encode()) > 72:
        raise SystemExit("Longueur du mot de passe incorrecte.")

    with transaction.atomic():
        verrou_admin()
        if SuperAdministrateur.objects.exists() or Utilisateur.objects.filter(email__iexact=email).exists():
            raise SystemExit("Compte ou administrateur existant : aucune modification effectuée.")

        user = Utilisateur.objects.create(
            email=email,
            nom=name,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        )
        SuperAdministrateur.objects.create(utilisateur=user)

    print(f"Administrateur système ({email}) créé avec succès, sans affectation aux sociétés ni droit métier.")


if __name__ == "__main__":
    main()