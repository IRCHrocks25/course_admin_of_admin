"""
Split lessons that flattened nested X.Y.Z headers into standalone sibling lessons.

Use this to repair courses imported before nested sections were promoted to
their own lessons (e.g. Liquid Gym). Finds header blocks whose text starts
with ``N.N.N`` and moves that header plus following blocks into a new Lesson
in the same module.

Usage:
    python manage.py split_nested_lesson_headers --course-id 117 --dry-run
    python manage.py split_nested_lesson_headers --course-id 117
    python manage.py split_nested_lesson_headers --course-slug liquid-gym-2 --tenant acme
"""
from __future__ import annotations

import copy
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from myApp.models import Course, Lesson

NESTED_HEADER_RE = re.compile(r'^(\d+\.\d+\.\d+)\s*(.*)$')


def _blocks_from_content(content: Any) -> list[dict]:
    if isinstance(content, dict):
        blocks = content.get('blocks') or []
        return blocks if isinstance(blocks, list) else []
    return []


def _header_text(block: dict) -> str:
    data = block.get('data') if isinstance(block.get('data'), dict) else {}
    return (data.get('text') or '').strip()


def _split_points(blocks: list[dict]) -> list[tuple[int, str, str]]:
    """Return (index, full_key, title_suffix) for nested section headers."""
    points = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get('type') != 'header':
            continue
        match = NESTED_HEADER_RE.match(_header_text(block))
        if not match:
            continue
        key = match.group(1)
        suffix = (match.group(2) or '').strip()
        points.append((index, key, suffix))
    return points


def _unique_slug(course: Course, base: str, exclude_id: int | None = None) -> str:
    base = slugify(base)[:180] or 'lesson'
    candidate = base
    n = 2
    while True:
        qs = course.lessons.filter(slug=candidate)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        if not qs.exists():
            return candidate
        candidate = f'{base}-{n}'
        n += 1


def split_lesson(lesson: Lesson, dry_run: bool = False) -> list[str]:
    """Split one lesson; return human-readable change lines."""
    blocks = _blocks_from_content(lesson.content)
    points = _split_points(blocks)
    if not points:
        return []

    changes: list[str] = []
    # Keep content before the first nested header on the original lesson.
    first_idx = points[0][0]
    remaining = copy.deepcopy(blocks[:first_idx])

    created_specs: list[tuple[str, list[dict]]] = []
    for i, (start, key, suffix) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else len(blocks)
        chunk = copy.deepcopy(blocks[start:end])
        title = f'{key} {suffix}'.strip() if suffix else key
        created_specs.append((title[:200], chunk))

    if dry_run:
        changes.append(
            f'lesson {lesson.id} "{lesson.title}": would keep {len(remaining)} blocks; '
            f'create {len(created_specs)} lessons: '
            + ', '.join(t for t, _ in created_specs)
        )
        return changes

    module = lesson.module
    base_order = lesson.order
    # Shift later siblings to make room for new lessons.
    shift = len(created_specs)
    siblings = (
        Lesson.objects.filter(course=lesson.course, module=module, order__gt=base_order)
        .exclude(id=lesson.id)
        .order_by('-order', '-id')
    )
    for sib in siblings:
        sib.order = sib.order + shift
        sib.save(update_fields=['order'])

    lesson.content = {
        'time': (lesson.content or {}).get('time') if isinstance(lesson.content, dict) else None,
        'blocks': remaining,
        'version': (lesson.content or {}).get('version', '2.28.2') if isinstance(lesson.content, dict) else '2.28.2',
    }
    if lesson.content['time'] is None:
        lesson.content.pop('time', None)
    lesson.save(update_fields=['content'])
    changes.append(f'lesson {lesson.id} "{lesson.title}": kept {len(remaining)} leading blocks')

    for offset, (title, chunk) in enumerate(created_specs, start=1):
        new_lesson = Lesson.objects.create(
            course=lesson.course,
            module=module,
            tenant=lesson.tenant or lesson.course.tenant,
            title=title,
            working_title=title,
            slug=_unique_slug(lesson.course, title),
            description='',
            order=base_order + offset,
            content={'blocks': chunk, 'version': '2.28.2'},
            lesson_type=lesson.lesson_type or 'video',
            show_what_youll_learn=lesson.show_what_youll_learn,
            show_lesson_notes=lesson.show_lesson_notes,
        )
        changes.append(f'  created lesson {new_lesson.id} "{new_lesson.title}" order={new_lesson.order}')

    return changes


class Command(BaseCommand):
    help = 'Split flattened X.Y.Z header sections inside lessons into standalone sibling lessons.'

    def add_arguments(self, parser):
        parser.add_argument('--course-id', type=int, help='Course primary key')
        parser.add_argument('--course-slug', type=str, help='Course slug')
        parser.add_argument('--tenant', type=str, help='Tenant slug (required when using --course-slug with duplicates)')
        parser.add_argument('--lesson-id', type=int, help='Limit to a single lesson id')
        parser.add_argument('--dry-run', action='store_true', help='Preview only')

    def handle(self, *args, **options):
        course_id = options.get('course_id')
        course_slug = (options.get('course_slug') or '').strip()
        tenant_slug = (options.get('tenant') or '').strip().lower()
        lesson_id = options.get('lesson_id')
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
        lessons = course.lessons.order_by('module__order', 'order', 'id')
        if lesson_id:
            lessons = lessons.filter(id=lesson_id)

        total_changes = 0
        with transaction.atomic():
            for lesson in lessons:
                lines = split_lesson(lesson, dry_run=dry_run)
                for line in lines:
                    self.stdout.write(line)
                total_changes += len(lines)
            if dry_run:
                transaction.set_rollback(True)

        if total_changes == 0:
            self.stdout.write(self.style.WARNING('No nested X.Y.Z headers found to split.'))
        elif dry_run:
            self.stdout.write(self.style.SUCCESS(f'Dry run complete ({total_changes} planned changes).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Done ({total_changes} changes).'))
