from django.core.management.base import BaseCommand, CommandError

from myApp.models import Tenant, Course
from myApp.utils.localization import get_translation_languages_for_tenant, normalize_language_code
from myApp.utils.translation import (
    generate_course_translation,
    generate_module_translations_for_course,
    generate_lesson_translation,
    generate_quiz_question_translations,
    publish_course_translations_for_language,
)


class Command(BaseCommand):
    help = 'Generate and publish tenant course translations from the CLI.'

    def add_arguments(self, parser):
        parser.add_argument('tenant_slug')
        parser.add_argument('--languages', nargs='*', default=None)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=options['tenant_slug']).first()
        if tenant is None:
            raise CommandError('Tenant not found.')

        languages = options['languages'] or get_translation_languages_for_tenant(tenant)
        languages = [normalize_language_code(code) for code in languages if normalize_language_code(code) != 'en']
        if not languages:
            raise CommandError('No non-English languages configured.')

        courses = Course.objects.filter(tenant=tenant)
        for course in courses:
            for lang in languages:
                if not options['force']:
                    published = course.lessons.filter(
                        translations__language_code=lang,
                        translations__status='published',
                    ).distinct().count()
                    if published == course.lessons.count() and course.lessons.exists():
                        self.stdout.write(f'Skip {course.slug} [{lang}] — already complete')
                        continue
                self.stdout.write(f'Generating {course.slug} [{lang}]...')
                generate_course_translation(course, lang)
                self.stdout.write('  course metadata done')
                generate_module_translations_for_course(course, lang)
                self.stdout.write('  module metadata done')
                lessons = list(course.lessons.all())
                for index, lesson in enumerate(lessons, start=1):
                    self.stdout.write(f'  lesson {index}/{len(lessons)}: {lesson.slug}')
                    generate_lesson_translation(lesson, lang)
                    generate_quiz_question_translations(lesson, lang)
                publish_course_translations_for_language(course, lang)
                self.stdout.write(self.style.SUCCESS(f'Published {course.slug} [{lang}]'))
