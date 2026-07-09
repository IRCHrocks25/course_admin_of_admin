"""Tests for lesson translation resolution and tenant language config."""
from django.test import TestCase, Client

from django.contrib.auth.models import User

from myApp import models as M
from myApp.utils.lesson_i18n import (
    resolve_lesson_display,
    get_tenant_lesson_languages,
    save_tenant_lesson_languages,
    show_language_switcher,
    build_lesson_title_map,
)
from myApp.tests.base import PLATFORM_HOST


class LessonI18nTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = M.Tenant.objects.create(name='Lang Tenant', slug='lang-tenant', is_active=True)
        cls.course = M.Course.objects.create(
            tenant=cls.tenant, name='Lang Course', slug='lang-course', status='active',
        )
        cls.lesson = M.Lesson.objects.create(
            tenant=cls.tenant,
            course=cls.course,
            title='English Title',
            slug='english-lesson',
            description='English description body',
            ai_clean_title='English Clean Title',
            ai_full_description='English full description',
            ai_outcomes=['Outcome A'],
            content={
                'blocks': [
                    {'type': 'paragraph', 'data': {'text': 'English paragraph'}},
                ],
                'version': '2.28.2',
            },
        )
        cls.student = User.objects.create_user(
            'lang_student', 'lang_student@example.com', 'pw-stud-123',
        )
        M.TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.student, role='student', is_active=True,
        )
        M.CourseEnrollment.objects.create(tenant=cls.tenant, user=cls.student, course=cls.course)

    def test_english_only_tenant_returns_english_display(self):
        display = resolve_lesson_display(self.lesson, 'en')
        self.assertEqual(display.title, 'English Clean Title')
        self.assertEqual(display.content['blocks'][0]['data']['text'], 'English paragraph')
        self.assertFalse(display.is_translated)

    def test_unapproved_translation_falls_back_to_english(self):
        M.LessonTranslation.objects.create(
            lesson=self.lesson,
            language_code='it',
            title='Titolo Italiano',
            ai_full_description='Descrizione italiana',
            content={'blocks': [{'type': 'paragraph', 'data': {'text': 'Paragrafo italiano'}}]},
            status='generated',
        )
        display = resolve_lesson_display(self.lesson, 'it')
        self.assertEqual(display.title, 'English Clean Title')
        self.assertFalse(display.is_translated)

    def test_approved_translation_overrides_fields(self):
        M.LessonTranslation.objects.create(
            lesson=self.lesson,
            language_code='it',
            title='Titolo Italiano',
            ai_clean_title='Titolo Italiano',
            ai_full_description='Descrizione italiana',
            content={'blocks': [{'type': 'paragraph', 'data': {'text': 'Paragrafo italiano'}}]},
            status='published',
        )
        display = resolve_lesson_display(self.lesson, 'it')
        self.assertEqual(display.title, 'Titolo Italiano')
        self.assertEqual(display.content['blocks'][0]['data']['text'], 'Paragrafo italiano')
        self.assertTrue(display.is_translated)

    def test_partial_translation_falls_back_per_field(self):
        M.LessonTranslation.objects.create(
            lesson=self.lesson,
            language_code='it',
            title='Solo Titolo',
            ai_clean_title='Solo Titolo',
            status='published',
        )
        display = resolve_lesson_display(self.lesson, 'it')
        self.assertEqual(display.title, 'Solo Titolo')
        self.assertEqual(display.ai_full_description, 'English full description')
        self.assertEqual(display.content['blocks'][0]['data']['text'], 'English paragraph')

    def test_tenant_language_config_defaults(self):
        config = get_tenant_lesson_languages(self.tenant)
        self.assertEqual(config['enabled'], ['en'])
        self.assertFalse(show_language_switcher(self.tenant, config))

    def test_tenant_language_config_enable_italian(self):
        save_tenant_lesson_languages(self.tenant, {
            'enabled': ['en', 'it'],
            'default': 'en',
            'allow_student_switch': True,
        })
        config = get_tenant_lesson_languages(self.tenant)
        self.assertIn('it', config['enabled'])
        self.assertTrue(show_language_switcher(self.tenant, config))

    def test_build_lesson_title_map(self):
        M.LessonTranslation.objects.create(
            lesson=self.lesson,
            language_code='it',
            title='Titolo',
            ai_clean_title='Titolo',
            status='published',
        )
        title_map = build_lesson_title_map([self.lesson], 'it')
        self.assertEqual(title_map[self.lesson.id], 'Titolo')

    def test_lesson_page_english_only_has_no_switcher(self):
        client = Client(HTTP_HOST=PLATFORM_HOST)
        client.force_login(self.student)
        url = f'/courses/{self.course.slug}/{self.lesson.slug}/?tenant={self.tenant.slug}'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'language-switcher')

    def test_lesson_page_with_italian_shows_switcher_and_translation(self):
        save_tenant_lesson_languages(self.tenant, {
            'enabled': ['en', 'it'],
            'default': 'en',
            'allow_student_switch': True,
        })
        M.LessonTranslation.objects.create(
            lesson=self.lesson,
            language_code='it',
            title='Titolo Italiano',
            ai_clean_title='Titolo Italiano',
            ai_full_description='Descrizione italiana',
            status='published',
        )
        client = Client(HTTP_HOST=PLATFORM_HOST)
        client.force_login(self.student)
        url = f'/courses/{self.course.slug}/{self.lesson.slug}/?tenant={self.tenant.slug}&lang=it'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'language-switcher')
        self.assertContains(response, 'Titolo Italiano')
        self.assertNotContains(response, 'English Clean Title')

    def test_progress_unchanged_by_language(self):
        save_tenant_lesson_languages(self.tenant, {
            'enabled': ['en', 'it'],
            'default': 'en',
            'allow_student_switch': True,
        })
        progress = M.UserProgress.objects.create(
            tenant=self.tenant,
            user=self.student,
            lesson=self.lesson,
            completed=True,
            status='completed',
        )
        client = Client(HTTP_HOST=PLATFORM_HOST)
        client.force_login(self.student)
        url = f'/courses/{self.course.slug}/{self.lesson.slug}/?tenant={self.tenant.slug}&lang=it'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        progress.refresh_from_db()
        self.assertTrue(progress.completed)
        self.assertEqual(progress.lesson_id, self.lesson.id)
