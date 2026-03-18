import django.db.models.deletion
from django.db import migrations, models


def backfill_default_tenant(apps, schema_editor):
    Tenant = apps.get_model('myApp', 'Tenant')
    Course = apps.get_model('myApp', 'Course')
    CourseResource = apps.get_model('myApp', 'CourseResource')
    Module = apps.get_model('myApp', 'Module')
    Lesson = apps.get_model('myApp', 'Lesson')
    LessonQuiz = apps.get_model('myApp', 'LessonQuiz')
    LessonQuizQuestion = apps.get_model('myApp', 'LessonQuizQuestion')
    LessonQuizAttempt = apps.get_model('myApp', 'LessonQuizAttempt')
    UserProgress = apps.get_model('myApp', 'UserProgress')
    CourseEnrollment = apps.get_model('myApp', 'CourseEnrollment')
    FavoriteCourse = apps.get_model('myApp', 'FavoriteCourse')
    Exam = apps.get_model('myApp', 'Exam')
    ExamQuestion = apps.get_model('myApp', 'ExamQuestion')
    ExamAttempt = apps.get_model('myApp', 'ExamAttempt')
    Certification = apps.get_model('myApp', 'Certification')
    Cohort = apps.get_model('myApp', 'Cohort')
    Bundle = apps.get_model('myApp', 'Bundle')
    BundlePurchase = apps.get_model('myApp', 'BundlePurchase')
    CourseAccess = apps.get_model('myApp', 'CourseAccess')
    CohortMember = apps.get_model('myApp', 'CohortMember')
    LearningPath = apps.get_model('myApp', 'LearningPath')
    LearningPathCourse = apps.get_model('myApp', 'LearningPathCourse')
    TenantConfig = apps.get_model('myApp', 'TenantConfig')

    default_tenant, _ = Tenant.objects.get_or_create(
        slug='default',
        defaults={
            'name': 'Default Tenant',
            'primary_color': '#3B82F6',
            'is_active': True,
        }
    )
    TenantConfig.objects.get_or_create(tenant=default_tenant)

    # Root entities
    Course.objects.filter(tenant__isnull=True).update(tenant=default_tenant)
    Bundle.objects.filter(tenant__isnull=True).update(tenant=default_tenant)
    Cohort.objects.filter(tenant__isnull=True).update(tenant=default_tenant)
    LearningPath.objects.filter(tenant__isnull=True).update(tenant=default_tenant)

    # Course lineage
    for obj in Module.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in Lesson.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in CourseResource.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])

    # Lesson quiz lineage
    for obj in LessonQuiz.objects.filter(tenant__isnull=True).select_related('lesson').iterator():
        obj.tenant_id = obj.lesson.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in LessonQuizQuestion.objects.filter(tenant__isnull=True).select_related('quiz').iterator():
        obj.tenant_id = obj.quiz.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in LessonQuizAttempt.objects.filter(tenant__isnull=True).select_related('quiz').iterator():
        obj.tenant_id = obj.quiz.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])

    # Exam lineage
    for obj in Exam.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in ExamQuestion.objects.filter(tenant__isnull=True).select_related('exam').iterator():
        obj.tenant_id = obj.exam.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in ExamAttempt.objects.filter(tenant__isnull=True).select_related('exam').iterator():
        obj.tenant_id = obj.exam.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])

    # Course-related user records
    for obj in UserProgress.objects.filter(tenant__isnull=True).select_related('lesson').iterator():
        obj.tenant_id = obj.lesson.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in CourseEnrollment.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in FavoriteCourse.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in Certification.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in CourseAccess.objects.filter(tenant__isnull=True).select_related('course').iterator():
        obj.tenant_id = obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])

    # Bundle/cohort/learning path related records
    for obj in BundlePurchase.objects.filter(tenant__isnull=True).select_related('bundle').iterator():
        obj.tenant_id = obj.bundle.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in CohortMember.objects.filter(tenant__isnull=True).select_related('cohort').iterator():
        obj.tenant_id = obj.cohort.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])
    for obj in LearningPathCourse.objects.filter(tenant__isnull=True).select_related('learning_path', 'course').iterator():
        obj.tenant_id = obj.learning_path.tenant_id or obj.course.tenant_id or default_tenant.id
        obj.save(update_fields=['tenant'])


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0017_courseresource'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tenant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(unique=True)),
                ('custom_domain', models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ('logo', models.ImageField(blank=True, null=True, upload_to='tenant_logos/')),
                ('primary_color', models.CharField(default='#3B82F6', max_length=7)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='TenantConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chatbot_webhook', models.URLField(blank=True)),
                ('vimeo_team_id', models.CharField(blank=True, max_length=255)),
                ('accredible_issuer_id', models.CharField(blank=True, max_length=255)),
                ('features', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='config', to='myApp.tenant')),
            ],
            options={
                'verbose_name': 'Tenant Config',
                'verbose_name_plural': 'Tenant Configs',
            },
        ),
        migrations.AlterField(
            model_name='bundle',
            name='name',
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name='bundle',
            name='slug',
            field=models.SlugField(max_length=200),
        ),
        migrations.AlterField(
            model_name='cohort',
            name='name',
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name='course',
            name='slug',
            field=models.SlugField(max_length=200),
        ),
        migrations.AddField(
            model_name='bundle',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='bundles', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='bundlepurchase',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='bundle_purchases', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='certification',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='certifications', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='cohort',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='cohorts', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='cohortmember',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='cohort_memberships', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='course',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='courses', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='courseaccess',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='course_accesses', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='courseenrollment',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='course_enrollments', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='courseresource',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='course_resources', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='exam',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='exams', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='examattempt',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='exam_attempts', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='examquestion',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='exam_questions', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='favoritecourse',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='favorite_courses', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='learningpath',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='learning_paths', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='learningpathcourse',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='learning_path_courses', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='lesson',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lessons', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='lessonquiz',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lesson_quizzes', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='lessonquizattempt',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lesson_quiz_attempts', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='lessonquizquestion',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lesson_quiz_questions', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='module',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='modules', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='userprogress',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='user_progress_records', to='myApp.tenant'),
        ),
        migrations.RunPython(backfill_default_tenant, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='cohort',
            constraint=models.UniqueConstraint(fields=('tenant', 'name'), name='uniq_cohort_tenant_name'),
        ),
        migrations.AddConstraint(
            model_name='course',
            constraint=models.UniqueConstraint(fields=('tenant', 'slug'), name='uniq_course_tenant_slug'),
        ),
        migrations.AddConstraint(
            model_name='bundle',
            constraint=models.UniqueConstraint(fields=('tenant', 'slug'), name='uniq_bundle_tenant_slug'),
        ),
        migrations.AddConstraint(
            model_name='bundle',
            constraint=models.UniqueConstraint(fields=('tenant', 'name'), name='uniq_bundle_tenant_name'),
        ),
    ]

