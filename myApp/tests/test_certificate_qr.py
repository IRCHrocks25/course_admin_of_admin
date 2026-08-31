from unittest import mock

from django.test import RequestFactory, TestCase

from myApp.models import Tenant
from myApp.utils.domains import build_certificate_verification_url, get_public_origin


class CertificateVerificationUrlTests(TestCase):
    """QR codes must encode the live tenant host, never localhost."""

    def test_uses_tenant_public_domain_not_localhost(self):
        with mock.patch.dict(
            'os.environ',
            {'PLATFORM_BASE_DOMAIN': 'courseforge.katek-ai.com'},
        ):
            tenant = Tenant.objects.create(name='Acme', slug='acme')
            request = RequestFactory().get('/')
            request.META['HTTP_HOST'] = 'localhost:8000'
            url = build_certificate_verification_url(
                'CERT-ACME-1',
                tenant=tenant,
                request=request,
            )
            self.assertEqual(
                url,
                'https://acme.courseforge.katek-ai.com/verify-certificate/CERT-ACME-1/',
            )
            self.assertNotIn('localhost', url)

    def test_skips_wildcard_and_local_hosts(self):
        with mock.patch.dict(
            'os.environ',
            {'PLATFORM_BASE_DOMAIN': 'courseforge.katek.app'},
        ):
            request = RequestFactory().get('/')
            request.META['HTTP_HOST'] = '127.0.0.1:8000'
            origin = get_public_origin(request=request, tenant=None)
            self.assertEqual(origin, 'https://courseforge.katek.app')

    def test_prefers_request_host_when_it_is_public(self):
        with mock.patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('PLATFORM_BASE_DOMAIN', None)
            request = RequestFactory().get('/')
            request.META['HTTP_HOST'] = 'academy.example.com'
            origin = get_public_origin(request=request, tenant=None)
            self.assertEqual(origin, 'https://academy.example.com')
