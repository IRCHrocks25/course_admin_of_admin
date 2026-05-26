from django import template

register = template.Library()


@register.filter
def cents_to_dollars(value):
    try:
        return f"${int(value) / 100:,.0f}"
    except (TypeError, ValueError):
        return value
