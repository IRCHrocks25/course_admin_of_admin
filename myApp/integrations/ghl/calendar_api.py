"""Thin read client for the GHL Calendars API (v2 / LeadConnector).

Only the reads needed for event sync. Auth + single-use token rotation live in
``oauth.py``; callers pass a current access token. Base URL, version header, and
endpoints are the verified v2 contract (services.leadconnectorhq.com).
"""
from __future__ import annotations

import requests

from . import config

_HTTP_TIMEOUT = 20


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Version": config.API_VERSION,
        "Accept": "application/json",
    }


def get_calendar_events(access_token, location_id, calendar_id, start_ms, end_ms):
    """GET /calendars/events for one calendar over [start_ms, end_ms] (epoch ms).

    Returns the list of event dicts (GHL wraps them in ``{"events": [...]}``).
    """
    resp = requests.get(
        f"{config.API_BASE_URL}/calendars/events",
        params={
            "locationId": location_id,
            "calendarId": calendar_id,
            "startTime": start_ms,
            "endTime": end_ms,
        },
        headers=_headers(access_token),
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data.get("events", [])
    return data or []
