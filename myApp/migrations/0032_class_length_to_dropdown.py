"""Best-effort migration of free-text Course.creation_blueprint.class_length to fixed keys.

Buckets: 5_min / 15_min / 30_min / 60_min / 90_min. Default for unparseable: 30_min.
"""
import re
from django.db import migrations


CLASS_LENGTH_KEYS = ('5_min', '15_min', '30_min', '60_min', '90_min')
DEFAULT_KEY = '30_min'
_BUCKETS_MIN = (5, 15, 30, 60, 90)


def _parse_class_length(text):
    if not isinstance(text, str):
        return DEFAULT_KEY
    s = text.strip().lower()
    if not s:
        return DEFAULT_KEY
    if s in CLASS_LENGTH_KEYS:
        return s
    m = re.search(r'(\d+(?:\.\d+)?)', s)
    if not m:
        return DEFAULT_KEY
    try:
        n = float(m.group(1))
    except ValueError:
        return DEFAULT_KEY
    # Convert hours to minutes if "hour" / "hr" appears in the text.
    if 'hour' in s or re.search(r'\bhrs?\b', s):
        n *= 60
    nearest = min(_BUCKETS_MIN, key=lambda b: abs(b - n))
    return f'{nearest}_min'


def forwards(apps, schema_editor):
    Course = apps.get_model('myApp', 'Course')
    for course in Course.objects.all():
        bp = course.creation_blueprint
        if not isinstance(bp, dict):
            continue
        existing = bp.get('class_length')
        if existing in CLASS_LENGTH_KEYS:
            continue
        bp['class_length'] = _parse_class_length(existing)
        course.creation_blueprint = bp
        course.save(update_fields=['creation_blueprint'])


def backwards(apps, schema_editor):
    # The original free-text values are unrecoverable; leave the keys in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0031_lesson_generation_settings'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
