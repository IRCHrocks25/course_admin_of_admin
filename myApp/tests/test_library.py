"""Academy Library: standalone content model, membership gate, dashboard CRUD."""
from django.urls import reverse

from myApp import models as M
from myApp.tests.base import PLATFORM_HOST, SeededTestCase
from myApp.utils.access import can_access_library


SECRET_MEDIA = 'https://cdn.example.com/secret-webinar-xyz.mp4'


class LibraryAccessHelperTests(SeededTestCase):
    def test_staff_can_preview_without_membership(self):
        self.assertTrue(can_access_library(self.admin_a, self.tenant_a))
        self.assertTrue(can_access_library(self.superuser, self.tenant_a))

    def test_student_needs_active_subscription(self):
        self.assertFalse(can_access_library(self.student_a, self.tenant_a))
        M.StudentSubscription.objects.create(
            tenant=self.tenant_a,
            user=self.student_a,
            status='active',
            access_mode='all_access',
            is_complimentary=True,
        )
        self.assertTrue(can_access_library(self.student_a, self.tenant_a))

    def test_anonymous_denied(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(can_access_library(AnonymousUser(), self.tenant_a))


class LibraryCatalogTests(SeededTestCase):
    def setUp(self):
        self.published = M.LibraryItem.objects.create(
            tenant=self.tenant_a,
            title='Q3 Faculty Webinar',
            slug='q3-faculty-webinar',
            item_type='recording',
            status='published',
            video_url=SECRET_MEDIA,
            short_description='Replay of the faculty session.',
        )
        self.draft = M.LibraryItem.objects.create(
            tenant=self.tenant_a,
            title='Unreleased Tool',
            slug='unreleased-tool',
            item_type='tool',
            status='draft',
            file_url='https://cdn.example.com/draft-tool.zip',
        )

    def test_published_lists_for_everyone_draft_hidden(self):
        for role in ('anon', 'student', 'admin'):
            resp = self.get(reverse('library'), role=role)
            self.assertEqual(resp.status_code, 200, role)
            self.assertContains(resp, 'Q3 Faculty Webinar')
            self.assertNotContains(resp, 'Unreleased Tool')

    def test_non_member_html_does_not_contain_media_url(self):
        resp = self.get(reverse('library'), role='student')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, SECRET_MEDIA)
        self.assertContains(resp, 'Members only')

    def test_member_can_see_media_url(self):
        M.StudentSubscription.objects.create(
            tenant=self.tenant_a,
            user=self.student_a,
            status='active',
            access_mode='all_access',
            is_complimentary=True,
        )
        resp = self.get(reverse('library'), role='student')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, SECRET_MEDIA)

    def test_staff_can_see_media_url(self):
        resp = self.get(reverse('library'), role='admin')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, SECRET_MEDIA)


class LibraryDashboardTests(SeededTestCase):
    def test_create_item_does_not_create_a_course(self):
        course_count = M.Course.objects.count()
        client = self.client_for('admin')
        resp = client.post(
            reverse('dashboard_library') + '?tenant=acme',
            {
                'action': 'save_item',
                'title': 'NCD Toolkit',
                'item_type': 'tool',
                'file_url': 'https://example.com/toolkit.pdf',
                'published': '1',
                'short_description': 'Member toolkit.',
            },
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(reverse('dashboard_library'), resp.url.split('?')[0])
        item = M.LibraryItem.objects.get(tenant=self.tenant_a, title='NCD Toolkit')
        self.assertEqual(item.item_type, 'tool')
        self.assertEqual(item.status, 'published')
        self.assertEqual(item.file_url, 'https://example.com/toolkit.pdf')
        self.assertTrue(item.slug)
        self.assertEqual(M.Course.objects.count(), course_count)

    def test_edit_and_delete_stay_on_library_page(self):
        item = M.LibraryItem.objects.create(
            tenant=self.tenant_a,
            title='Old Title',
            slug='old-title',
            item_type='document',
            status='draft',
            file_url='https://example.com/old.pdf',
        )
        client = self.client_for('admin')
        edit = client.post(
            reverse('dashboard_library') + '?tenant=acme',
            {
                'action': 'save_item',
                'item_id': str(item.id),
                'title': 'Updated Title',
                'item_type': 'document',
                'file_url': 'https://example.com/new.pdf',
                'published': '1',
            },
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(edit.status_code, 302)
        self.assertEqual(reverse('dashboard_library'), edit.url.split('?')[0])
        item.refresh_from_db()
        self.assertEqual(item.title, 'Updated Title')
        self.assertEqual(item.status, 'published')
        self.assertEqual(item.slug, 'old-title')

        delete = client.post(
            reverse('dashboard_library') + '?tenant=acme',
            {'action': 'delete_item', 'item_id': str(item.id)},
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(delete.status_code, 302)
        self.assertEqual(reverse('dashboard_library'), delete.url.split('?')[0])
        self.assertFalse(M.LibraryItem.objects.filter(id=item.id).exists())

    def test_student_cannot_open_dashboard_library(self):
        resp = self.get(reverse('dashboard_library'), role='student')
        self.assertEqual(resp.status_code, 302)
