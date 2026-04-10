from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def abs_value(value):
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0

@register.filter
def div(a, b):
    """Safe division for percentages."""
    try:
        if b == 0:
            return 0
        return (a / b) * 100
    except (TypeError, ZeroDivisionError):
        return 0

@register.filter
def abs_val(value):
    """Absolute value filter."""
    return abs(value) if value else 0

@register.filter
def mul(a, b):
    """Multiplication filter."""
    try:
        return a * b
    except (TypeError, ValueError):
        return 0
