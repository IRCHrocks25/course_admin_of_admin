"""
Role-based URL regression net.

Covers three things:
  1. test_no_url_returns_500   — every GET-able URL, every role, must never 500.
  2. test_access_contract      — curated pages assert the EXACT status per role
                                 (200 where expected, 302 redirect for wrong-role).
  3. test_tenant_isolation_*   — example isolation assertions; extend these as the
                                 tenant-isolation workstream proceeds.

Run: ``python manage.py test myApp``
"""
from django.urls import get_resolver

from .base import SeededTestCase, ROLES

# Named URLs the sweep should not GET (webhooks / health / logout side effects).
SKIP_NAMES = {
    "logout", "stripe_webhook", "stripe_tenant_webhook", "healthz", "readyz",
}


class NoServerErrorSweepTest(SeededTestCase):
    """No URL may return HTTP 500 for any role (the bug class this net guards)."""

    def test_no_url_returns_500(self):
        patterns = [p for p in get_resolver().url_patterns if getattr(p, "name", None)]
        checked = 0
        for pattern in patterns:
            if pattern.name in SKIP_NAMES:
                continue
            url = self.reverse_pattern(pattern)
            if url is None:
                continue
            for role in ROLES:
                with self.subTest(url=pattern.name, role=role):
                    resp = self.get(url, role=role)
                    self.assertNotEqual(
                        resp.status_code, 500,
                        msg=f"{pattern.name} returned 500 for role={role}",
                    )
                checked += 1
        self.assertGreater(checked, 100, "sweep should cover the full URL surface")


class AccessContractTest(SeededTestCase):
    """Exact status per role for the important pages. 200 = authorized + renders;
    302 = redirected (anon -> login, or wrong-role bounced)."""

    # name -> (kwargs, {role: expected_status})
    EXPECTATIONS = {
        # ── public ──
        "home":                      ({}, {"anon": 200, "student": 200, "admin": 200, "super": 200}),
        "courses":                   ({}, {"anon": 200, "student": 200, "admin": 200, "super": 200}),
        "verify_certificate":        ({"certificate_id": "ABC123"}, {"anon": 200, "student": 200, "admin": 200, "super": 200}),
        "login":                     ({}, {"anon": 200, "student": 302, "admin": 302, "super": 302}),
        "register":                  ({}, {"anon": 200, "student": 302, "admin": 302, "super": 302}),

        # ── student-facing (login required) ──
        "student_certifications":    ({}, {"anon": 302, "student": 200, "admin": 200, "super": 200}),
        "student_course_progress":   ("course", {"anon": 302, "student": 200, "admin": 200, "super": 200}),
        "course_detail":             ("course", {"anon": 302, "student": 200, "admin": 200, "super": 200}),
        "lesson_detail":             ("lesson", {"anon": 302, "student": 200, "admin": 200, "super": 200}),
        # forum requires tenant membership; super has none in tenant A -> 302
        "forum_feed":                ({}, {"anon": 302, "student": 200, "admin": 200, "super": 302}),

        # ── dashboard (staff only) ──
        "dashboard_home":            ({}, {"anon": 302, "student": 302, "admin": 200, "super": 200}),
        "dashboard_analytics":       ({}, {"anon": 302, "student": 302, "admin": 200, "super": 200}),
        "dashboard_courses":         ({}, {"anon": 302, "student": 302, "admin": 200, "super": 200}),
        "dashboard_students":        ({}, {"anon": 302, "student": 302, "admin": 200, "super": 200}),
        # ↓ the two templates created in the audit fix
        "dashboard_student_progress": ({}, {"anon": 302, "student": 302, "admin": 200, "super": 200}),
        "dashboard_course_progress": ("course", {"anon": 302, "student": 302, "admin": 200, "super": 200}),

        # ── superadmin (superuser only) ──
        "superadmin_home":           ({}, {"anon": 302, "student": 302, "admin": 302, "super": 200}),
        "superadmin_tenants":        ({}, {"anon": 302, "student": 302, "admin": 302, "super": 200}),
        # ↓ the two annotation-conflict crashes fixed in the audit
        "superadmin_analytics":      ({}, {"anon": 302, "student": 302, "admin": 302, "super": 200}),
        "superadmin_tenant_analytics": ("tenant", {"anon": 302, "student": 302, "admin": 302, "super": 200}),
    }

    def _kwargs(self, spec):
        """spec is either a kwargs dict or a shorthand string key."""
        if spec == "course":
            return {"course_slug": self.course_a.slug}
        if spec == "lesson":
            return {"course_slug": self.course_a.slug, "lesson_slug": self.lesson_a.slug}
        if spec == "tenant":
            return {"tenant_id": self.tenant_a.id}
        return spec

    def test_access_contract(self):
        from django.urls import reverse
        for name, (spec, expected) in self.EXPECTATIONS.items():
            url = reverse(name, kwargs=self._kwargs(spec))
            for role, want in expected.items():
                with self.subTest(url=name, role=role):
                    resp = self.get(url, role=role)
                    self.assertEqual(
                        resp.status_code, want,
                        msg=f"{name} role={role}: expected {want}, got {resp.status_code}",
                    )


class TenantIsolationTest(SeededTestCase):
    """Example isolation assertions. The next workstream extends this class with
    one assertion per object-by-id view: tenant A's admin must NOT reach tenant B's
    objects (expect 404/302, never 200 with B's data)."""

    def test_dashboard_course_detail_is_tenant_scoped(self):
        from django.urls import reverse
        # Positive control: admin_a can open their own course.
        own = self.get(reverse("dashboard_course_detail", kwargs={"course_slug": self.course_a.slug}), role="admin")
        self.assertEqual(own.status_code, 200)
        # Isolation: admin_a must NOT open tenant B's course.
        other = self.get(reverse("dashboard_course_detail", kwargs={"course_slug": self.course_b.slug}), role="admin")
        self.assertNotEqual(
            other.status_code, 200,
            msg="tenant A admin reached tenant B course detail (isolation leak)",
        )
