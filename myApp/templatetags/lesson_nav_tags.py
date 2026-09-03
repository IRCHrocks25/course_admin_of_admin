from django import template

from myApp.utils.lesson_hierarchy import clean_lesson_nav_title, lesson_nest_depth

register = template.Library()


@register.filter
def nest_depth(title):
    return lesson_nest_depth(title or '')


@register.filter
def clean_nav_title(title):
    return clean_lesson_nav_title(title or '')
