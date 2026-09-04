from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0068_lesson_video_script_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='what_youll_learn_heading',
            field=models.CharField(
                blank=True,
                default="What You'll Learn Today",
                help_text="Heading shown above the What you'll learn body on the student lesson page",
                max_length=200,
            ),
        ),
    ]
