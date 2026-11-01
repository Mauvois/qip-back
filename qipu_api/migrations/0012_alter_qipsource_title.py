from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('qipu_api', '0011_zoterocollection_zoteropreview_zoterooauthattempt_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='qipsource',
            name='title',
            field=models.CharField(max_length=2000),
        ),
    ]
