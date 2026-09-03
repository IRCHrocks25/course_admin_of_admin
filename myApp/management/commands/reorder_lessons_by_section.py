"""Reorder module lessons by section number (2.3 before 2.3.1 before 2.4) and clean titles.

Usage:
    python manage.py reorder_lessons_by_section --course-id 117 --dry-run
    python manage.py reorder_lessons_by_section --course-id 117
    python manage.py reorder_lessons_by_section --course-slug liquid-gym-2 --tenant liquidgym
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from myApp.models import Course, Lesson
from myApp.utils.lesson_hierarchy import clean_lesson_nav_title, sort_lessons_by_section


class Command(BaseCommand):
    help = 'Reorder lessons within each module by section number and clean CHAPTER echo titles.'

    def add_arguments(self, parser):
        parser.add_argument('--course-id', type=int)
        parser.add_argument('--course-slug', type=str)
        parser.add_argument('--tenant', type=str, help='Tenant slug')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        course_id = options.get('course_id')
        course_slug = (options.get('course_slug') or '').strip()
        tenant_slug = (options.get('tenant') or '').strip().lower()
        dry_run = bool(options.get('dry_run'))

        if not course_id and not course_slug:
            raise CommandError('Provide --course-id or --course-slug')

        qs = Course.objects.all()
        if course_id:
            qs = qs.filter(id=course_id)
        if course_slug:
            qs = qs.filter(slug=course_slug)
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)

        courses = list(qs[:5])
        if not courses:
            raise CommandError('Course not found')
        if len(courses) > 1:
            raise CommandError('Multiple courses matched; pass --tenant or --course-id')

        course = courses[0]
        changes = 0
        with transaction.atomic():
            modules = list(course.modules.order_by('order', 'id'))
            for module in modules:
                lessons = list(module.lessons.order_by('order', 'id'))
                ordered = sort_lessons_by_section(lessons)
                for index, lesson in enumerate(ordered, start=1):
                    new_title = clean_lesson_nav_title(lesson.title)[:200] or lesson.title
                    title_changed = new_title != lesson.title
                    order_changed = lesson.order != index
                    if not title_changed and not order_changed:
                        continue
                    changes += 1
                    self.stdout.write(
                        f'module {module.id}: lesson {lesson.id} '
                        f'order {lesson.order}->{index}'
                        + (f' title "{lesson.title}" -> "{new_title}"' if title_changed else '')
                    )
                    if not dry_run:
                        update_fields = ['order']
                        lesson.order = index
                        if title_changed:
                            lesson.title = new_title
                            update_fields.append('title')
                            if lesson.working_title and 'CHAPTER' in (lesson.working_title or '').upper():
                                lesson.working_title = new_title
                                update_fields.append('working_title')
                        lesson.save(update_fields=update_fields)

            # Orphans (no module)
            orphans = list(course.lessons.filter(module__isnull=True).order_by('order', 'id'))
            ordered_orphans = sort_lessons_by_section(orphans)
            for index, lesson in enumerate(ordered_orphans, start=1):
                new_title = clean_lesson_nav_title(lesson.title)[:200] or lesson.title
                if lesson.order == index and new_title == lesson.title:
                    continue
                changes += 1
                self.stdout.write(f'orphan lesson {lesson.id}: order {lesson.order}->{index}')
                if not dry_run:
                    lesson.order = index
                    fields = ['order']
                    if new_title != lesson.title:
                        lesson.title = new_title
                        fields.append('title')
                    lesson.save(update_fields=fields)

            if dry_run:
                transaction.set_rollback(True)

        if changes == 0:
            self.stdout.write(self.style.WARNING('No order/title changes needed.'))
        elif dry_run:
            self.stdout.write(self.style.SUCCESS(f'Dry run: {changes} planned changes.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated {changes} lesson(s).'))
