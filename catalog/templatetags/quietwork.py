from django import template

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
