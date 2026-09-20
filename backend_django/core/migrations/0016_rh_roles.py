from django.db import migrations


def roles(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    for code, libelle in [('RH', 'Ressources humaines'), ('DRH', 'Direction des ressources humaines'), ('RESP_EQUIPE', 'Responsable d’équipe — pointage')]:
        Role.objects.get_or_create(code=code, defaults={'libelle': libelle, 'niveau': 0})


class Migration(migrations.Migration):
    dependencies = [('core', '0015_rh_dossiers_pointages')]
    operations = [migrations.RunPython(roles, migrations.RunPython.noop)]
