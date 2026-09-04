# Allow empty script fields on INSERT. Django does not keep a Postgres
# server default after AddField, so an omitted column was stored as NULL
# and failed the NOT NULL constraint during course generation.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0067_platformconfig'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lesson',
            name='video_script',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Structured ~5-minute video script JSON (hook, sections, close, shot_list)',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='lesson',
            name='script_doc_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Google Doc file ID for the uploaded video script',
                max_length=200,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='lesson',
            name='script_doc_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Google Doc URL for the uploaded video script',
                null=True,
            ),
        ),
    ]
