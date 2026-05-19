from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0034_course_category_and_display_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='ai_hero_image_url',
            field=models.URLField(blank=True, default='', help_text='Cloudinary URL of the AI-generated hero image for this lesson'),
        ),
        migrations.AddField(
            model_name='lesson',
            name='ai_hero_image_prompt',
            field=models.TextField(blank=True, default='', help_text='The DALL-E prompt used to generate the hero image'),
        ),
        migrations.AlterField(
            model_name='aiusagelog',
            name='feature',
            field=models.CharField(
                choices=[
                    ('course_structure', 'Course Structure'),
                    ('lesson_metadata', 'Lesson Metadata'),
                    ('lesson_content', 'Lesson Content'),
                    ('lesson_image', 'Lesson Image'),
                    ('lesson_quiz', 'Lesson Quiz'),
                    ('course_exam', 'Course Exam'),
                ],
                max_length=40,
            ),
        ),
    ]
