from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings

from myApp.models import PendingRegistration, Tenant, TenantConfig, TenantMembership
from myApp.utils.registration_webhook import (
    notify_registration_webhook,
    send_test_registration_webhook,
)
from myApp.views import _activate_membership_registration

User = get_user_model()

HOOK_URL = 'https://katalyst-crm2.fly.dev/webhook/test-hook'


@override_settings(ALLOWED_HOSTS=['*'])
class RegistrationWebhookHelperTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='WEI', slug='wei', is_active=True)
        self.config = TenantConfig.objects.create(tenant=self.tenant)
        self.user = User.objects.create_user(
            username='jane', email='jane@example.com', password='pw',
        )

    def test_blank_url_does_not_post(self):
        with mock.patch('myApp.utils.registration_webhook.requests.post') as post:
            sent = notify_registration_webhook(self.tenant, self.user, source='free_signup')

        self.assertFalse(sent)
        post.assert_not_called()

    def test_set_url_posts_expected_json(self):
        self.config.registration_webhook = HOOK_URL
        self.config.save(update_fields=['registration_webhook'])

        with mock.patch('myApp.utils.registration_webhook.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            sent = notify_registration_webhook(self.tenant, self.user, source='free_signup')

        self.assertTrue(sent)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], HOOK_URL)
        payload = kwargs['json']
        self.assertEqual(payload['event'], 'user.registered')
        self.assertEqual(payload['username'], 'jane')
        self.assertEqual(payload['email'], 'jane@example.com')
        self.assertEqual(payload['user_id'], self.user.id)
        self.assertEqual(payload['tenant_slug'], 'wei')
        self.assertEqual(payload['tenant_name'], 'WEI')
        self.assertEqual(payload['source'], 'free_signup')
        self.assertIn('registered_at', payload)
        self.assertEqual(kwargs['headers']['Content-Type'], 'application/json')
        self.assertEqual(kwargs['timeout'], 8)

    def test_network_failure_is_swallowed(self):
        self.config.registration_webhook = HOOK_URL
        self.config.save(update_fields=['registration_webhook'])

        with mock.patch(
            'myApp.utils.registration_webhook.requests.post',
            side_effect=ConnectionError('down'),
        ):
            sent = notify_registration_webhook(self.tenant, self.user)

        self.assertFalse(sent)

    def test_send_test_payload_uses_source_test(self):
        self.config.registration_webhook = HOOK_URL
        self.config.save(update_fields=['registration_webhook'])

        with mock.patch('myApp.utils.registration_webhook.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.text = 'ok'
            ok, detail = send_test_registration_webhook(self.tenant)

        self.assertTrue(ok)
        self.assertEqual(detail, 'Test payload sent.')
        self.assertEqual(post.call_args.kwargs['json']['source'], 'test')
        self.assertEqual(post.call_args.kwargs['json']['username'], 'test-user')


@override_settings(ALLOWED_HOSTS=['*'])
class RegistrationWebhookSignupTests(TestCase):
    HOST = 'localhost'

    def setUp(self):
        self.tenant = Tenant.objects.create(name='WEI', slug='wei', is_active=True)
        self.config = TenantConfig.objects.create(
            tenant=self.tenant, registration_webhook=HOOK_URL,
        )

    def _register(self, username='newstudent', email='new@example.com'):
        return self.client.post(
            '/register/?tenant=wei',
            {
                'username': username,
                'email': email,
                'password': 'password123',
                'confirm_password': 'password123',
            },
            HTTP_HOST=self.HOST,
        )

    @mock.patch('myApp.utils.registration_webhook.requests.post')
    def test_free_signup_posts_once(self, post):
        post.return_value.status_code = 200
        post.return_value.text = 'ok'

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._register()

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='newstudent').exists())
        post.assert_called_once()
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['username'], 'newstudent')
        self.assertEqual(payload['email'], 'new@example.com')
        self.assertEqual(payload['source'], 'free_signup')
        self.assertEqual(payload['tenant_slug'], 'wei')

    @mock.patch('myApp.utils.registration_webhook.requests.post')
    def test_blank_url_skips_post_on_signup(self, post):
        self.config.registration_webhook = ''
        self.config.save(update_fields=['registration_webhook'])

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._register(username='blankhook', email='blank@example.com')

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='blankhook').exists())
        post.assert_not_called()

    @mock.patch(
        'myApp.utils.registration_webhook.requests.post',
        side_effect=ConnectionError('down'),
    )
    def test_webhook_failure_still_creates_account(self, _post):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._register(username='stillok', email='stillok@example.com')

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='stillok').exists())

    @mock.patch('myApp.utils.registration_webhook.requests.post')
    def test_paid_activation_posts_only_on_first_create(self, post):
        post.return_value.status_code = 200
        post.return_value.text = 'ok'
        pending = PendingRegistration.objects.create(
            tenant=self.tenant,
            username='paidstudent',
            email='paid@example.com',
            password=make_password('password123'),
            interval='month',
        )
        session = {
            'metadata': {
                'flow': 'membership_registration',
                'pending_registration_id': str(pending.id),
            },
            'subscription': 'sub_1',
            'customer': 'cus_1',
        }

        with self.captureOnCommitCallbacks(execute=True):
            user = _activate_membership_registration(session)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'paidstudent')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['json']['source'], 'membership_signup')

        with self.captureOnCommitCallbacks(execute=True):
            again = _activate_membership_registration(session)
        self.assertEqual(again.id, user.id)
        self.assertEqual(post.call_count, 1)


@override_settings(ALLOWED_HOSTS=['*'])
class RegistrationWebhookAdminTests(TestCase):
    HOST = 'localhost'

    def setUp(self):
        self.tenant = Tenant.objects.create(name='ATI', slug='ati', is_active=True)
        self.config = TenantConfig.objects.create(tenant=self.tenant)
        self.admin = User.objects.create_user(
            username='ati-admin', email='admin@ati.test', password='pw', is_staff=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.admin, role='tenant_admin', is_active=True,
        )
        self.superuser = User.objects.create_superuser(
            'root', 'root@example.com', 'pw-super-123',
        )

    def test_tenant_dashboard_saves_url(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/dashboard/integrations/registration-webhook/?tenant=ati',
            {'action': 'save', 'registration_webhook': HOOK_URL},
            HTTP_HOST=self.HOST,
        )
        self.assertEqual(resp.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.registration_webhook, HOOK_URL)

    def test_tenant_dashboard_rejects_invalid_url(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/dashboard/integrations/registration-webhook/?tenant=ati',
            {'action': 'save', 'registration_webhook': 'not-a-url'},
            HTTP_HOST=self.HOST,
        )
        self.assertEqual(resp.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.registration_webhook, '')

    @mock.patch('myApp.utils.registration_webhook.requests.post')
    def test_tenant_dashboard_sends_test_payload(self, post):
        post.return_value.status_code = 200
        post.return_value.text = 'ok'
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/dashboard/integrations/registration-webhook/?tenant=ati',
            {'action': 'test', 'registration_webhook': HOOK_URL},
            HTTP_HOST=self.HOST,
        )
        self.assertEqual(resp.status_code, 302)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['source'], 'test')

    def test_superadmin_saves_url(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(
            f'/superadmin/tenants/{self.tenant.id}/',
            {
                'name': self.tenant.name,
                'slug': self.tenant.slug,
                'custom_domain': '',
                'primary_color': '#3B82F6',
                'is_active': 'on',
                'chatbot_webhook': '',
                'registration_webhook': HOOK_URL,
                'vimeo_team_id': '',
                'accredible_issuer_id': '',
            },
            HTTP_HOST=self.HOST,
        )
        self.assertEqual(resp.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.registration_webhook, HOOK_URL)

    def test_integrations_page_shows_webhook_card(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            '/dashboard/integrations/ghl/?tenant=ati',
            HTTP_HOST=self.HOST,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Registration webhook')
        self.assertContains(resp, 'Send test payload')
