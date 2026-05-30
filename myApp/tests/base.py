"""
Shared seeding + helpers for the role-based URL sweep and (future) tenant-isolation tests.

Two tenants are seeded so isolation tests can assert that tenant A's admin cannot
reach tenant B's objects. Requests resolve their tenant via the ``?tenant=<slug>``
dev override that TenantMiddleware honours on platform hosts (localhost), so every
request in these tests is made with HTTP_HOST=localhost.
"""
import re

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch

from myApp import models as M

# Roles exercised by the sweep. Keys are used in expectation tables.
ROLES = ("anon", "student", "admin", "super")

# Platform host so the ``?tenant=`` override in TenantMiddleware applies.
PLATFORM_HOST = "localhost"


class SeededTestCase(TestCase):
    """Base case that seeds two complete tenants (A=acme, B=globex).

    Subclass this for URL sweeps and tenant-isolation assertions. Object handles
    are exposed as class attributes (e.g. ``cls.course_a``, ``cls.course_b``).
    """

    @classmethod
    def setUpTestData(cls):
        # Platform superuser (no tenant membership).
        cls.superuser = User.objects.create_superuser("root", "root@example.com", "pw-super-123")

        # ── Tenant A (acme) ──
        cls.tenant_a = M.Tenant.objects.create(
            name="Acme", slug="acme", is_active=True, is_archived=False,
        )
        cls.admin_a = User.objects.create_user(
            "admin_a", "admin_a@example.com", "pw-admin-123", is_staff=True,
        )
        cls.student_a = User.objects.create_user(
            "student_a", "student_a@example.com", "pw-stud-123",
        )
        M.TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.admin_a, role="tenant_admin", is_active=True,
        )
        M.TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.student_a, role="student", is_active=True,
        )
        cls.course_a, cls.lesson_a = cls._seed_course(cls.tenant_a, "acme")
        M.CourseEnrollment.objects.create(
            tenant=cls.tenant_a, user=cls.student_a, course=cls.course_a,
        )
        cls.bundle_a = M.Bundle.objects.create(
            tenant=cls.tenant_a, name="Acme Bundle", slug="acme-bundle", price=10,
        )
        cls.post_a, cls.comment_a = cls._seed_forum(cls.tenant_a, cls.student_a)

        # ── Tenant B (globex) — for isolation tests ──
        cls.tenant_b = M.Tenant.objects.create(
            name="Globex", slug="globex", is_active=True, is_archived=False,
        )
        cls.admin_b = User.objects.create_user(
            "admin_b", "admin_b@example.com", "pw-admin-123", is_staff=True,
        )
        M.TenantMembership.objects.create(
            tenant=cls.tenant_b, user=cls.admin_b, role="tenant_admin", is_active=True,
        )
        cls.course_b, cls.lesson_b = cls._seed_course(cls.tenant_b, "globex")

    # ── seed helpers ──
    @staticmethod
    def _seed_course(tenant, prefix):
        course = M.Course.objects.create(
            tenant=tenant, name=f"{prefix.title()} Course",
            slug=f"{prefix}-course", status="active",
        )
        lesson = M.Lesson.objects.create(
            tenant=tenant, course=course,
            title=f"{prefix.title()} Lesson", slug=f"{prefix}-lesson",
        )
        return course, lesson

    @staticmethod
    def _seed_forum(tenant, author):
        category = M.ForumCategory.objects.create(tenant=tenant, name="General")
        post = M.ForumPost.objects.create(
            tenant=tenant, author=author, content="hello world", category=category,
        )
        comment = M.ForumComment.objects.create(
            tenant=tenant, post=post, author=author, content="a comment",
        )
        return post, comment

    # ── request helpers ──
    def client_for(self, role):
        """Return a Client logged in as the given role, pinned to the platform host."""
        client = Client(HTTP_HOST=PLATFORM_HOST)
        user = {
            "anon": None,
            "student": self.student_a,
            "admin": self.admin_a,
            "super": self.superuser,
        }[role]
        if user is not None:
            client.force_login(user)
        return client

    def get(self, url, role="anon", tenant_slug="acme"):
        """GET ``url`` as ``role`` with the tenant dev-override applied."""
        return self.client_for(role).get(url, {"tenant": tenant_slug})

    # ── URL building (mirrors the manual sweep) ──
    # Sample kwargs for parametrized URLs, pointing at seeded tenant-A objects.
    def _sample_kwargs(self):
        return {
            "course_slug": self.course_a.slug,
            "lesson_slug": self.lesson_a.slug,
            "lesson_id": self.lesson_a.id,
            "course_id": self.course_a.id,
            "bundle_id": self.bundle_a.id,
            "post_id": self.post_a.id,
            "comment_id": self.comment_a.id,
            "tenant_id": self.tenant_a.id,
            "user_id": self.student_a.id,
            "tenant_slug": "acme",
            "certificate_id": "ABC123",
            "tier_code": "starter",
            "interval": "monthly",
            "domain_id": 1, "exam_id": 1, "tier_id": 1,
            "notification_id": 1, "delivery_id": 1,
        }

    def reverse_pattern(self, pattern):
        """Reverse a URLPattern using sample kwargs, or None if it can't be built."""
        params = re.findall(r"\(\?P<(\w+)>", pattern.pattern.regex.pattern)
        sample = self._sample_kwargs()
        try:
            return reverse(pattern.name, kwargs={p: sample[p] for p in params})
        except (NoReverseMatch, KeyError):
            return None
