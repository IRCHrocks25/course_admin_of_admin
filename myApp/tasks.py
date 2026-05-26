from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django_tasks import task


@task()
def send_notification_emails(notification_id):
    from .models import TenantNotification, TenantMembership

    notification = TenantNotification.objects.get(id=notification_id)
    if not notification.send_email:
        return

    deliveries = (
        notification.deliveries
        .filter(email_sent_at__isnull=True)
        .select_related('tenant')
    )

    for delivery in deliveries:
        admins = (
            TenantMembership.objects
            .filter(tenant=delivery.tenant, role='tenant_admin', is_active=True)
            .select_related('user')
        )
        try:
            for membership in admins:
                if not membership.user.email:
                    continue
                html = render_to_string('emails/notification.html', {
                    'notification': notification,
                    'tenant': delivery.tenant,
                    'user': membership.user,
                    'cta_url': _build_cta_url(notification, delivery.tenant),
                })
                send_mail(
                    subject=notification.title,
                    message='',
                    html_message=html,
                    from_email=None,
                    recipient_list=[membership.user.email],
                )
            delivery.email_sent_at = timezone.now()
        except Exception as e:
            delivery.email_error = str(e)[:1000]
        delivery.save(update_fields=['email_sent_at', 'email_error'])


def _build_cta_url(notification, tenant):
    if notification.cta_type == 'url':
        return notification.cta_custom_url
    if notification.cta_type == 'upgrade' and notification.cta_tier:
        return f"/upgrade/{notification.cta_tier.code}/"
    if notification.cta_type == 'setup_fee' and notification.cta_tier:
        return f"/setup-fee/{notification.cta_tier.code}/"
    return ''
