#!/usr/bin/env python3
"""
Turn Natural Earth country outlines into the compact map our backdrop draws.

    python3 tools/make-map.py path/to/ne_110m_admin_0_countries.geojson

Source: Natural Earth (naturalearthdata.com), 1:110m Admin 0 Countries. Natural
Earth places its data in the public domain, so the generated file can ship.
Only the generated file is committed - the multi-megabyte source is not.

What this does:

* clips every country to the window we draw (Europe and its edges),
* simplifies the rings, because at this scale a coastline traced to the metre
  is thousands of points nobody can see, and
* keeps each country's ISO 3166-1 alpha-2 code, which is what lets the app
  highlight the country you are connected to - Proton's server records carry
  the same codes.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "src" / "unofficial_protonvpn" / "widgets" / "map_data.py"

#: The whole world. The map pans to whichever country you are connected to, so
#: it cannot be clipped to Europe - connecting to Japan has to show Japan.
BOUNDS = (-180.0, 180.0, -58.0, 84.0)   # west, east, south, north

#: Douglas-Peucker tolerance in degrees. Larger means blockier and smaller.
TOLERANCE = 0.18

#: Rings smaller than this (in square degrees) are dropped. Kept small so that
#: countries like Singapore, Malta and Luxembourg survive: Proton has servers
#: in them, and a country you can connect to must be a country we can draw.
MINIMUM_AREA = 0.01


def clip_to_bounds(ring, bounds):
    """Sutherland-Hodgman clip of a polygon ring against the bounding box."""
    west, east, south, north = bounds

    def clip_edge(points, inside, intersect):
        if not points:
            return []
        output = []
        previous = points[-1]
        for current in points:
            if inside(current):
                if not inside(previous):
                    output.append(intersect(previous, current))
                output.append(current)
            elif inside(previous):
                output.append(intersect(previous, current))
            previous = current
        return output

    def lerp(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    points = list(ring)
    points = clip_edge(points, lambda p: p[0] >= west,
                       lambda a, b: lerp(a, b, (west - a[0]) / (b[0] - a[0])))
    points = clip_edge(points, lambda p: p[0] <= east,
                       lambda a, b: lerp(a, b, (east - a[0]) / (b[0] - a[0])))
    points = clip_edge(points, lambda p: p[1] >= south,
                       lambda a, b: lerp(a, b, (south - a[1]) / (b[1] - a[1])))
    points = clip_edge(points, lambda p: p[1] <= north,
                       lambda a, b: lerp(a, b, (north - a[1]) / (b[1] - a[1])))
    return points


def simplify(points, tolerance):
    """Douglas-Peucker: drop points that do not change the shape."""
    if len(points) < 3:
        return points

    def distance(point, start, end):
        if start == end:
            return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        return abs(dy * point[0] - dx * point[1] + end[0] * start[1]
                   - end[1] * start[0]) / length

    furthest, largest = 0, 0.0
    for index in range(1, len(points) - 1):
        gap = distance(points[index], points[0], points[-1])
        if gap > largest:
            furthest, largest = index, gap

    if largest <= tolerance:
        return [points[0], points[-1]]

    left = simplify(points[:furthest + 1], tolerance)
    right = simplify(points[furthest:], tolerance)
    return left[:-1] + right


def area(ring):
    """Absolute shoelace area, in square degrees."""
    total = 0.0
    for index in range(len(ring)):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def rings_of(geometry):
    """Yield the outer ring of every polygon in a geometry."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield [tuple(p) for p in coordinates[0]]
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield [tuple(p) for p in polygon[0]]


def country_code(properties) -> str:
    """ISO alpha-2, preferring the field Natural Earth keeps accurate."""
    for key in ("ISO_A2_EH", "ISO_A2", "WB_A2"):
        value = properties.get(key)
        if value and value not in ("-99", "-1"):
            return str(value).upper()
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    source = Path(sys.argv[1])
    data = json.loads(source.read_text())

    countries = {}
    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        code = country_code(properties)
        if not code:
            continue

        kept = []
        for ring in rings_of(feature.get("geometry") or {}):
            clipped = clip_to_bounds(ring, BOUNDS)
            if len(clipped) < 4 or area(clipped) < MINIMUM_AREA:
                continue
            reduced = simplify(clipped, TOLERANCE)
            if len(reduced) >= 4:
                kept.append([(round(x, 3), round(y, 3)) for x, y in reduced])

        if kept:
            countries.setdefault(code, []).extend(kept)

    lines = [
        '"""',
        "Country outlines for the map backdrop. Generated - do not edit by hand.",
        "",
        "    python3 tools/make-map.py ne_110m_admin_0_countries.geojson",
        "",
        "Source: Natural Earth 1:110m Admin 0 Countries (naturalearthdata.com),",
        "released into the public domain. Clipped to the window we draw and",
        "simplified: this is a stylised backdrop, not a survey.",
        "",
        "Keys are ISO 3166-1 alpha-2 codes, matching the country codes on",
        "Proton's server records, so the connected country can be highlighted.",
        '"""',
        "",
        f"BOUNDS = {BOUNDS!r}",
        "",
        "COUNTRIES = {",
    ]
    for code in sorted(countries):
        lines.append(f"    {code!r}: [")
        for ring in countries[code]:
            packed = ", ".join(f"({x}, {y})" for x, y in ring)
            lines.append(f"        [{packed}],")
        lines.append("    ],")
    lines.append("}")
    lines.append("")

    OUTPUT.write_text("\n".join(lines))

    points = sum(len(r) for rings in countries.values() for r in rings)
    size = OUTPUT.stat().st_size
    print(f"{len(countries)} countries, {points} points -> "
          f"{OUTPUT.relative_to(REPO)} ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
