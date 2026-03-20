from django.db import connections
from django.http import JsonResponse


def healthz(request):
    """Liveness check: process is up."""
    return JsonResponse({'status': 'ok'}, status=200)


def readyz(request):
    """
    Readiness check: app can serve traffic.
    Includes a lightweight database ping.
    """
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception as exc:
        return JsonResponse({'status': 'not_ready', 'error': str(exc)}, status=503)

    return JsonResponse({'status': 'ready'}, status=200)
