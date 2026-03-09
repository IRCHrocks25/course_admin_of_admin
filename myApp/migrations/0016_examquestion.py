# Generated for exam questions (AI-generated final exam)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0015_increase_short_description_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExamQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('option_a', models.CharField(max_length=300)),
                ('option_b', models.CharField(max_length=300)),
                ('option_c', models.CharField(blank=True, max_length=300)),
                ('option_d', models.CharField(blank=True, max_length=300)),
                ('correct_option', models.CharField(choices=[('A', 'Option A'), ('B', 'Option B'), ('C', 'Option C'), ('D', 'Option D')], max_length=1)),
                ('order', models.IntegerField(default=0)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='myApp.exam')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
    ]
