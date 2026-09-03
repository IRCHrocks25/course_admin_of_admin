"""Helpers for inline image/video blocks inside lesson notes (Editor.js content)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def normalize_inline_video_embed(url: str) -> str:
    """Return a safe http(s) iframe embed URL, or '' if the input is not usable."""
    raw = (url or '').strip()
    if not raw:
        return ''
    # Reject non-http(s) schemes (javascript:, data:, etc.)
    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme.lower() not in ('http', 'https'):
        return ''
    if not parsed.scheme:
        raw = 'https://' + raw.lstrip('/')
        parsed = urlparse(raw)
    if parsed.scheme.lower() not in ('http', 'https'):
        return ''
    if not parsed.netloc:
        return ''

    drive = re.search(
        r'(?:drive\.google\.com/(?:file/d/|open\?id=)|docs\.google\.com/file/d/)([a-zA-Z0-9_-]+)',
        raw,
        flags=re.IGNORECASE,
    )
    if drive:
        return f'https://drive.google.com/file/d/{drive.group(1)}/preview'

    vimeo = re.search(
        r'(?:vimeo\.com/(?:video/|channels/[^/]+/|groups/[^/]+/videos/|album/\d+/video/|ondemand/[^/]+/|manage/videos/)?|player\.vimeo\.com/video/)(\d+)',
        raw,
        flags=re.IGNORECASE,
    )
    if vimeo:
        return f'https://player.vimeo.com/video/{vimeo.group(1)}'

    yt = re.search(
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})',
        raw,
        flags=re.IGNORECASE,
    )
    if yt:
        return f'https://www.youtube.com/embed/{yt.group(1)}'

    return raw


def enrich_video_block(block: dict[str, Any]) -> dict[str, Any]:
    """Attach a sanitized embed_url onto a video block's data for templates."""
    if not isinstance(block, dict) or block.get('type') != 'video':
        return block
    data = block.get('data') if isinstance(block.get('data'), dict) else {}
    url = (data.get('url') or data.get('embed_url') or '').strip()
    embed = normalize_inline_video_embed(url)
    out = dict(block)
    out_data = dict(data)
    out_data['url'] = url
    out_data['embed_url'] = embed
    out['data'] = out_data
    return out
