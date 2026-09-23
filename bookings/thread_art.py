"""'Your thread': one drawing per member and program.

The line runs through a node per session. Its shape comes from the member:
the sway is seeded by who they are and which group they were in, and each
session they wrote a reflection for pulls the line a little further out.
Sessions they ticked off are blue. Same data, same drawing, every time.
"""

import hashlib
import math
import textwrap
from dataclasses import dataclass

from django.utils import timezone
from django.utils.html import escape

MOSS, OAT, BLUE, SAGE, INK, INK_SOFT = "#2F4538", "#F5F0E8", "#7D9BB8", "#DCE3D5", "#25302A", "#4E5A52"
SERIF = "Newsreader, Georgia, 'Times New Roman', serif"
SANS = "'DM Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"

WIDTH = 1000
TOP = 300
STEP = 190
SIDE_MARGIN = 150


@dataclass
class Node:
    number: int
    title: str
    date: str
    done: bool
    quote: str
    x: float = 0.0
    y: float = 0.0


def _seed(*parts):
    digest = hashlib.sha256("·".join(str(p) for p in parts).encode()).digest()
    return [b / 255 for b in digest]


def layout(nodes, seed_parts):
    """Place nodes down the page with a gentle, personal sway."""
    rnd = _seed(*seed_parts)
    phase = rnd[0] * math.tau
    for i, node in enumerate(nodes):
        weight = min(len(node.quote) / 240, 1.0)  # more written, wider swing
        amplitude = 90 + 110 * weight + 40 * rnd[(i + 1) % len(rnd)]
        node.x = WIDTH / 2 + amplitude * math.sin(phase + i * (1.05 + 0.4 * rnd[1]))
        node.x = min(max(node.x, SIDE_MARGIN + 60), WIDTH - SIDE_MARGIN - 60)
        node.y = TOP + i * STEP
    return nodes


def _segments(points):
    """Catmull-Rom through the points, as one cubic Bézier per gap."""
    segs = []
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        segs.append(f"C {c1[0]:.1f} {c1[1]:.1f}, {c2[0]:.1f} {c2[1]:.1f}, {p2[0]:.1f} {p2[1]:.1f}")
    return segs


def _path(points, upto=None):
    """The curve through all points, or only its first `upto` segments (same shape)."""
    if not points:
        return ""
    segs = _segments(points)
    return " ".join([f"M {points[0][0]:.1f} {points[0][1]:.1f}"] + segs[:upto])


def _text_lines(x, y, lines, anchor, size, family, fill, style="normal", gap=1.35):
    out = []
    for i, line in enumerate(lines):
        out.append(
            f'<text x="{x:.1f}" y="{y + i * size * gap:.1f}" text-anchor="{anchor}" font-family="{family}" '
            f'font-size="{size}" font-style="{style}" fill="{fill}">{escape(line)}</text>'
        )
    return "".join(out)


def render_svg(nodes, *, program_title, subtitle, name, footer):
    height = TOP + (len(nodes) - 1) * STEP + 260
    # Short tails above the first node and below the last, clear of the text.
    start = (nodes[0].x, TOP - 60) if nodes else (WIDTH / 2, TOP)
    end = (nodes[-1].x, nodes[-1].y + 80) if nodes else (WIDTH / 2, TOP)
    points = [start] + [(n.x, n.y) for n in nodes] + [end]
    full = _path(points)
    last_done = max((i for i, n in enumerate(nodes) if n.done), default=-1)
    # Blue runs along the very same curve, from the top to the last session ticked off.
    walked = _path(points, upto=last_done + 1) if last_done >= 0 else ""

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        f'role="img" aria-labelledby="thread-title thread-desc">',
        f'<title id="thread-title">{escape(name)}\'s thread · {escape(program_title)}</title>',
        f'<desc id="thread-desc">{sum(n.done for n in nodes)} of {len(nodes)} sessions done.</desc>',
        f'<rect width="{WIDTH}" height="{height}" fill="{OAT}"/>',
        _text_lines(WIDTH / 2, 92, ["YOUR THREAD"], "middle", 14, SANS, INK_SOFT),
        _text_lines(WIDTH / 2, 150, [program_title], "middle", 44, SERIF, MOSS),
        _text_lines(WIDTH / 2, 190, [subtitle], "middle", 17, SANS, INK_SOFT),
        f'<path class="thread-all" d="{full}" fill="none" stroke="{MOSS}" stroke-opacity="0.35" '
        f'stroke-width="1.6" stroke-linecap="round"/>',
    ]
    if walked:
        parts.append(
            f'<path class="thread-walked" d="{walked}" fill="none" stroke="{BLUE}" stroke-width="3.2" '
            f'stroke-linecap="round"/>'
        )
    for i, n in enumerate(nodes):
        # The words sit beside and below the node: put them on the side the
        # line is not leaving towards (points has a tail at each end).
        right = points[i + 2][0] <= n.x
        if n.x > WIDTH - SIDE_MARGIN - 200:
            right = False
        elif n.x < SIDE_MARGIN + 200:
            right = True
        tx = n.x + 34 if right else n.x - 34
        anchor = "start" if right else "end"
        parts.append(f'<g class="thread-node" style="--i:{i}">')
        if n.done:
            parts.append(f'<circle cx="{n.x:.1f}" cy="{n.y:.1f}" r="13" fill="{BLUE}"/>')
        else:
            parts.append(
                f'<circle cx="{n.x:.1f}" cy="{n.y:.1f}" r="12" fill="{OAT}" stroke="{MOSS}" stroke-width="1.6"/>'
            )
        parts.append(_text_lines(tx, n.y - 26, [f"{n.number} · {n.date}".upper()], anchor, 12, SANS, INK_SOFT))
        parts.append(_text_lines(tx, n.y + 4, textwrap.wrap(n.title, 30)[:2], anchor, 22, SERIF, MOSS, gap=1.2))
        if n.quote:
            quote = textwrap.wrap(f"“{n.quote}”", 44, max_lines=3, placeholder="…”")
            lines_in_title = len(textwrap.wrap(n.title, 30)[:2])
            parts.append(_text_lines(tx, n.y + 12 + lines_in_title * 26, quote, anchor, 15, SERIF, INK, "italic"))
        parts.append("</g>")
    parts.append(_text_lines(WIDTH / 2, height - 70, [footer], "middle", 15, SERIF, INK_SOFT, "italic"))
    parts.append(_text_lines(WIDTH / 2, height - 40, ["Quietwork"], "middle", 18, SERIF, MOSS))
    parts.append("</svg>")
    return "".join(parts)


def build_thread(user, cohort, sessions, done_ids, reflections):
    """Everything the page and the download need."""
    nodes = [
        Node(
            number=s.number,
            title=s.title,
            date=timezone.localtime(s.starts_at).strftime("%-d %b"),
            done=s.pk in done_ids,
            quote=" ".join((reflections.get(s.pk) or "").split()),
        )
        for s in sessions
    ]
    layout(nodes, (user.pk, cohort.pk))
    first, last = sessions[0].starts_at, sessions[-1].starts_at
    done = sum(n.done for n in nodes)
    subtitle = f"{cohort.name} · {timezone.localtime(first):%-d %B} – {timezone.localtime(last):%-d %B %Y}"
    footer = (
        f"{done} of {len(nodes)} evenings of small, steady work."
        if done else "The thread starts with the first evening."
    )
    svg = render_svg(
        nodes, program_title=cohort.program.title, subtitle=subtitle, name=user.display_name, footer=footer
    )
    return {"nodes": nodes, "svg": svg, "done": done, "total": len(nodes),
            "reflections_count": sum(1 for n in nodes if n.quote)}
