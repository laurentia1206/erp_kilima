"""La table à clé composite n'est pas créée par les modèles unmanaged.

Création uniquement si absente (installation vierge) ; une base existante
conserve sa table et toutes ses affectations. Retour arrière non destructif.
"""
from django.db import migrations, models


def creer_affectations(apps, schema_editor):
    if "utilisateur_societe" in schema_editor.connection.introspection.table_names():
        return
    uuid_type = models.UUIDField().db_type(schema_editor.connection)
    schema_editor.execute(f"""
        CREATE TABLE utilisateur_societe (
            utilisateur_id {uuid_type} NOT NULL REFERENCES utilisateur(id),
            societe_id {uuid_type} NOT NULL REFERENCES societe(id),
            role_id {uuid_type} NOT NULL REFERENCES role(id),
            site_id {uuid_type} NULL,
            PRIMARY KEY (utilisateur_id, societe_id, role_id)
        )
    """)


class Migration(migrations.Migration):
    dependencies = [("core", "0012_article_nature")]
    operations = [migrations.RunPython(creer_affectations, migrations.RunPython.noop)]
