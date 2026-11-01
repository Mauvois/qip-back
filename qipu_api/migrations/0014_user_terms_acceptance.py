from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('qipu_api', '0013_backfill_bibliographic_publication_dates')]

    operations = [
        migrations.AddField(
            model_name='user', name='terms_accepted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user', name='terms_version',
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
