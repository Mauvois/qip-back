from django.db import migrations


def create_statuses(apps, schema_editor):
    status = apps.get_model('qipu_api', 'EpistemicStatus')
    status.objects.using(schema_editor.connection.alias).bulk_create([
        status(code='factoid', label='Factoïde', definition='Énoncé rapporté sans adoption critique implicite.'),
        status(code='qualified', label='Information qualifiée', definition='Énoncé formulé et qualifié par un utilisateur.'),
    ])


def remove_statuses(apps, schema_editor):
    apps.get_model('qipu_api', 'EpistemicStatus').objects.using(schema_editor.connection.alias).filter(
        code__in=['factoid', 'qualified']).delete()


class Migration(migrations.Migration):
    dependencies = [('qipu_api', '0004_epistemicstatus_historicalentity_researchproject_and_more')]
    operations = [migrations.RunPython(create_statuses, remove_statuses)]
