"""
Make every lesson quiz optional across all tenants.

A quiz with ``is_required=True`` blocks a student from completing the lesson
(myApp/views.py: "if quiz.is_required") and counts toward the "required
quizzes" gate that must be cleared before the course/certificate unlocks
(myApp/views.py: LessonQuiz.objects.filter(is_required=True)). Flipping
``is_required`` to ``False`` leaves the quiz in place but lets learners move on
to the next lesson/course without passing it.

Usage:
    python manage.py make_quizzes_optional                 # apply to all tenants
    python manage.py make_quizzes_optional --dry-run       # preview only
    python manage.py make_quizzes_optional --tenant acme   # one tenant by slug
    python manage.py make_quizzes_optional --revert         # make them required again
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from myApp.models import LessonQuiz, Tenant


class Command(BaseCommand):
    help = 'Toggle all lesson quizzes to optional (is_required=False) so learners can progress without passing them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without writing to the database.',
        )
        parser.add_argument(
            '--revert',
            action='store_true',
            help='Reverse the operation: make all quizzes required again (is_required=True).',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help='Limit to a single tenant by slug. Defaults to all tenants.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        revert = options['revert']
        tenant_slug = options['tenant']

        # Target state: optional by default, required when --revert is passed.
        target_required = bool(revert)
        target_word = 'REQUIRED' if target_required else 'OPTIONAL'

        quizzes = LessonQuiz.objects.all()

        if tenant_slug:
            tenant = Tenant.objects.filter(slug=tenant_slug).first()
            if tenant is None:
                self.stderr.write(self.style.ERROR(f'No tenant found with slug "{tenant_slug}".'))
                return
            quizzes = quizzes.filter(tenant=tenant)
            scope = f'tenant "{tenant.name}" ({tenant.slug})'
        else:
            scope = 'ALL tenants'

        total = quizzes.count()
        # Rows that actually need flipping (already-correct rows are left alone).
        to_change = quizzes.exclude(is_required=target_required)
        change_count = to_change.count()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Making lesson quizzes {target_word} for {scope}'
        ))
        self.stdout.write(f'  Quizzes in scope : {total}')
        self.stdout.write(f'  Already {target_word.lower():<8}: {total - change_count}')
        self.stdout.write(f'  Will change      : {change_count}')

        # Per-tenant breakdown of what changes, so the operator can sanity-check.
        breakdown = (
            to_change
            .values('tenant__slug', 'tenant__name')
            .annotate(n=Count('id'))
            .order_by('tenant__name')
        )
        for row in breakdown:
            name = row['tenant__name'] or 'Unassigned tenant'
            slug = row['tenant__slug'] or '—'
            self.stdout.write(f'    - {name} ({slug}): {row["n"]}')

        if change_count == 0:
            self.stdout.write(self.style.SUCCESS('\nNothing to do — all quizzes already in the target state.'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN — no changes written. Re-run without --dry-run to apply.'))
            return

        # Single bulk UPDATE: fast, atomic, and skips per-row save() side effects.
        updated = to_change.update(is_required=target_required)
        self.stdout.write(self.style.SUCCESS(
            f'\nUpdated {updated} quiz(zes) to is_required={target_required} ({target_word}).'
        ))
        if not target_required:
            self.stdout.write(self.style.SUCCESS(
                'Learners can now advance to the next lesson/course without passing these quizzes.'
            ))
