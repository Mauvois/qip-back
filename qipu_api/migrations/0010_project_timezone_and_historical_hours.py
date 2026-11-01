from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('qipu_api', '0009_geographicalplace_valid_geographical_coordinates')]

    operations = [
        migrations.AddField(model_name='researchproject', name='timezone',
                            field=models.CharField(default='UTC', max_length=64)),
        *[
            migrations.AddField(model_name=model, name=f'{bound}_time',
                                field=models.TimeField(blank=True, null=True))
            for model in ('sourcedating', 'qipinformation')
            for bound in ('begin_of_begin', 'end_of_begin', 'begin_of_end', 'end_of_end')
        ],
    ]
