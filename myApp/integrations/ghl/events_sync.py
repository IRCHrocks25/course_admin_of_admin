"""Map a GHL calendar-event/appointment payload onto a CourseForge Event.

``apply_ghl_event`` is the single writer shared by the poll command and the
webhook handler, so there is one mapping path to maintain. The join link comes
from the GHL ``address`` field (verified against the AppointmentCreate webhook
schema); start/end are ISO-8601 with offset.
"""
from __future__ import annotations

from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from ...models import Event

DEFAULT_DURATION_MINUTES = 60


def _unique_slug(title: str, ghl_event_id: str) -> str:
    base = slugify(title) or "event"
    # The GHL event id is unique per location, so it guarantees a per-tenant
    # unique slug without a collision loop.
    suffix = slugify(ghl_event_id)[-8:] or "x"
    return f"{base}-{suffix}"[:200]


def apply_ghl_event(tenant, calendar_id: str, payload: dict):
    """Upsert one GHL event onto a tenant's Event, keyed on the GHL event id.

    Returns the Event, or None if the payload has no usable id.
    """
    ghl_event_id = str(payload.get("id") or "").strip()
    if not ghl_event_id:
        return None

    start = parse_datetime(payload.get("startTime") or "")
    end = parse_datetime(payload.get("endTime") or "")
    duration = DEFAULT_DURATION_MINUTES
    if start and end:
        duration = max(1, int((end - start).total_seconds() // 60))

    ev = (
        Event.objects
        .filter(tenant=tenant, source="ghl", ghl_event_id=ghl_event_id)
        .first()
    )
    if ev is None:
        ev = Event(
            tenant=tenant,
            source="ghl",
            ghl_event_id=ghl_event_id,
            slug=_unique_slug(payload.get("title") or "", ghl_event_id),
        )

    ev.ghl_calendar_id = calendar_id or payload.get("calendarId") or ""
    ev.title = (payload.get("title") or "Untitled event").strip()
    ev.join_link = (payload.get("address") or "").strip()
    if start:
        ev.event_date = start.date()
        ev.start_time = start.time().replace(microsecond=0)
    ev.duration_minutes = duration
    ev.timezone = payload.get("timezone") or ev.timezone or "UTC"
    ev.status = "published"
    ev.save()
    return ev
