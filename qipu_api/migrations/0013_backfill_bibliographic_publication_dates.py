from django.db import migrations


def backfill(apps, schema_editor):
    from qipu_api.zotero_formats import date_text, publication_bounds

    BibliographicRecord = apps.get_model('qipu_api', 'BibliographicRecord')
    SourceDating = apps.get_model('qipu_api', 'SourceDating')
    for record in BibliographicRecord.objects.using(schema_editor.connection.alias).iterator():
        issued = record.csl.get('issued')
        bounds = publication_bounds(issued)
        if not bounds:
            continue
        datings = SourceDating.objects.using(schema_editor.connection.alias).filter(
            source_id=record.source_id, date_kind='publication', date_text=date_text(issued))
        for dating in datings:
            if not any((dating.begin_of_begin, dating.end_of_begin, dating.begin_of_end, dating.end_of_end,
                        dating.begin_of_begin_time, dating.end_of_begin_time, dating.begin_of_end_time,
                        dating.end_of_end_time)):
                dating.begin_of_begin = bounds['begin_of_begin']
                dating.end_of_end = bounds['end_of_end']
                dating.save(update_fields=['begin_of_begin', 'end_of_end'])


class Migration(migrations.Migration):
    dependencies = [('qipu_api', '0012_alter_qipsource_title')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
