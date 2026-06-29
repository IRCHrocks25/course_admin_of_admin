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


def get_calendars(access_token, location_id):
    """GET /calendars/ for one GHL location and return normalized rows."""
    resp = requests.get(
        f"{config.API_BASE_URL}/calendars/",
        params={"locationId": location_id},
        headers=_headers(access_token),
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("calendars", []) if isinstance(data, dict) else (data or [])
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cal_id = str(row.get("id") or "").strip()
        if not cal_id:
            continue
        normalized.append({
            "id": cal_id,
            "name": str(row.get("name") or row.get("title") or cal_id).strip(),
            "calendarType": str(row.get("calendarType") or row.get("type") or "").strip(),
            "description": str(row.get("description") or "").strip(),
        })
    return normalized
