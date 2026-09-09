#!/usr/bin/env python3
"""Generate map-bg-adventure.svg: an Equal-Earth world map where the countries
(and US states) the Shapovalov family has visited are tinted, with one dot per
visited city and the city names laid out as two legend columns flanking the
map. Each label is tied to its dot by a 1px leader line.

Layout: [left legend][map strip][right legend]
  - The strip is cropped to the visited region (as before).
  - Points closer than --cluster-km merge into one city dot/label.
  - Labels stack top-to-bottom in dot-latitude order: dots left of the
    strip's midline label in the left column, the rest in the right one,
    so no leader line ever crosses the midline. Within a column a
    tangent ordering keeps leaders from crossing each other.
  - Colours are emitted as CSS custom properties on :root (edit them in one
    place to recolour the whole map).
  - Phones (image box <= the media breakpoint) hide the legends and scale the
    strip to full width via a baked CSS transform. The site pairs this with an
    aspect-ratio rule on the <img> in site.css (see PROJECT.md).

Factual sources:
  - map-data/map.kml                    -> visited points (lon, lat, name).
  - map-data/label-overrides.json       -> optional {"raw KML name": "label"}.
Boundaries (public domain, Natural Earth 1:110m, fetched once and cached):
  - ne_110m_admin_0_countries.geojson        (country polygons)
  - ne_110m_admin_1_states_provinces.geojson (US state polygons)
  - ne_110m_populated_places_simple.geojson  (city names/populations)

A point is "visited" via ray-cast point-in-polygon against the boundaries. Points
that fall just outside a coarse coastline (real coastal towns) are rescued to
their single nearest polygon within a small tolerance, so the highlight is derived
directly from the KML with no manual country lists and no border double-counting.

Projection: spherical Equal Earth (formulas from PROJ, the reference impl).
Output: img/map-bg-*.svg, transparent background. Python 3.10+, stdlib only.
"""
import argparse
import html
import json
import math
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
KML = SCRIPT_DIR / "map-data" / "map.kml"
CACHE = SCRIPT_DIR / "map-data"
OVERRIDES = CACHE / "label-overrides.json"

COUNTRIES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                 "master/geojson/ne_110m_admin_0_countries.geojson")
STATES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_110m_admin_1_states_provinces.geojson")
POP_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
           "master/geojson/ne_110m_populated_places_simple.geojson")

# Equal Earth spherical forward (PROJ reference coefficients).
A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3.0) / 2.0

# Named colour palettes -> (hex, opacity) per map role. The hex values are
# emitted as CSS custom properties on :root inside the SVG; edit them there
# (or here + re-run) to recolour.
PALETTES = {
    "default": {
        "land_fill":    ("#6b675c", 0.05),   # --muted
        "land_stroke":  ("#6b675c", 0.16),
        "state_stroke": ("#6b675c", 0.10),
        "vis_fill":     ("#3a5a80", 0.16),  # --accent (cool ink-blue)
        "vis_stroke":   ("#3a5a80", 0.30),
        "marker": {"fill": ("#3a5a80", 0.95), "ring": ("#25231e", 0.80), "r": 0.010},
        "label":  {"fill": ("#25231e", 0.92), "leader": 0.55},
    },
    "adventure": {
        "land_fill":    ("#F7F1DE", 0.50),  # beige - parchment land
        "land_stroke":  ("#B0BA99", 0.45),  # sage - coastlines
        "state_stroke": ("#B0BA99", 0.30),  # sage - state dividers
        "vis_fill":     ("#B0BA99", 0.30),  # sage - visited tint
        "vis_stroke":   ("#B0BA99", 0.55),  # sage - visited edge
        "marker": {"fill": ("#9D6638", 0.95), "ring": ("#4E220F", 0.90), "r": 0.008},
        "label":  {"fill": ("#4E220F", 0.92), "leader": 0.55},
    },
}
OUT_BY_PALETTE = {"default": "map-bg.svg", "adventure": "map-bg-adventure.svg"}

# Legend geometry constants (viewBox units, scaled off the strip / font size).
LEGEND_PITCH = 1.30     # min row pitch as a multiple of the font size
LEGEND_GAP = 0.35       # gap between a label and its leader line, x font
LEGEND_HGAP = 3.0       # gap between a legend column and the map, x font
LEGEND_VPAD = 0.75      # vertical padding above/below the stack, x max font
LEGEND_MAX_LABEL = 30   # labels longer than this are truncated with an ellipsis
LEGEND_FONT_SAFETY = 1.12  # widen estimates: real fonts vary vs the metrics
CITY_MATCH_KM = 40      # a Natural Earth city within this range names a cluster

# Line weights (CSS px: every stroke is rendered non-scaling) and marker
# sizing. Emitted as the size custom properties in the SVG's <style> block;
# edit them there for one-off tweaks, here to change future renders.
STROKE_COAST = 0.8      # coastlines / country outlines
STROKE_STATE = 0.5      # US-state dividers
STROKE_VISITED = 1.1    # visited-region edge
STROKE_LEADER = 1.0     # label leader lines
STROKE_RING = 0.5       # ring around each city dot
RING_FACTOR = 1.85      # ring radius as a multiple of the dot radius

# Legend font sizing: the font is at most 1/FONT_MAX_DIV of the strip width,
# and the canvas never grows taller than H_CAP_FACTOR times the strip (the
# busier legend column sets the row pitch that fits inside that cap).
FONT_MAX_DIV = 65.0
H_CAP_FACTOR = 3.3     # sized so labels stay legible in the 50rem content column

# Helvetica/Arial advance widths (units per 1000 em) for label-width
# estimation. Real rendering fonts differ by a few percent either way, hence
# LEGEND_FONT_SAFETY; accented letters decompose to their base glyph and
# anything unknown defaults to 0.6 em.
GLYPH_W = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278, "0": 556, "1": 556, "2": 556, "3": 556, "4": 556,
    "5": 556, "6": 556, "7": 556, "8": 556, "9": 556, ":": 278, ";": 278,
    "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "A": 667, "B": 667,
    "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278,
    "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469,
    "_": 556, "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556,
    "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500, "l": 222,
    "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500,
    "t": 278, "u": 556, "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
    "æ": 722, "Æ": 1000, "ø": 556, "Ø": 778, "ł": 222, "Ł": 556, "đ": 556,
    "Đ": 722, "ð": 556, "Ð": 722, "þ": 556, "Þ": 667, "ß": 556, "…": 1000,
    "–": 556, "—": 1000,
}


def text_width(name, font):
    """Estimated rendered width of a label at the given font size, in
    viewBox units."""
    total = 0
    for ch in unicodedata.normalize("NFD", name):
        if unicodedata.combining(ch):
            continue
        total += GLYPH_W.get(ch, 600)
    return total / 1000.0 * font * LEGEND_FONT_SAFETY


def equal_earth(lon_deg, lat_deg):
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    psi = math.asin(max(-1.0, min(1.0, M * math.sin(phi))))
    psi2 = psi * psi
    psi6 = psi2 * psi2 * psi2
    x = lam * math.cos(psi) / (M * (A1 + 3 * A2 * psi2 + psi6 * (7 * A3 + 9 * A4 * psi2)))
    y = psi * (A1 + A2 * psi2 + psi6 * (A3 + A4 * psi2))
    return x, y


UA = "shapovalov-bg/1.0 (generating site map background)"


def fetch_json_cached(url, dest):
    if dest.exists():
        return json.loads(dest.read_text(encoding="utf-8"))
    CACHE.mkdir(exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    print(f"  fetching {url}")
    data = urllib.request.urlopen(req, timeout=60).read()
    dest.write_bytes(data)
    print(f"  cached {len(data)} bytes -> {dest.name}")
    return json.loads(data)


def point_in_ring(px, py, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi + 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(px, py, geom):
    if geom["type"] == "Polygon":
        rings = geom["coordinates"]
        if not point_in_ring(px, py, rings[0]):
            return False
        return not any(point_in_ring(px, py, h) for h in rings[1:])
    if geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            if point_in_ring(px, py, poly[0]) and \
               not any(point_in_ring(px, py, h) for h in poly[1:]):
                return True
    return False


def iter_rings(geom):
    if geom["type"] == "Polygon":
        yield from geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield from poly


def d2seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp = p2 - p1
    dl = math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def cluster_points(pts, km):
    """Greedy clustering: each point joins the first cluster with a member
    within `km` kilometres. Returns a list of member lists."""
    if km <= 0:
        return [[p] for p in pts]
    clusters = []
    for p in pts:
        for cl in clusters:
            if any(haversine_km(p[:2], q[:2]) < km for q in cl):
                cl.append(p)
                break
        else:
            clusters.append([p])
    return clusters


def clean_name(raw):
    """Normalise a KML placemark name into a legend-friendly label candidate:
    fix non-breaking spaces, collapse whitespace, drop regional suffixes
    ("Sámara, Costa Rica" -> "Sámara")."""
    s = raw.replace("\xa0", " ")
    s = " ".join(s.split())
    return s.split(",")[0].strip()


def norm_ws(s):
    """Whitespace-normalised form of a name (NBSPs and runs of spaces collapse),
    so override keys can be typed with plain spaces and still match KML names."""
    return " ".join(s.replace("\xa0", " ").split())


def load_overrides(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {path} is not valid JSON ({e})", file=sys.stderr)
        print("  fix the file (or delete it) and re-run", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict) or \
       not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        print(f"error: {path} must be a JSON object of "
              '{"raw KML name": "clean label"} pairs', file=sys.stderr)
        sys.exit(2)
    return {norm_ws(k): v.strip() for k, v in data.items()}


def pick_label(members, ov, ne_cities, warnings):
    """Representative label for a cluster, in order of precedence:
    1. The biggest Natural Earth populated place within CITY_MATCH_KM of any
       member ("Ještěd" next to Prague still reads "Prague"); an override may
       rename even that city ("København" -> "Copenhagen").
    2. Otherwise, overrides rename members first, then the most common name
       wins; ties go to the shortest.
    """
    best = None  # (pop_max, -distance_km, city name)
    for lon, lat, _raw in members:
        for cname, cpop, clon, clat in ne_cities:
            d = haversine_km((lon, lat), (clon, clat))
            if d <= CITY_MATCH_KM:
                cand = (cpop, -d, cname)
                if best is None or cand > best:
                    best = cand
    if best is not None:
        label = ov.get(best[2], best[2])
    else:
        names = []
        for _lon, _lat, raw in members:
            c = clean_name(raw)
            if norm_ws(raw) in ov:
                names.append(ov[norm_ws(raw)])
            elif c and c in ov:
                names.append(ov[c])
            elif c:
                names.append(c)
        votes = {}
        for n in names:
            votes[n] = votes.get(n, 0) + 1
        label = max(votes, key=lambda n: (votes[n], -len(n))) if votes else "?"
    if len(label) > LEGEND_MAX_LABEL:
        cut = label[:LEGEND_MAX_LABEL - 1].rsplit(" ", 1)[0]
        warnings.append(f"label truncated: {label!r} -> {cut + '…'!r}")
        label = cut + "…"
    return label


def tangent_order(dts, slots):
    """Slot order (top to bottom) for straight leaders that never cross.

    All leaders of a column start on one vertical line (the column edge).
    Assign slots top to bottom, giving each slot the "upper tangent" dot: the
    remaining dot whose leader line leaves every other remaining dot at or
    below it. Every later leader joins a lower slot to a dot below that
    line, so it can never cross it. Falls back to the topmost remaining dot
    if no tangent exists (should not happen with distinct dots).
    """
    remaining = list(range(len(dts)))
    order = []
    for s in slots:
        best = None
        for D in remaining:
            dD, tD = dts[D]
            for E in remaining:
                if E == D:
                    continue
                dE, tE = dts[E]
                if dD * (tE - s) - (tD - s) * dE < -1e-9:
                    break  # E sits above D's line; D is not the tangent
            else:
                if best is None or tD < dts[best][1]:
                    best = D
        if best is None:
            best = min(remaining, key=lambda i: dts[i][1])
        order.append(best)
        remaining.remove(best)
    return order


def leader_crossings(placed):
    """Exact count of crossing leader pairs within a side (orientation test)."""
    def turn(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    n = 0
    for i in range(len(placed)):
        a, b = placed[i]
        for j in range(i + 1, len(placed)):
            c, d = placed[j]
            if turn(a, b, c) != turn(a, b, d) and turn(c, d, a) != turn(c, d, b):
                n += 1
    return n


def repair_crossings(order, slots, dts, rounds=500):
    """Swap the slots of crossing leader pairs until none remain.

    The tangent assignment is crossing-free when it completes, but its
    conservative test can find no candidate for a slot (steep leader lines
    with sparsely spaced slots); the fallback pick may then cross, and this
    deterministic repair finishes the job. Works on the 3-decimal coordinates
    that are actually emitted and counts grazing touches as crossings, so
    sub-pixel near-misses in full precision cannot reappear after rounding.
    """
    def turn(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    for _ in range(rounds):
        ss = [((0.0, s), dts[i]) for s, i in zip(slots, order)]
        for a in range(len(ss)):
            p, q = ss[a]
            for b in range(a + 1, len(ss)):
                r, t = ss[b]
                if turn(p, q, r) != turn(p, q, t) and \
                   turn(r, t, p) != turn(r, t, q):
                    order[a], order[b] = order[b], order[a]
                    break
            else:
                continue
            break
    return order


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--palette", default="default", choices=list(PALETTES),
                    help="colour scheme (default: %(default)s)")
    ap.add_argument("--out", default=None,
                    help="output filename (default: derived from --palette)")
    ap.add_argument("--opacity", type=float, default=None,
                    help="absolute opacity (0-1) applied to every layer that "
                         "doesn't have its own knob below; omit to use palette "
                         "defaults")
    ap.add_argument("--no-dots", dest="dots", action="store_false",
                    help="don't plot a marker for each city "
                         "(dots are on by default)")
    ap.add_argument("--land-opacity", type=float, default=None,
                    help="absolute opacity (0-1) of the unvisited land base, "
                         "coastlines, and state dividers; overrides --opacity; "
                         "default uses the palette")
    ap.add_argument("--visited-opacity", type=float, default=None,
                    help="absolute opacity (0-1) of the visited regions (fill "
                         "and edge); overrides --opacity; default uses the palette")
    ap.add_argument("--dot-opacity", type=float, default=None,
                    help="absolute opacity (0-1) of the city markers "
                         "(dot and ring); overrides --opacity; default uses the "
                         "palette")
    ap.add_argument("--dot-size", type=float, default=None,
                    help="absolute radius (viewBox units) of the city markers; "
                         "the ring scales with it; default uses the palette")
    ap.add_argument("--crop-visited", action="store_true",
                    help="size the map strip to a bounding box around the visited "
                         "region (projected screen space) instead of the whole "
                         "world; non-visited land shows faintly as context")
    ap.add_argument("--pad", type=float, default=0.02,
                    help="padding around the map strip as a fraction of its size "
                         "(default %(default)s)")
    ap.add_argument("--no-legend", dest="legend", action="store_false",
                    help="drop the side legend columns and leader lines; "
                         "render only the map strip with city dots")
    ap.add_argument("--cluster-km", type=float, default=100.0,
                    help="merge visited points within this many kilometres into "
                         "one city dot with one label (default %(default)s; "
                         "0 labels every point separately)")
    ap.add_argument("--legend-breakpoint", type=int, default=700,
                    help="media width (px of the rendered <img> box) below which "
                         "the legend columns and leader lines are hidden and the "
                         "strip is scaled to full width (default %(default)s)")
    ap.add_argument("--label-overrides", type=Path, default=OVERRIDES,
                    help="optional JSON file of {'raw KML name': 'clean label'} "
                         f"rewrites (default: {OVERRIDES} if present)")
    args = ap.parse_args()
    for _k in ("opacity", "land_opacity", "visited_opacity", "dot_opacity"):
        _v = getattr(args, _k)
        if _v is not None and not (0 <= _v <= 1.0):
            ap.error(f"--{_k.replace('_', '-')} must be between 0 and 1")
    if args.dot_size is not None and not (0 < args.dot_size <= 0.1):
        ap.error("--dot-size must be a positive radius (<= 0.1)")
    if not (0 <= args.pad <= 1.0):
        ap.error("--pad must be between 0 and 1")
    if args.cluster_km < 0:
        ap.error("--cluster-km must be >= 0")

    if not KML.exists():
        print(f"missing {KML}", file=sys.stderr)
        return 1
    out_path = REPO / "img" / (args.out or OUT_BY_PALETTE[args.palette])
    print(f"palette: {args.palette}  ->  {out_path.name}")

    overrides = load_overrides(args.label_overrides)
    if overrides:
        print(f"  label overrides: {len(overrides)} from {args.label_overrides.name}")

    countries = fetch_json_cached(COUNTRIES_URL, CACHE / "ne_110m_countries.geojson")
    states = fetch_json_cached(STATES_URL, CACHE / "ne_110m_states.geojson")
    pop = fetch_json_cached(POP_URL, CACHE / "ne_110m_populated_places_simple.geojson")
    ne_cities = []  # (name, pop_max, lon, lat)
    for f in pop["features"]:
        p = f.get("properties", {})
        if p.get("name") and p.get("pop_max") is not None:
            ne_cities.append((p["name"], int(p["pop_max"]),
                              float(p["longitude"]), float(p["latitude"])))
    print(f"  reference cities: {len(ne_cities)} (Natural Earth populated places)")

    ns = {"k": "http://www.opengis.net/kml/2.2"}
    pts = []  # (lon, lat, name)
    for pm in ET.parse(KML).getroot().findall(".//k:Placemark", ns):
        c = pm.find("k:Point/k:coordinates", ns)
        if c is None or not c.text:
            continue
        lon, lat, *_ = [float(v) for v in c.text.strip().split(",")]
        name = (pm.find("k:name", ns).text or "").strip()
        pts.append((lon, lat, name))
    print(f"  visited points: {len(pts)}")

    # Unify features: countries (skip USA -> drawn via states) + US states.
    feats = []  # (fid, kind, geom, name)
    for f in countries["features"]:
        if not f["geometry"]:
            continue
        props = f.get("properties", {})
        if (props.get("ISO_A2_EH") or props.get("ISO_A2") or "") == "US":
            continue
        feats.append((id(f), "country", f["geometry"],
                      props.get("ADMIN") or props.get("NAME") or "?"))
    for f in states["features"]:
        if not f["geometry"]:
            continue
        props = f["properties"]
        if props.get("iso_a2") == "US" or props.get("admin") == "United States of America":
            feats.append((id(f), "state", f["geometry"],
                          props.get("name") or props.get("gn_name") or "?"))

    # Classify: strict PIP, then rescue coastal misses to nearest polygon.
    visited_ids = set()
    orphans = []
    for lon, lat, _name in pts:
        insiders = [fid for fid, kind, geom, name in feats
                    if point_in_polygon(lon, lat, geom)]
        if insiders:
            visited_ids.update(insiders)
        else:
            orphans.append((lon, lat))

    EPS2 = 0.05 ** 2  # ~5.5 km rescue tolerance for coastal points
    for lon, lat in orphans:
        best, best_fid, best_name = EPS2, None, None
        for fid, kind, geom, name in feats:
            mn = min(d2seg(lon, lat, ax, ay, bx, by)
                     for ring in iter_rings(geom)
                     for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]))
            if mn <= best:
                best, best_fid, best_name = mn, fid, name
        if best_fid:
            visited_ids.add(best_fid)
            print(f"  rescued ({lon:.3f}, {lat:.3f}) -> {best_name} "
                  f"({math.sqrt(best):.3f} deg)")

    visited_countries = sorted({name for fid, kind, geom, name in feats
                                if fid in visited_ids and kind == "country"})
    visited_states = sorted({name for fid, kind, geom, name in feats
                             if fid in visited_ids and kind == "state"})
    print(f"  visited countries ({len(visited_countries)}): {visited_countries}")
    print(f"  visited US states ({len(visited_states)}): {visited_states}")

    # Project everything, track bounds.
    def project_rings(geom):
        return [[equal_earth(lon, lat) for lon, lat, *_ in ring]
                for ring in iter_rings(geom)]

    all_polys = []  # (projected_rings, kind, visited)
    xs, ys = [], []
    for fid, kind, geom, name in feats:
        prings = project_rings(geom)
        rx = [p[0] for ring in prings for p in ring]
        ry = [p[1] for ring in prings for p in ring]
        xs += rx
        ys += ry
        bounds = (min(rx), max(rx), min(ry), max(ry))
        all_polys.append((prings, kind, fid in visited_ids, bounds, fid))

    if args.crop_visited:
        # Frame only the visited region: bound by visited polygons + the points.
        xs, ys = [], []
        for prings, kind, visited, (b0, b1, b2, b3), fid in all_polys:
            if not visited:
                continue
            xs += [b0, b1]
            ys += [b2, b3]
        for lon, lat, _name in pts:
            x, y = equal_earth(lon, lat)
            xs.append(x)
            ys.append(y)

    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = args.pad * max(maxx - minx, maxy - miny)
    minx -= pad
    maxx += pad
    miny -= pad
    maxy += pad
    sw, sh = maxx - minx, maxy - miny

    def in_frame(bounds):
        b0, b1, b2, b3 = bounds
        return not (b1 < minx or b0 > maxx or b3 < miny or b2 > maxy)

    if args.crop_visited:
        all_polys = [p for p in all_polys if in_frame(p[3])]
        print(f"  cropped to visited region: {sw:.3f} x {sh:.3f} (pad {args.pad:g}), "
              f"{len(all_polys)} regions in frame")

    # Cities: cluster the points, resolve labels, project cluster centroids.
    warnings = []
    clusters = cluster_points(pts, args.cluster_km)
    cities = []  # (canvas cx computed later, canvas cy, label, n_members)
    for members in clusters:
        proj = [equal_earth(lon, lat) for lon, lat, _n in members]
        cx = sum(p[0] for p in proj) / len(proj)
        cy = sum(p[1] for p in proj) / len(proj)
        label = pick_label(members, overrides, ne_cities, warnings) if args.legend else ""
        cities.append((cx, cy, label, len(members)))
    print(f"  cities: {len(cities)} (cluster {args.cluster_km:g} km, "
          f"{len(pts)} points)")

    # Legend geometry. The canvas is [left legend][strip][right legend]; the
    # strip is vertically centred, the label stacks fill the full height.
    # Sides are strictly geographic: dots left of the strip's midline label
    # in the left column, the rest in the right one, so no leader line ever
    # crosses the midline. The sides can be uneven (the visited region is
    # denser in the east), so each column spreads its own labels evenly over
    # the full height and the font is sized by the busier side.
    n_left = n_right = rows = 0
    if args.legend and cities:
        n_left = sum(1 for c in cities if c[0] - minx < sw / 2)
        n_right = len(cities) - n_left
        rows = max(n_left, n_right, 1)
        font_max = sw / FONT_MAX_DIV         # font ceiling for sparse datasets
        vpad = LEGEND_VPAD * font_max
        h_cap = H_CAP_FACTOR * sh            # don't let the canvas grow forever
        font = min(font_max, (h_cap - 2 * vpad) / (rows * LEGEND_PITCH))
        pitch = LEGEND_PITCH * font          # min row pitch (busier side)
        gap, hgap = LEGEND_GAP * font, LEGEND_HGAP * font
        widest = max(text_width(c[2], font) for c in cities)
        legend_w = widest + gap + 0.5 * font
        height = max(sh, rows * pitch + 2 * vpad)
        ox = legend_w + hgap                 # strip left edge in canvas coords
        oy = (height - sh) / 2               # strip top edge
        width = 2 * (legend_w + hgap) + sw
    else:
        cities = [(cx, cy, "", m) for cx, cy, _l, m in cities]
        font = pitch = legend_w = 0.0
        ox, oy, width, height = 0.0, 0.0, sw, sh

    # Place the labels: each side takes its half's cities, ordered by the
    # tangent algorithm so no two leaders of a side cross, and spread evenly
    # across the canvas height.
    placed = []  # (side, label_y, dot_x, dot_y, label)
    if args.legend and cities:
        halves = {"L": [], "R": []}
        for cx, cy, label, _m in cities:
            dx, dy = ox + (cx - minx), oy + (maxy - cy)
            halves["L" if cx - minx < sw / 2 else "R"].append((dx, dy, label))
        for side in ("L", "R"):
            subset = halves[side]
            if not subset:
                continue
            # Rows sit at the minimum pitch, or wider only if the side's dots
            # span more height than that; the block is centred on its dots'
            # latitude span and kept inside the canvas padding.
            dys = [dy for _dx, dy, _label in subset]
            span = max(dys) - min(dys)
            spread = max(pitch, span / max(1, len(subset) - 1))
            top = (min(dys) + max(dys)) / 2 - spread * len(subset) / 2
            top = min(max(vpad, top),
                      max(vpad, height - vpad - spread * len(subset)))
            slots = [top + (i + 0.5) * spread for i in range(len(subset))]
            edge = ox - hgap if side == "L" else ox + sw + hgap
            edge_q = round(edge, 3)
            sgn = 1.0 if side == "L" else -1.0
            dts = [(sgn * (dx - edge), dy) for dx, dy, _label in subset]
            # Quantise exactly like the emitted coordinates (edge included),
            # so the repair and the self-check see the geometry that ships.
            dts_q = [(round(sgn * (round(dx, 3) - edge_q), 3), round(dy, 3))
                     for dx, dy, _label in subset]
            slots_q = [round(s, 3) for s in slots]
            order = repair_crossings(tangent_order(dts, slots), slots_q, dts_q)
            segs = []
            for s, i in zip(slots_q, order):
                dx, dy, label = subset[i]
                dx, dy = round(dx, 3), round(dy, 3)
                placed.append((side, s, dx, dy, label))
                segs.append(((edge_q, s), (dx, dy)))
            crossed = leader_crossings(segs)
            if crossed:
                warnings.append(f"{crossed} crossing leader lines on side {side}")
        print(f"  legend: {n_left} labels left, {n_right} right (split at strip "
              f"midline {sw / 2:.3f}, font {font:.4f}, min pitch {pitch:.4f}, "
              f"tangent-ordered)")

    dupes = {l for l in (p[4] for p in placed) if l
             and sum(1 for q in placed if q[4] == l) > 1}
    for d in sorted(dupes):
        warnings.append(f"duplicate label (add an override to disambiguate): {d!r}")
    for w in warnings:
        print(f"  note: {w}")

    # Resolve ABSOLUTE opacities. Rule (override-precedence, all on a 0-1 scale):
    #   explicit per-layer knob  >  --opacity (catch-all)  >  palette default
    P = PALETTES[args.palette]

    def op(knob, default):
        if knob is not None:
            return knob
        if args.opacity is not None:
            return args.opacity
        return default

    LAND_FILL_OP = op(args.land_opacity, P["land_fill"][1])
    LAND_STROKE_OP = op(args.land_opacity, P["land_stroke"][1])
    STATE_STROKE_OP = op(args.land_opacity, P["state_stroke"][1])
    VIS_FILL_OP = op(args.visited_opacity, P["vis_fill"][1])
    VIS_STROKE_OP = op(args.visited_opacity, P["vis_stroke"][1])
    MARK_FILL_OP = op(args.dot_opacity, P["marker"]["fill"][1])
    RING_OP = op(args.dot_opacity, P["marker"]["ring"][1])
    LABEL_FILL_OP = P["label"]["fill"][1]
    LEADER_OP = P["label"]["leader"]

    m = P["marker"]
    dot_r = args.dot_size if args.dot_size is not None else m["r"]
    ring_r = dot_r * RING_FACTOR

    def path_d(rings):
        return "".join(
            "M" + " L".join(f"{(ox + x - minx):.3f} {(oy + maxy - y):.3f}"
                            for x, y in ring) + " Z"
            for ring in rings)

    def dot_pos(cx, cy):
        return ox + (cx - minx), oy + (maxy - cy)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width:.3f} {height:.3f}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="World map with visited regions highlighted and '
        f'{"labelled city dots" if args.legend else "city dots"}">',
        '<title>Visited places</title>',
    ]
    style = [
        ":root{",
        f"--land:{P['land_fill'][0]};--coast:{P['land_stroke'][0]};"
        f"--state:{P['state_stroke'][0]};",
        f"--visited:{P['vis_fill'][0]};--visited-edge:{P['vis_stroke'][0]};",
        f"--dot:{m['fill'][0]};--dot-ring:{m['ring'][0]};"
        f"--label:{P['label']['fill'][0]};--leader:{m['ring'][0]};",
        f"--stroke-coast:{STROKE_COAST};--stroke-state:{STROKE_STATE};"
        f"--stroke-visited:{STROKE_VISITED};--stroke-leader:{STROKE_LEADER};"
        f"--stroke-ring:{STROKE_RING}",
        "}",
        ".legend{font-family:ui-sans-serif,system-ui,-apple-system,"
        "Segoe UI,Roboto,sans-serif}",
    ]
    if args.legend and cities:
        # Phones: hide the legends and scale the strip to the full canvas.
        k = width / sw
        tx = -k * ox
        ty = height / 2 - k * (oy + sh / 2)
        style.append(
            f"@media (max-width:{args.legend_breakpoint}px){{"
            ".legend,.leaders{display:none}"
            f".map{{transform:translate({tx:.4f}px,{ty:.4f}px) "
            f"scale({k:.4f})}}}}")
    lines.append("<style>" + "".join(style) + "</style>")

    lines.append('<g class="map" shape-rendering="geometricPrecision">')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if kind == "country":
            lines.append(f'<path d="{path_d(prings)}" fill="var(--land)" '
                         f'fill-opacity="{LAND_FILL_OP}" stroke="var(--coast)" '
                         f'stroke-opacity="{LAND_STROKE_OP}" stroke-width="var(--stroke-coast)" '
                         f'vector-effect="non-scaling-stroke"/>')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if kind == "state":
            lines.append(f'<path d="{path_d(prings)}" fill="none" '
                         f'stroke="var(--state)" stroke-opacity="{STATE_STROKE_OP}" '
                         f'stroke-width="var(--stroke-state)" vector-effect="non-scaling-stroke"/>')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if visited:
            lines.append(f'<path d="{path_d(prings)}" fill="var(--visited)" '
                         f'fill-opacity="{VIS_FILL_OP}" stroke="var(--visited-edge)" '
                         f'stroke-opacity="{VIS_STROKE_OP}" stroke-width="var(--stroke-visited)" '
                         f'vector-effect="non-scaling-stroke"/>')
    # City dots: one per cluster, projected through Equal Earth.
    if args.dots:
        for cx, cy, _label, _nmem in cities:
            dx, dy = dot_pos(cx, cy)
            lines.append(f'<circle class="dot" cx="{dx:.3f}" cy="{dy:.3f}" r="{dot_r}" '
                         f'fill="var(--dot)" fill-opacity="{MARK_FILL_OP}"/>')
            lines.append(f'<circle class="ring" cx="{dx:.3f}" cy="{dy:.3f}" r="{ring_r:.4f}" '
                         f'fill="none" stroke="var(--dot-ring)" '
                         f'stroke-opacity="{RING_OP}" stroke-width="var(--stroke-ring)" '
                         f'vector-effect="non-scaling-stroke"/>')
    lines.append("</g>")

    if placed:
        lines.append(f'<g class="leaders">')
        for side, ly, dot_x, dot_y, _label in placed:
            lx = ox - hgap if side == "L" else ox + sw + hgap
            lines.append(
                f'<line x1="{lx:.3f}" y1="{ly:.3f}" x2="{dot_x:.3f}" '
                f'y2="{dot_y:.3f}" stroke="var(--leader)" '
                f'stroke-opacity="{LEADER_OP}" stroke-width="var(--stroke-leader)" '
                f'vector-effect="non-scaling-stroke"/>')
        lines.append("</g>")
        lines.append('<g class="legend">')
        for side, ly, _dot_x, _dot_y, label in placed:
            tx = ox - hgap - gap if side == "L" else ox + sw + hgap + gap
            anchor = "end" if side == "L" else "start"
            lines.append(
                f'<text x="{tx:.3f}" y="{ly:.3f}" font-size="{font:.4f}" '
                f'fill="var(--label)" fill-opacity="{LABEL_FILL_OP}" '
                f'text-anchor="{anchor}" dominant-baseline="central">'
                f'{html.escape(label)}</text>')
        lines.append("</g>")

    lines.append("</svg>")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"  canvas {width:.3f} x {height:.3f} (aspect {width / height:.2f}:1, "
          f"strip {sw:.3f} x {sh:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
