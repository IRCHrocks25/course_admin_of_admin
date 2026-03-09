# Generated for course resources (SOP templates, checklists, downloads)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0016_examquestion'),
    ]

    operations = [
        migrations.CreateModel(
            name='CourseResource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('resource_type', models.CharField(choices=[('template', 'Template'), ('checklist', 'Checklist'), ('pdf', 'PDF Document'), ('workbook', 'Workbook'), ('other', 'Other')], default='other', max_length=20)),
                ('file', models.FileField(blank=True, null=True, upload_to='course_resources/')),
                ('file_url', models.URLField(blank=True, help_text='External link if file is hosted elsewhere (Google Drive, etc.)')),
                ('order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='resources', to='myApp.course')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
    ]
