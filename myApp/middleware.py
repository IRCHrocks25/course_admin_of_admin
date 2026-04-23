import os
import re
import time

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from .models import Tenant, TenantDomain, TenantMembership


class ProtectiveThrottleMiddleware:
    """
    Lightweight route throttling for expensive write endpoints.
    Helps protect the app from burst traffic and abusive retries.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = (os.getenv('ENABLE_PROTECTIVE_THROTTLE', 'True').strip().lower() in {'1', 'true', 'yes', 'on'})
        self.rules = self._build_rules()

    def _build_rules(self):
        def _limit(name, default_value):
            raw = os.getenv(name)
            try:
                return int(raw) if raw else default_value
            except (TypeError, ValueError):
                return default_value

        # Defaults are intentionally conservative but practical for normal usage.
        return [
            {
                'pattern': re.compile(r'^/login/?$'),
                'window': 60,
                'per_ip_limit': _limit('THROTTLE_LOGIN_PER_MIN', 30),
                'global_limit': _limit('THROTTLE_LOGIN_GLOBAL_PER_MIN', 300),
                'name': 'login',
            },
            {
                'pattern': re.compile(r'^/register/?$'),
                'window': 60,
                'per_ip_limit': _limit('THROTTLE_REGISTER_PER_MIN', 12),
                'global_limit': _limit('THROTTLE_REGISTER_GLOBAL_PER_MIN', 120),
                'name': 'register',
            },
            {
                'pattern': re.compile(r'^/creator/courses/.+/lessons/\d+/generate/?$'),
                'window': 60,
                'per_ip_limit': _limit('THROTTLE_AI_GENERATE_PER_MIN', 8),
                'global_limit': _limit('THROTTLE_AI_GENERATE_GLOBAL_PER_MIN', 60),
                'name': 'ai_generate',
            },
            {
                'pattern': re.compile(r'^/creator/upload-video-transcribe/?$'),
                'window': 300,
                'per_ip_limit': _limit('THROTTLE_TRANSCRIBE_PER_5MIN', 6),
                'global_limit': _limit('THROTTLE_TRANSCRIBE_GLOBAL_PER_5MIN', 40),
                'name': 'video_transcribe',
            },
        ]

    def _client_ip(self, request):
        forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
        if forwarded:
            return forwarded
        return request.META.get('REMOTE_ADDR', 'unknown')

    def _increment_counter(self, key, ttl_seconds):
        try:
            if cache.add(key, 1, timeout=ttl_seconds):
                return 1
            return cache.incr(key)
        except ValueError:
            # Cache entry vanished between calls; start fresh.
            try:
                cache.set(key, 1, timeout=ttl_seconds)
                return 1
            except Exception:
                return None
        except Exception:
            # Fail open if cache backend is unavailable/misconfigured.
            return None

    def __call__(self, request):
        if not self.enabled or request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return self.get_response(request)

        path = request.path.rstrip('/') or '/'
        client_ip = self._client_ip(request)

        for rule in self.rules:
            if not rule['pattern'].match(path):
                continue

            window = rule['window']
            current_slot = int(time.time() // window)
            ttl = window + 2

            per_ip_key = f"throttle:{rule['name']}:ip:{client_ip}:{current_slot}"
            ip_count = self._increment_counter(per_ip_key, ttl)
            if ip_count is None:
                return self.get_response(request)
            if ip_count > rule['per_ip_limit']:
                return JsonResponse(
                    {
                        'error': 'Too many requests. Please retry shortly.',
                        'throttle': rule['name'],
                    },
                    status=429
                )

            global_key = f"throttle:{rule['name']}:global:{current_slot}"
            global_count = self._increment_counter(global_key, ttl)
            if global_count is None:
                return self.get_response(request)
            if global_count > rule['global_limit']:
                return JsonResponse(
                    {
                        'error': 'Service is temporarily busy. Please retry shortly.',
                        'throttle': rule['name'],
                    },
                    status=429
                )

            break

        return self.get_response(request)


class TenantMiddleware:
    """
    Resolve tenant from host for domain/subdomain-based multi-tenant behavior.
    Platform hosts intentionally resolve to no tenant.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        tenant = None
        platform_hosts = {
            h.strip().lower()
            for h in os.getenv('PLATFORM_HOSTS', 'localhost,127.0.0.1').split(',')
            if h.strip()
        }

        if host in platform_hosts:
            # Dev override: allow local tenant preview with ?tenant=<slug>
            tenant_slug = (request.GET.get('tenant') or '').strip().lower()
            if tenant_slug:
                tenant = Tenant.objects.filter(slug=tenant_slug, is_active=True, is_archived=False).first()
        else:
            tenant_domain = TenantDomain.objects.filter(
                domain=host,
                is_verified=True,
                tenant__is_active=True,
                tenant__is_archived=False,
            ).select_related('tenant').first()
            if tenant_domain:
                tenant = tenant_domain.tenant

            if tenant is None:
                tenant = Tenant.objects.filter(custom_domain=host, is_active=True, is_archived=False).first()
            if tenant is None and '.' in host:
                maybe_slug = host.split('.')[0]
                tenant = Tenant.objects.filter(slug=maybe_slug, is_active=True, is_archived=False).first()

        request.tenant = tenant
        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    """
    Redirect authenticated users to password-change flow when required.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        path = (request.path or '').rstrip('/') or '/'
        exempt_paths = {
            (reverse('force_password_change').rstrip('/') or '/'),
            (reverse('logout').rstrip('/') or '/'),
            (reverse('login').rstrip('/') or '/'),
            (reverse('admin:logout').rstrip('/') or '/'),
        }
        if (
            path in exempt_paths
            or path.startswith('/static/')
            or path.startswith('/media/')
            or path.startswith('/admin/')
        ):
            return self.get_response(request)

        if TenantMembership.objects.filter(
            user=user,
            is_active=True,
            must_change_password=True,
        ).exists():
            return redirect('force_password_change')

        return self.get_response(request)

