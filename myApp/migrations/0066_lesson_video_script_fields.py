# Generated manually for Lesson video-script fields + AIUsageLog feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0065_lesson_ai_generation_status_partial'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='video_script',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Structured ~5-minute video script JSON (hook, sections, close, shot_list)',
            ),
        ),
        migrations.AddField(
            model_name='lesson',
            name='script_doc_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Google Doc file ID for the uploaded video script',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='lesson',
            name='script_doc_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Google Doc URL for the uploaded video script',
            ),
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
                    ('lesson_audio', 'Lesson Audio'),
                    ('lesson_quiz', 'Lesson Quiz'),
                    ('course_exam', 'Course Exam'),
                    ('lesson_video_script', 'Lesson Video Script'),
                ],
                max_length=40,
            ),
        ),
    ]
