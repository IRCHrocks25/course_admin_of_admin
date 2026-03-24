from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0021_tenantdomain"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIUsageLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("openai", "OpenAI")], default="openai", max_length=20)),
                (
                    "feature",
                    models.CharField(
                        choices=[
                            ("course_structure", "Course Structure"),
                            ("lesson_metadata", "Lesson Metadata"),
                            ("lesson_content", "Lesson Content"),
                            ("lesson_quiz", "Lesson Quiz"),
                            ("course_exam", "Course Exam"),
                        ],
                        max_length=40,
                    ),
                ),
                ("model_name", models.CharField(blank=True, max_length=80)),
                ("request_id", models.CharField(blank=True, max_length=120)),
                ("prompt_tokens", models.IntegerField(default=0)),
                ("completion_tokens", models.IntegerField(default=0)),
                ("total_tokens", models.IntegerField(default=0)),
                ("input_rate_per_million", models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ("output_rate_per_million", models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ("cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "course",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_usage_logs",
                        to="myApp.course",
                    ),
                ),
                (
                    "lesson",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_usage_logs",
                        to="myApp.lesson",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_usage_logs",
                        to="myApp.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="aiusagelog",
            index=models.Index(fields=["tenant", "created_at"], name="myApp_aiusa_tenant__8ff736_idx"),
        ),
        migrations.AddIndex(
            model_name="aiusagelog",
            index=models.Index(fields=["course", "created_at"], name="myApp_aiusa_course__ef1057_idx"),
        ),
        migrations.AddIndex(
            model_name="aiusagelog",
            index=models.Index(fields=["feature", "created_at"], name="myApp_aiusa_feature_3f79a1_idx"),
        ),
    ]
