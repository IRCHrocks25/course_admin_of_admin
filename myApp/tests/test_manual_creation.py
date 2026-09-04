"""Manual Creation tab: create course, add/save lessons, attach resources."""
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from myApp import models as M
from myApp.tests.base import PLATFORM_HOST, SeededTestCase


class ManualCreationApiTests(SeededTestCase):
    def _admin(self):
        client = self.client_for('admin')
        return client

    def _post_json(self, client, url, payload):
        return client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_HOST=PLATFORM_HOST,
        )

    def test_create_course_requires_title(self):
        client = self._admin()
        resp = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json().get('ok', True))

    def test_create_course_and_add_lesson(self):
        client = self._admin()
        resp = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {
                'title': 'Handmade Espresso',
                'short_description': 'Pull a shot by hand.',
                'pricing_type': 'free',
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data['ok'])
        course = M.Course.objects.get(id=data['course_id'])
        self.assertEqual(course.tenant_id, self.tenant_a.id)
        self.assertEqual(course.name, 'Handmade Espresso')
        self.assertEqual(course.modules.count(), 1)
        self.assertEqual(course.creation_blueprint.get('source'), 'manual_creation')
        self.assertEqual(data['live_url'], f'/courses/{course.slug}/')

        lesson_resp = self._post_json(
            client,
            reverse('dashboard_manual_add_lesson') + '?tenant=acme',
            {'course_slug': course.slug},
        )
        self.assertEqual(lesson_resp.status_code, 200, lesson_resp.content)
        lesson_data = lesson_resp.json()
        self.assertTrue(lesson_data['ok'])
        lesson = M.Lesson.objects.get(id=lesson_data['lesson_id'])
        self.assertEqual(lesson.course_id, course.id)
        self.assertEqual(lesson.ai_generation_status, 'approved')
        self.assertTrue(lesson.show_what_youll_learn)
        self.assertTrue(lesson.show_lesson_notes)
        self.assertEqual(lesson.what_youll_learn_heading, "What You'll Learn Today")
        self.assertIn('upload_image_url', lesson_data)
        self.assertIn('upload_video_url', lesson_data)
        self.assertIn(str(lesson.id), lesson_data['save_notes_url'])
        self.assertEqual(lesson_data.get('hero_url'), '')
        self.assertEqual(lesson_data.get('upload_hero_url'), reverse('dashboard_manual_upload_hero'))
        self.assertEqual(lesson_data.get('hero_video_url'), '')
        self.assertEqual(lesson_data.get('upload_hero_video_url'), reverse('dashboard_manual_save_hero_video'))

    def test_upload_and_delete_hero_image(self):
        client = self._admin()
        created = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {'title': 'Hero Course'},
        ).json()
        lesson_id = self._post_json(
            client,
            reverse('dashboard_manual_add_lesson') + '?tenant=acme',
            {'course_slug': created['slug']},
        ).json()['lesson_id']
        image = SimpleUploadedFile('hero.png', b'\x89PNG\r\n\x1a\nhero', content_type='image/png')
        hero_url = 'https://cdn.example.com/objects/hero-1'
        with patch(
            'myApp.dashboard_views.upload_lesson_hero_image',
            return_value=hero_url,
        ) as upload:
            resp = client.post(
                reverse('dashboard_manual_upload_hero') + '?tenant=acme',
                {'lesson_id': lesson_id, 'hero_image': image},
                HTTP_HOST=PLATFORM_HOST,
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(resp.json()['hero_url'], hero_url)
        upload.assert_called_once()

        with patch('myApp.dashboard_views.delete_lesson_hero_image', return_value=True) as delete:
            resp = client.post(
                reverse('dashboard_manual_upload_hero') + '?tenant=acme',
                {'lesson_id': lesson_id, 'action': 'delete'},
                HTTP_HOST=PLATFORM_HOST,
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['hero_url'], '')
        delete.assert_called_once()

    def test_save_and_delete_hero_video_url(self):
        client = self._admin()
        created = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {'title': 'Hero Video Course'},
        ).json()
        lesson_id = self._post_json(
            client,
            reverse('dashboard_manual_add_lesson') + '?tenant=acme',
            {'course_slug': created['slug']},
        ).json()['lesson_id']
        resp = client.post(
            reverse('dashboard_manual_save_hero_video') + '?tenant=acme',
            {
                'lesson_id': lesson_id,
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            },
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['ok'])
        lesson = M.Lesson.objects.get(id=lesson_id)
        self.assertEqual(lesson.video_url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        resp = client.post(
            reverse('dashboard_manual_save_hero_video') + '?tenant=acme',
            {'lesson_id': lesson_id, 'action': 'delete'},
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        lesson.refresh_from_db()
        self.assertEqual(lesson.video_url, '')

    def test_save_lesson_heading_body_and_blocks(self):
        client = self._admin()
        created = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {'title': 'Latte Art Basics'},
        ).json()
        lesson_id = self._post_json(
            client,
            reverse('dashboard_manual_add_lesson') + '?tenant=acme',
            {'course_slug': created['slug']},
        ).json()['lesson_id']

        video_url = 'https://cdn.katalyst-crm.com/objects/b3640620-ece9-68f4-ba06-d497b0e48026'
        resp = self._post_json(
            client,
            reverse('dashboard_manual_save_lesson') + '?tenant=acme',
            {
                'lesson_id': lesson_id,
                'title': 'Pouring a heart',
                'heading': 'Today’s pour',
                'learn_body': 'You will pour a clean heart in milk foam.',
                'blocks': [
                    {'type': 'paragraph', 'data': {'text': 'Steam the milk first.'}},
                    {'type': 'video', 'data': {'url': video_url, 'source': 'upload'}},
                ],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        lesson = M.Lesson.objects.get(id=lesson_id)
        self.assertEqual(lesson.title, 'Pouring a heart')
        self.assertEqual(lesson.what_youll_learn_heading, 'Today’s pour')
        self.assertEqual(lesson.ai_full_description, 'You will pour a clean heart in milk foam.')
        self.assertEqual(lesson.ai_generation_status, 'approved')
        self.assertEqual(len(lesson.content['blocks']), 2)
        self.assertEqual(lesson.content['blocks'][1]['data']['url'], video_url)

    def test_add_resource_via_url(self):
        client = self._admin()
        created = self._post_json(
            client,
            reverse('dashboard_manual_create_course') + '?tenant=acme',
            {'title': 'Macchiato Manual'},
        ).json()
        resp = client.post(
            reverse('dashboard_manual_add_resource') + '?tenant=acme',
            {
                'course_slug': created['slug'],
                'title': 'Recipe PDF',
                'resource_type': 'pdf',
                'file_url': 'https://example.com/recipe.pdf',
            },
            HTTP_HOST=PLATFORM_HOST,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data['ok'])
        course = M.Course.objects.get(slug=created['slug'], tenant=self.tenant_a)
        resource = course.resources.get(id=data['resource_id'])
        self.assertEqual(resource.title, 'Recipe PDF')
        self.assertEqual(resource.resource_type, 'pdf')
        self.assertEqual(resource.file_url, 'https://example.com/recipe.pdf')

    def test_tenant_isolation_on_add_lesson(self):
        client = self._admin()
        resp = self._post_json(
            client,
            reverse('dashboard_manual_add_lesson') + '?tenant=acme',
            {'course_slug': self.course_b.slug},
        )
        self.assertIn(resp.status_code, (404, 400))

    def test_student_page_uses_heading_and_hides_empty_body(self):
        course = M.Course.objects.create(
            tenant=self.tenant_a,
            name='Manual Student Course',
            slug='manual-student-course',
            short_description='Manual course',
            description='Manual course',
            status='active',
        )
        empty = M.Lesson.objects.create(
            tenant=self.tenant_a,
            course=course,
            title='Empty learn',
            slug='empty-learn',
            description='',
            ai_full_description='',
            what_youll_learn_heading='Ignore me',
            show_what_youll_learn=True,
            show_lesson_notes=True,
            ai_generation_status='approved',
        )
        filled = M.Lesson.objects.create(
            tenant=self.tenant_a,
            course=course,
            title='Filled learn',
            slug='filled-learn',
            description='desc',
            ai_full_description='Steam, pour, serve.',
            what_youll_learn_heading='What you will master',
            show_what_youll_learn=True,
            show_lesson_notes=True,
            ai_generation_status='approved',
            video_url='https://cdn.katalyst-crm.com/objects/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            content={
                'blocks': [
                    {
                        'type': 'video',
                        'data': {
                            'url': 'https://cdn.katalyst-crm.com/objects/b3640620-ece9-68f4-ba06-d497b0e48026',
                            'source': 'upload',
                        },
                    }
                ]
            },
        )
        M.CourseEnrollment.objects.create(
            tenant=self.tenant_a, user=self.student_a, course=course,
        )
        student = self.client_for('student')

        empty_resp = student.get(
            f'/courses/{course.slug}/{empty.slug}/?tenant=acme',
        )
        self.assertEqual(empty_resp.status_code, 200)
        self.assertNotContains(empty_resp, 'Ignore me')

        filled_resp = student.get(
            f'/courses/{course.slug}/{filled.slug}/?tenant=acme',
        )
        self.assertEqual(filled_resp.status_code, 200)
        self.assertContains(filled_resp, 'What you will master')
        self.assertContains(filled_resp, 'Steam, pour, serve.')
        self.assertContains(filled_resp, 'cdn.katalyst-crm.com/objects/b3640620-ece9-68f4-ba06-d497b0e48026')
        self.assertContains(filled_resp, '<video')
        self.assertContains(filled_resp, 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')

    def test_add_course_page_has_manual_tab(self):
        client = self._admin()
        resp = client.get(reverse('dashboard_add_course') + '?tenant=acme')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'tab-manual-creation')
        self.assertContains(resp, 'Manual Creation')
        self.assertContains(resp, 'Create your lesson')
        self.assertContains(resp, 'notes_block_editor.js')
        self.assertContains(resp, 'View live course')
        self.assertContains(resp, 'Hero image')
        self.assertContains(resp, 'Hero video')

    def test_generate_lesson_page_uses_shared_notes_editor(self):
        client = self._admin()
        url = reverse(
            'generate_lesson_ai',
            args=[self.course_a.slug, self.lesson_a.id],
        ) + '?tenant=acme'
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'notes_block_editor.js')
        self.assertContains(resp, 'data-notes-editor-root')
        self.assertContains(resp, 'CourseforgeNotesEditor.mount')
