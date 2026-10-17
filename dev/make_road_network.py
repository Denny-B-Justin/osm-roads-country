"""
dev/make_road_network.py
------------------------
Regenerates the two pieces of artwork in /assets:

  assets/road_network.svg   the stylised road map behind the home page
  assets/favicon.svg / .ico the browser-tab icon

The map is invented, not real data: a handful of towns, each with a warped street
grid, ring and radial roads, motorways joining the towns, rural tracks and a
river. It uses the app's colours (navy background, teal main roads, orange
motorways) and is drawn densest on the right so the text on the left stays
readable. Fixed seed, so every run produces the same file.

    python dev/make_road_network.py
"""

import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, os.pardir, "assets")

W, H = 1600, 1000
SEED = 20261017


# ── small helpers ─────────────────────────────────────────────────────────────

class Field:
    """Smooth 2-D noise in [-1, 1]: a sum of plane waves with random direction/phase."""

    def __init__(self, rng, waves=6, freq=(0.002, 0.009)):
        self.terms = []
        for _ in range(waves):
            a = rng.uniform(0, 2 * math.pi)
            k = rng.uniform(*freq)
            self.terms.append((k * math.cos(a), k * math.sin(a), rng.uniform(0, 2 * math.pi)))

    def __call__(self, x, y):
        return sum(math.sin(kx * x + ky * y + p) for kx, ky, p in self.terms) / len(self.terms)


def fmt(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def path_d(points):
    """Polyline -> compact SVG path data (absolute M, then relative l)."""
    if len(points) < 2:
        return ""
    x0, y0 = points[0]
    out = [f"M{fmt(x0)} {fmt(y0)}l"]
    px, py = round(x0, 1), round(y0, 1)
    rel = []
    for x, y in points[1:]:
        x, y = round(x, 1), round(y, 1)
        dx, dy = round(x - px, 1), round(y - py, 1)
        if dx == 0 and dy == 0:
            continue
        rel.append(f"{fmt(dx)} {fmt(dy)}")
        px, py = x, y
    if not rel:
        return ""
    return out[0] + " ".join(rel)


def smooth(points, samples=8):
    """Catmull-Rom spline through the points."""
    if len(points) < 3:
        return points
    pts = [points[0]] + points + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(samples):
            t = s / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t
                       + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                       + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3)
                for j in (0, 1)))
    out.append(points[-1])
    return out


def curve_between(a, b, rng, field, bend=0.16, steps=7, wiggle=14):
    """A gently bent road from a to b, as a smooth polyline."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    side = rng.choice((-1, 1)) * rng.uniform(0.4, 1.0) * bend * length
    pts = []
    for i in range(steps + 1):
        t = i / steps
        arc = math.sin(math.pi * t) * side
        x = ax + dx * t + nx * arc
        y = ay + dy * t + ny * arc
        if 0 < i < steps:
            w = field(x, y) * wiggle
            x += nx * w
            y += ny * w
        pts.append((x, y))
    return smooth(pts, samples=10)


# ── the map ───────────────────────────────────────────────────────────────────

# Towns with a street grid: x, y, radius, grid angle (degrees), street spacing
TOWNS = [
    (1190, 430, 175, 12, 11),
    (1470, 170, 105, -22, 10),
    (870, 735, 110, 31, 10),
    (1440, 800, 96, 6, 10),
    (790, 260, 72, -36, 10),
    (1585, 520, 80, 41, 10),
    (1075, 950, 66, 18, 9),
    (575, 520, 48, 14, 9),
    (340, 830, 36, -10, 9),
]

# Motorway corridors: chains of points (towns by index, or explicit x/y off the map).
PRIMARY_ROADS = [(4, 1), (2, 6), (3, 5), (7, 8), (0, 6), (4, 7), (1, 5), (2, 0), (7, (-80, 300)),
                 (8, (300, 1090)), (6, (1260, 1090))]

MOTORWAYS = [
    [(-80, 610), 7, 2, 3, (1720, 900)],
    [(980, -90), 4, 0, 5, (1720, 470)],
    [(1550, -90), 1, 0],
]


def poisson_points(rng, tries=9000):
    """Settlements: Poisson-disk sample whose spacing shrinks to the right (where the map shows)."""
    pts = []
    for _ in range(tries):
        x = rng.uniform(-60, W + 60)
        y = rng.uniform(-60, H + 60)
        f = max(0.0, min(1.0, x / W))
        spacing = 125 - 70 * f          # 125 px apart on the left, 55 px on the right
        if all(math.dist((x, y), p) >= min(spacing, 125 - 70 * max(0.0, min(1.0, p[0] / W)))
               for p in pts):
            pts.append((x, y))
    return pts


def neighbourhood_edges(pts, extra=0.08, rng=None):
    """Relative-neighbourhood graph (sparse, road-like) plus a few Gabriel edges for loops."""
    n = len(pts)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            dij = math.dist(pts[i], pts[j])
            if dij > 260:
                continue
            rng_ok = True
            gab_ok = True
            mx = ((pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2)
            for k in range(n):
                if k in (i, j):
                    continue
                dik, djk = math.dist(pts[i], pts[k]), math.dist(pts[j], pts[k])
                if max(dik, djk) < dij:
                    rng_ok = False
                if math.dist(mx, pts[k]) < dij / 2:
                    gab_ok = False
                if not rng_ok and not gab_ok:
                    break
            if rng_ok or (gab_ok and rng.random() < extra):
                edges.add((i, j))
    return sorted(edges)


def town_streets(town, rng, warp_x, warp_y, edge):
    """Warped street grid inside an irregular blob around the town centre."""
    cx, cy, r, ang, sp = town
    a = math.radians(ang)
    u = (math.cos(a), math.sin(a))
    v = (-math.sin(a), math.cos(a))
    lines = []
    for family in (0, 1):
        d, n = (u, v) if family == 0 else (v, u)
        t = -r
        while t <= r:
            seg = []
            w = -r
            while w <= r:
                x = cx + n[0] * t + d[0] * w
                y = cy + n[1] * t + d[1] * w
                x += warp_x(x, y) * r * 0.12
                y += warp_y(x, y) * r * 0.12
                theta = math.atan2(y - cy, x - cx)
                limit = r * (0.72 + 0.28 * edge(math.cos(theta) * 90 + cx, math.sin(theta) * 90 + cy))
                if math.hypot(x - cx, y - cy) < limit:
                    seg.append((x, y))
                else:
                    if len(seg) > 1:
                        lines.append(seg)
                    seg = []
                w += 5
            if len(seg) > 1:
                lines.append(seg)
            t += sp * rng.uniform(0.7, 1.4)
    kept = []
    for seg in lines:
        if rng.random() < 0.14:
            continue
        if len(seg) > 6 and rng.random() < 0.4:
            cut = rng.randint(2, len(seg) - 2)
            seg = seg[:cut] if rng.random() < 0.5 else seg[cut:]
        kept.append(seg)
    return kept


def ring(town, field):
    """Irregular ring road around the main town."""
    cx, cy, r, _ang, _sp = town
    pts = []
    for s in range(0, 10):
        theta = 2 * math.pi * s / 9
        rr = r * 0.74 * (1 + 0.32 * field(cx + 130 * math.cos(theta), cy + 130 * math.sin(theta)))
        pts.append((cx + rr * math.cos(theta), cy + rr * 0.9 * math.sin(theta)))
    pts[-1] = pts[0]
    return smooth(pts, samples=10)


def dead_ends(rng, field, origins, n):
    """Tracks: wandering dead-end roads leaving villages."""
    out = []
    for _ in range(n):
        x, y = rng.choice(origins)
        heading = rng.uniform(0, 2 * math.pi)
        pts = [(x, y)]
        for _ in range(rng.randint(6, 18)):
            heading += field(x * 1.9, y * 1.9) * 0.45 + rng.uniform(-0.15, 0.15)
            x += math.cos(heading) * 8
            y += math.sin(heading) * 8
            pts.append((x, y))
        out.append(pts)
    return out


def river(field):
    """A meandering river from the top edge to the bottom-right coast: (centre line, half widths)."""
    pts = [(1020, -60), (1005, 120), (1085, 250), (1030, 420), (1100, 560),
           (1230, 640), (1300, 750), (1400, 880), (1470, 1080)]
    pts = [(x + field(x, y) * 30, y) for x, y in pts]
    line = smooth(pts, samples=10)
    widths = [4 + 6 * (i / len(line)) for i in range(len(line))]
    return line, widths


def river_polygon(line, widths):
    left, right = [], []
    for i, (x, y) in enumerate(line):
        a = line[max(i - 1, 0)]
        b = line[min(i + 1, len(line) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        left.append((x + nx * widths[i], y + ny * widths[i]))
        right.append((x - nx * widths[i], y - ny * widths[i]))
    poly = left + right[::-1]
    return "M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in poly) + "Z"


def coast():
    """Sea in the bottom-right corner, plus two depth contours."""
    shore = smooth([(1300, 1010), (1360, 968), (1430, 952), (1490, 918), (1550, 908), (1610, 866)],
                   samples=8)
    sea = "M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in shore) + " L1610 1010Z"
    contours = [[(x + off * 0.6, y + off) for x, y in shore] for off in (20, 44)]
    return sea, contours


def build_svg():
    rng = random.Random(SEED)
    warp_x, warp_y = Field(rng, freq=(0.004, 0.012)), Field(rng, freq=(0.004, 0.012))
    edge = Field(rng, waves=4, freq=(0.01, 0.03))
    field = Field(rng)

    centres = [(t[0], t[1]) for t in TOWNS]
    villages = [p for p in poisson_points(rng)
                if all(math.dist(p, c) > t[2] * 0.9 for c, t in zip(centres, TOWNS))]
    nodes = centres + villages
    is_town = [True] * len(centres) + [False] * len(villages)

    minor, local, secondary, primary, motorway = [], [], [], [], []

    for town in TOWNS:
        minor += town_streets(town, rng, warp_x, warp_y, edge)
    # Small street clusters in some villages.
    for vx, vy in villages:
        if rng.random() < 0.2 + 0.5 * max(0.0, min(1.0, vx / W)):
            minor += town_streets((vx, vy, rng.uniform(14, 24), rng.uniform(0, 90), 8),
                                  rng, warp_x, warp_y, edge)

    for i, j in neighbourhood_edges(nodes, rng=rng):
        a, b = nodes[i], nodes[j]
        line = curve_between(a, b, rng, field, bend=0.07, steps=6, wiggle=9)
        if is_town[i] and is_town[j]:
            primary.append(line)
        elif is_town[i] or is_town[j]:
            secondary.append(line)
        else:
            local.append(line)

    primary.append(ring(TOWNS[0], field))
    for i, j in PRIMARY_ROADS:
        b = centres[j] if isinstance(j, int) else j
        primary.append(curve_between(centres[i], b, rng, field, bend=0.10, steps=8, wiggle=12))

    for chain in MOTORWAYS:
        pts = [centres[c] if isinstance(c, int) else c for c in chain]
        line = []
        for a, b in zip(pts, pts[1:]):
            seg = curve_between(a, b, rng, field, bend=0.08, steps=5, wiggle=6)
            line += seg if not line else seg[1:]
        motorway.append(line)

    tracks_d = dead_ends(rng, field, villages, 70)
    r_line, r_widths = river(field)
    sea, contours = coast()
    flows = [path_d(p) for p in motorway]

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'preserveAspectRatio="xMidYMid slice" aria-hidden="true">']
    parts.append("""<style>
.g{fill:none;stroke:#9FB8D6;stroke-opacity:.045;stroke-width:1}
.w{fill:#061A2E;fill-opacity:.9}
.wl{fill:none;stroke:#64CBD6;stroke-opacity:.18;stroke-width:.8}
.dp{fill:none;stroke:#64CBD6;stroke-opacity:.12;stroke-width:.8;stroke-dasharray:2 5}
.tr{fill:none;stroke:#8FB0D4;stroke-opacity:.22;stroke-width:.7;stroke-dasharray:3 3}
.mn{fill:none;stroke:#8FB0D4;stroke-opacity:.36;stroke-width:.75;stroke-linecap:round;stroke-linejoin:round}
.lc{fill:none;stroke:#9DB9DA;stroke-opacity:.40;stroke-width:.95;stroke-linecap:round}
.sc{fill:none;stroke:#64CBD6;stroke-opacity:.50;stroke-width:1.35;stroke-linecap:round}
.pr{fill:none;stroke:#64CBD6;stroke-opacity:.72;stroke-width:2;stroke-linecap:round}
.mc{fill:none;stroke:#08213A;stroke-width:7;stroke-linecap:round;stroke-linejoin:round}
.mw{fill:none;stroke:#F26B23;stroke-opacity:.82;stroke-width:2.8;stroke-linecap:round;stroke-linejoin:round}
.fl{fill:none;stroke:#FFE7D6;stroke-width:1.7;stroke-linecap:round;stroke-dasharray:1.5 46.5;animation:fl 8s linear infinite}
.fl.b{animation-duration:11s;animation-direction:reverse}
.nd{fill:#EAF4FB;fill-opacity:.85}
@keyframes fl{to{stroke-dashoffset:-96}}
@media (prefers-reduced-motion: reduce){.fl{animation:none;stroke-opacity:0}}
</style>""")
    grid = "".join(f"M{x} 0V{H}" for x in range(0, W + 1, 160))
    grid += "".join(f"M0 {y}H{W}" for y in range(0, H + 1, 160))
    parts.append(f'<path class="g" d="{grid}"/>')
    parts.append(f'<path class="w" d="{sea}"/>')
    parts.append(f'<path class="dp" d="{"".join(path_d(c) for c in contours)}"/>')
    parts.append(f'<path class="w" d="{river_polygon(r_line, r_widths)}"/>')
    parts.append(f'<path class="wl" d="{path_d(r_line)}"/>')
    parts.append(f'<path class="tr" d="{"".join(path_d(p) for p in tracks_d)}"/>')
    parts.append(f'<path class="mn" d="{"".join(path_d(p) for p in minor)}"/>')
    parts.append(f'<path class="lc" d="{"".join(path_d(p) for p in local)}"/>')
    parts.append(f'<path class="sc" d="{"".join(path_d(p) for p in secondary)}"/>')
    parts.append(f'<path class="pr" d="{"".join(path_d(p) for p in primary)}"/>')
    parts.append(f'<path class="mc" d="{"".join(flows)}"/>')
    parts.append(f'<path class="mw" d="{"".join(flows)}"/>')
    parts.append("".join(f'<path class="fl{" b" if k % 2 else ""}" d="{d}"/>' for k, d in enumerate(flows)))
    for cx, cy, r, _a, _s in TOWNS:
        parts.append(f'<circle class="nd" cx="{cx}" cy="{cy}" r="{fmt(3.2 if r >= 90 else 2.4)}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


# ── favicon ───────────────────────────────────────────────────────────────────

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#0B2B4B"/>
<path d="M-4 52C14 50 22 40 30 30S46 12 68 12" fill="none" stroke="#08213A" stroke-width="15" stroke-linecap="round"/>
<path d="M-4 52C14 50 22 40 30 30S46 12 68 12" fill="none" stroke="#F26B23" stroke-width="10" stroke-linecap="round"/>
<path d="M-4 52C14 50 22 40 30 30S46 12 68 12" fill="none" stroke="#FFF4EC" stroke-width="2" stroke-dasharray="5 5"/>
<path d="M8 4C16 22 30 40 60 58" fill="none" stroke="#64CBD6" stroke-width="5" stroke-linecap="round" stroke-opacity=".9"/>
</svg>
"""


def write_favicon_ico(path):
    """Raster copy of the favicon for browsers without SVG favicon support (needs Pillow)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed: favicon.ico not regenerated")
        return

    size = 256
    s = size / 64

    def bezier(p0, p1, p2, p3, n=60):
        out = []
        for i in range(n + 1):
            t = i / n
            mt = 1 - t
            out.append(tuple(
                (mt ** 3 * p0[k] + 3 * mt * mt * t * p1[k] + 3 * mt * t * t * p2[k] + t ** 3 * p3[k]) * s
                for k in (0, 1)))
        return out

    # Same shapes as FAVICON_SVG: C then S (S reflects the previous control point).
    road = bezier((-4, 52), (14, 50), (22, 40), (30, 30)) + bezier((30, 30), (38, 20), (46, 12), (68, 12))[1:]
    teal = bezier((8, 4), (16, 22), (30, 40), (60, 58))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(14 * s), fill=255)
    layer = Image.new("RGBA", (size, size), (11, 43, 75, 255))
    d = ImageDraw.Draw(layer)
    d.line(road, fill=(8, 33, 58, 255), width=int(15 * s), joint="curve")
    d.line(road, fill=(242, 107, 35, 255), width=int(10 * s), joint="curve")
    d.line(teal, fill=(100, 203, 214, 235), width=int(5 * s), joint="curve")
    img.paste(layer, (0, 0), mask)
    img.save(path, sizes=[(16, 16), (32, 32), (48, 48)])


def main():
    svg = build_svg()
    out = os.path.join(ASSETS, "road_network.svg")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"wrote {os.path.normpath(out)} ({len(svg.encode()) / 1024:,.0f} KB)")

    with open(os.path.join(ASSETS, "favicon.svg"), "w", encoding="utf-8") as fh:
        fh.write(FAVICON_SVG)
    write_favicon_ico(os.path.join(ASSETS, "favicon.ico"))
    print("wrote favicon.svg and favicon.ico")


if __name__ == "__main__":
    main()
