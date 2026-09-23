from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def euros(cents):
    """2400 -> "€24", 3550 -> "€35.50"."""
    if cents is None:
        return ""
    whole, rest = divmod(int(cents), 100)
    return f"€{whole}" if rest == 0 else f"€{whole}.{rest:02d}"


@register.filter
def seats_left(obj):
    """Seats left on an annotated Cohort/Workshop (seats_held) or a plain one."""
    held = getattr(obj, "seats_held", None)
    if held is None:
        return obj.seats_left()
    return max(obj.capacity - held, 0)


@register.filter
def seats_percent_taken(obj):
    if not obj.capacity:
        return 100
    return round(100 * (obj.capacity - seats_left(obj)) / obj.capacity)


@register.simple_tag
def local_time(dt):
    """Placeholder the browser fills with the visitor's own time, when it differs
    from Elena's (e.g. " · 20:00 for you"). Empty and hidden without JavaScript."""
    if not dt:
        return ""
    return format_html('<span class="local-time" data-local-time="{}" hidden></span>', dt.isoformat())
