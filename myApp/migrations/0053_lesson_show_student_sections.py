from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0052_courseresource_iceberg_url_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='show_what_youll_learn',
            field=models.BooleanField(
                default=True,
                help_text='Show the "What You\'ll Learn Today" section on the student lesson page',
            ),
        ),
        migrations.AddField(
            model_name='lesson',
            name='show_lesson_notes',
            field=models.BooleanField(
                default=True,
                help_text='Show the "Lesson Notes" section on the student lesson page',
            ),
        ),
    ]
