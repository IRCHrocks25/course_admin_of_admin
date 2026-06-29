"""Shared GHL calendar-event backfill service.

Used by both the scheduled management command and the CourseForge dashboard
"Run event sync now" control so selection, refresh, and upsert behavior stay
identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from . import calendar_api, events_sync, oauth


@dataclass
class GhlEventSyncResult:
    upserted: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def ensure_fresh_connection(connection):
    """Return a connection with a valid access token, or None when refresh fails."""
    if oauth.needs_refresh(connection):
        refreshed = oauth.refresh_connection(connection.id)
        if not (refreshed and refreshed.is_healthy):
            return None
        return refreshed
    return connection


def sync_connection_events(connection, *, days_back=180, days_ahead=180, dry_run=False):
    """Fetch selected GHL event calendars for one connection and upsert Events."""
    result = GhlEventSyncResult()
    cal_ids = connection.event_calendar_id_list
    if not cal_ids:
        result.skipped += 1
        return result

    connection = ensure_fresh_connection(connection)
    if connection is None:
        result.failed += 1
        result.errors.append("token refresh failed")
        return result

    now = timezone.now()
    start_ms = int((now - timedelta(days=days_back)).timestamp() * 1000)
    end_ms = int((now + timedelta(days=days_ahead)).timestamp() * 1000)
    token = connection.get_access_token()

    for cal_id in cal_ids:
        try:
            events = calendar_api.get_calendar_events(
                token, connection.ghl_location_id, cal_id, start_ms, end_ms)
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{connection.tenant.slug}/{cal_id}: {exc}")
            continue
        for event in events:
            if not dry_run:
                events_sync.apply_ghl_event(connection.tenant, cal_id, event)
            result.upserted += 1
    return result


def sync_all_connections(connections, *, days_back=180, days_ahead=180, dry_run=False):
    total = GhlEventSyncResult()
    for connection in connections:
        result = sync_connection_events(
            connection,
            days_back=days_back,
            days_ahead=days_ahead,
            dry_run=dry_run,
        )
        total.upserted += result.upserted
        total.failed += result.failed
        total.skipped += result.skipped
        total.errors.extend(result.errors)
    return total
