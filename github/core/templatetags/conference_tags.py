from django import template

register = template.Library()

CONFERENCE_NAMES = {
    'East': 'Conferencia Este',
    'West': 'Conferencia Oeste',
}

@register.filter
def conference_name(value):
    return CONFERENCE_NAMES.get(value, value)
