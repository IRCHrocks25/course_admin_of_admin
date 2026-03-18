from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0018_multitenant_phase1'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='userprogress',
            unique_together={('tenant', 'user', 'lesson')},
        ),
        migrations.AlterUniqueTogether(
            name='courseenrollment',
            unique_together={('tenant', 'user', 'course')},
        ),
        migrations.AlterUniqueTogether(
            name='favoritecourse',
            unique_together={('tenant', 'user', 'course')},
        ),
        migrations.AlterUniqueTogether(
            name='certification',
            unique_together={('tenant', 'user', 'course')},
        ),
        migrations.AlterUniqueTogether(
            name='lesson',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='lesson',
            constraint=models.UniqueConstraint(
                fields=('tenant', 'course', 'slug'),
                name='uniq_lesson_tenant_course_slug',
            ),
        ),
    ]

