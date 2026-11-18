"""Deterministic, locally contrasting colors for frozen Scope station groups.

No QGIS dependency: the selection can be regression-tested in ordinary Python.
Only geographic neighbours need maximally different colors; distant groups may
retain the same original color. No source/current data are modified.
"""
from __future__ import annotations

from hashlib import sha256
from math import sqrt

# Diverse categorical candidates with dark/light and hue differences.
CANDIDATES = (
    "#0072b2", "#e69f00", "#009e73", "#cc79a7", "#d55e00",
    "#56b4e9", "#6b52ae", "#8c564b", "#e7298a", "#66a61e",
    "#a6761d", "#fb9a99", "#b15928", "#1f78b4", "#ff7f00",
    "#33a02c", "#6a3d9a", "#b2df8a", "#4e79a7", "#f28e2b",
    "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1",
    "#ff9da7", "#9c755f", "#00a6a6", "#db567b", "#5f4b8b",
)


def _hex(color):
    color = str(color or "").strip().lower()
    if len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdef" for c in color[1:]):
        return color
    return ""


def _fallback(name):
    # Stable and fairly saturated; never use Python's randomized hash().
    return CANDIDATES[int(sha256(name.encode("utf-8")).hexdigest()[:8], 16) % len(CANDIDATES)]


def _lab(color):
    """sRGB D65 to CIE L*a*b*; differences are more useful than RGB distance."""
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    xyz = ((r * .4124564 + g * .3575761 + b * .1804375) / .95047,
           (r * .2126729 + g * .7151522 + b * .0721750),
           (r * .0193339 + g * .1191920 + b * .9503041) / 1.08883)
    def f(v):
        return v ** (1 / 3) if v > .008856 else 7.787 * v + 16 / 116
    x, y, z = [f(v) for v in xyz]
    return (116 * y - 16, 500 * (x - y), 200 * (y - z))


def perceptual_distance(a, b):
    a, b = _hex(a), _hex(b)
    if not a or not b:
        return 0.0
    p, q = _lab(a), _lab(b)
    return sqrt(sum((x - y) ** 2 for x, y in zip(p, q)))


def _representatives(points, limit=96):
    # Preserve both horizontal and vertical spatial extremes of long clusters.
    coords = sorted(set((float(x), float(y)) for x, y in points))
    if len(coords) <= limit:
        return coords
    by_y = sorted(coords, key=lambda item: (item[1], item[0]))
    count = limit // 2
    indices = [round(i * (len(coords) - 1) / (count - 1)) for i in range(count)]
    return sorted(set([coords[i] for i in indices] + [by_y[i] for i in indices]))


def _nearest_distance(left, right):
    if not left or not right:
        return float("inf")
    best = float("inf")
    for ax, ay in left:
        for bx, by in right:
            d = (ax - bx) ** 2 + (ay - by) ** 2
            if d < best:
                best = d
                if best == 0:
                    return 0.0
    return sqrt(best)


def neighbour_graph(group_points, nearest_count=4):
    """Connect each group to its closest geographic groups by point geometry.

    The relation is symmetric. Long corridors use sampled connection points,
    not station-name hashes or just station centroids.
    """
    names = sorted(group_points)
    sample = {name: _representatives(group_points[name]) for name in names}
    graph = {name: set() for name in names}
    for name in names:
        distances = sorted(
            ((_nearest_distance(sample[name], sample[other]), other)
             for other in names if other != name and sample[other]),
            key=lambda pair: (pair[0], pair[1]))
        if not sample[name] or not distances:
            continue
        nearest = distances[0][0]
        threshold = max(30.0, nearest * 1.8)
        selected = set(other for _, other in distances[:nearest_count])
        selected.update(other for distance, other in distances[:8] if distance <= threshold)
        for other in selected:
            graph[name].add(other)
            graph[other].add(name)
    return graph


def choose_scope_colors(group_points, preferred_colors=None):
    """Pick a stable, high-contrast color for adjacent Scope groups.

    Existing colors are retained when sufficiently distinct from already
    assigned neighbouring groups. Otherwise choose the farthest alternative.
    Groups and points may be provided in any order and result stays identical.
    """
    preferred_colors = preferred_colors or {}
    names = sorted(set(group_points) | set(preferred_colors))
    graph = neighbour_graph({name: list(group_points.get(name, ())) for name in names})
    initial = {name: _hex(preferred_colors.get(name)) or _fallback(name) for name in names}
    palette = {}
    for name in sorted(names, key=lambda item: (-len(graph[item]), item)):
        existing = [palette[other] for other in graph[name] if other in palette]
        preferred = initial[name]
        if not existing or min(perceptual_distance(preferred, x) for x in existing) >= 52:
            choice = preferred
        else:
            scores = []
            for index, candidate in enumerate(dict.fromkeys((preferred,) + CANDIDATES)):
                distances = [perceptual_distance(candidate, x) for x in existing]
                # Maximum separation is the primary goal; maintain deterministic ties.
                scores.append((min(distances), sum(distances) / len(distances),
                               -perceptual_distance(preferred, candidate),
                               -index, candidate))
            choice = max(scores)[-1]
        palette[name] = choice
    return {name: palette[name] for name in names}
