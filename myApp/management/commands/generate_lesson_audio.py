"""
Backfill AI audio narration for lessons.

By default processes every lesson that has no audio yet (audio_url empty and
not currently processing). Runs synchronously, one lesson at a time, so it is
safe to run on a dyno/laptop without spawning a thread per lesson.

Usage:
    python manage.py generate_lesson_audio                 # all lessons missing audio
    python manage.py generate_lesson_audio --course my-course-slug
    python manage.py generate_lesson_audio --lesson-id 42
    python manage.py generate_lesson_audio --force         # also regenerate existing/failed
    python manage.py generate_lesson_audio --limit 10
"""
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Q

from myApp.models import Lesson
from myApp.utils.lesson_audio import generate_lesson_audio


class Command(BaseCommand):
    help = 'Generate AI audio narration (OpenAI TTS) for lessons that are missing it.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit to a single tenant by slug')
        parser.add_argument('--course', help='Limit to a single course by slug')
        parser.add_argument('--lesson-id', type=int, help='Generate for one lesson only')
        parser.add_argument('--force', action='store_true',
                            help='Regenerate even when audio already exists or previously failed/skipped')
        parser.add_argument('--limit', type=int, default=0,
                            help='Stop after N lessons (0 = no limit)')

    def handle(self, *args, **options):
        lessons = Lesson.objects.all().order_by('course_id', 'order', 'id')

        if options['lesson_id']:
            lessons = lessons.filter(id=options['lesson_id'])
        if options['tenant']:
            lessons = lessons.filter(tenant__slug=options['tenant'])
        if options['course']:
            lessons = lessons.filter(course__slug=options['course'])
        if not options['force']:
            # Stale 'processing' rows (from a crashed prior run) are retried too;
            # don't run two backfills concurrently.
            lessons = lessons.filter(Q(audio_url='') | Q(audio_url__isnull=True))

        if options['limit']:
            lessons = lessons[:options['limit']]

        # Materialize IDs up front so no queryset cursor is held open across
        # an hours-long run, then re-fetch each lesson on a fresh connection.
        lesson_ids = list(lessons.values_list('id', flat=True))
        total = len(lesson_ids)
        if not total:
            self.stdout.write(self.style.WARNING('No lessons need audio. Use --force to regenerate.'))
            return

        self.stdout.write(f'Generating audio for {total} lesson(s)...')
        done = failed = 0
        for idx, lesson_id in enumerate(lesson_ids, start=1):
            try:
                close_old_connections()
                lesson = Lesson.objects.get(id=lesson_id)
                label = f'[{idx}/{total}] lesson {lesson.id}: {lesson.title[:60]}'
                self.stdout.write(f'{label} ...', ending=' ')
                self.stdout.flush()
                url = generate_lesson_audio(lesson)
                if url:
                    done += 1
                    self.stdout.write(self.style.SUCCESS(f'OK ({lesson.get_audio_duration_display() or "?"})'))
                else:
                    failed += 1
                    close_old_connections()
                    lesson.refresh_from_db(fields=['audio_status', 'audio_error'])
                    self.stdout.write(self.style.ERROR(
                        f'{lesson.audio_status}: {(lesson.audio_error or "no detail")[:200]}'
                    ))
            except Exception as e:
                # One poisoned lesson must not abort the rest of the queue.
                failed += 1
                self.stdout.write(self.style.ERROR(f'lesson {lesson_id} crashed: {str(e)[:200]}'))

        self.stdout.write(self.style.SUCCESS(f'Done. {done} generated, {failed} failed/skipped.'))
