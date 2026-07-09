from django import template

register = template.Library()


@register.filter
def dict_get(mapping, key):
    if not mapping:
        return ''
    try:
        return mapping.get(key, '')
    except AttributeError:
        return ''
