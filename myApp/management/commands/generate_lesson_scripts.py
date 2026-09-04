"""
Backfill ~5-minute video scripts for lessons.

Runs synchronously, one lesson at a time. Use this to regenerate or to
fill scripts for courses created before the feature existed.

Usage:
    python manage.py generate_lesson_scripts
    python manage.py generate_lesson_scripts --course my-course-slug
    python manage.py generate_lesson_scripts --lesson-id 42
    python manage.py generate_lesson_scripts --force
    python manage.py generate_lesson_scripts --limit 10
"""
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Q

from myApp.dashboard_views import _course_scripts_folder_id, _run_generate_and_upload_script
from myApp.models import Lesson


class Command(BaseCommand):
    help = 'Generate AI video scripts (and optional Google Docs) for lessons missing them.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit to a single tenant by slug')
        parser.add_argument('--course', help='Limit to a single course by slug')
        parser.add_argument('--lesson-id', type=int, help='Generate for one lesson only')
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate even when video_script already exists',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Stop after N lessons (0 = no limit)',
        )

    def handle(self, *args, **options):
        lessons = Lesson.objects.select_related('course').order_by('course_id', 'order', 'id')

        if options['lesson_id']:
            lessons = lessons.filter(id=options['lesson_id'])
        if options['tenant']:
            lessons = lessons.filter(tenant__slug=options['tenant'])
        if options['course']:
            lessons = lessons.filter(course__slug=options['course'])
        if not options['force']:
            lessons = lessons.filter(Q(video_script={}) | Q(video_script__isnull=True))

        if options['limit']:
            lessons = lessons[:options['limit']]

        lesson_ids = list(lessons.values_list('id', flat=True))
        total = len(lesson_ids)
        if not total:
            self.stdout.write(self.style.WARNING('No lessons need a video script. Use --force to regenerate.'))
            return

        self.stdout.write(f'Generating video scripts for {total} lesson(s)...')
        folder_cache = {}
        done = failed = 0
        for idx, lesson_id in enumerate(lesson_ids, start=1):
            try:
                close_old_connections()
                lesson = Lesson.objects.select_related('course').get(id=lesson_id)
                course_name = lesson.course.name if lesson.course_id else 'Untitled Course'
                if course_name not in folder_cache:
                    folder_cache[course_name] = _course_scripts_folder_id(course_name)
                label = f'[{idx}/{total}] lesson {lesson.id}: {lesson.title[:60]}'
                self.stdout.write(f'{label} ...', ending=' ')
                self.stdout.flush()
                _run_generate_and_upload_script(lesson.id, course_name, folder_cache[course_name])
                close_old_connections()
                lesson.refresh_from_db(fields=['video_script', 'script_doc_url'])
                if lesson.video_script:
                    done += 1
                    doc_note = ' + Doc' if lesson.script_doc_url else ''
                    self.stdout.write(self.style.SUCCESS(f'OK{doc_note}'))
                else:
                    failed += 1
                    self.stdout.write(self.style.ERROR('skipped or failed (no JSON saved)'))
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f'lesson {lesson_id} crashed: {str(exc)[:200]}'))

        self.stdout.write(self.style.SUCCESS(f'Done. {done} generated, {failed} failed/skipped.'))
