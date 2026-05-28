from django import template
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def dictget(d, key):
    """Lookup key in a dict. Returns None if missing or not a dict."""
    if isinstance(d, dict):
        return d.get(key)
    return None


@register.filter
def in_set(s, value):
    """Check if value is in a set/list."""
    if s is None:
        return False
    return value in s


@register.filter
def initial(name):
    """Return first character uppercase for avatar circle."""
    if name:
        return name[0].upper()
    return '?'


@register.filter
def short_timesince(dt):
    """Return a short time-since string like '2h' or '3d'."""
    ts = timesince(dt)
    first_part = ts.split(',')[0].strip()
    return first_part
