#!/usr/bin/env python3
"""Generate map-bg.svg: a very faint Equal-Earth world map background where the
countries (and US states) the Shapovalov family has actually visited are tinted.

Factual source:
  - map-data/map.kml  -> 133 visited points (lon, lat).
Boundaries (public domain, Natural Earth 1:110m, fetched once and cached):
  - ne_110m_admin_0_countries.geojson        (country polygons)
  - ne_110m_admin_1_states_provinces.geojson (US state polygons)

A point is "visited" via ray-cast point-in-polygon against the boundaries. Points
that fall just outside a coarse coastline (real coastal towns) are rescued to
their single nearest polygon within a small tolerance, so the highlight is derived
directly from the KML with no manual country lists and no border double-counting.

Projection: spherical Equal Earth (formulas from PROJ, the reference impl).
Output: img/map-bg.svg, transparent background, faint gray land with
a subtle blue tint on visited regions. Use it as a CSS background-image.
"""
import argparse
import html
import json
import math
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
KML = SCRIPT_DIR / "map-data" / "map.kml"
CACHE = SCRIPT_DIR / "map-data"

COUNTRIES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                 "master/geojson/ne_110m_admin_0_countries.geojson")
STATES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_110m_admin_1_states_provinces.geojson")

# Equal Earth spherical forward (PROJ reference coefficients).
A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3.0) / 2.0

# Named colour palettes -> (hex, opacity) per map role.
#   land_fill   : base tint of every landmass (keep faint).
#   land_stroke : coastline / country outline.
#   state_stroke: faint US-state dividers.
#   vis_fill    : fill of visited regions.
#   vis_stroke  : outline of visited regions.
PALETTES = {
    "default": {
        "land_fill":   ("#6b675c", 0.05),   # --muted
        "land_stroke": ("#6b675c", 0.16),
        "state_stroke":("#6b675c", 0.10),
        "vis_fill":    ("#3a5a80", 0.16),  # --accent (cool ink-blue)
        "vis_stroke":  ("#3a5a80", 0.30),
        # marker: solid dot + soft halo
        "marker": {"fill": ("#3a5a80", 0.95), "halo": ("#ffffff", 0.30), "r": 0.010},
        "label": {"fill": ("#25231e", 0.92), "halo": ("#ffffff", 0.75), "size": 0.045},
    },
    "adventure": {
        "land_fill":   ("#F7F1DE", 0.50),  # beige — parchment land
        "land_stroke": ("#B0BA99", 0.45),  # sage — coastlines
        "state_stroke":("#B0BA99", 0.30),  # sage — state dividers
        "vis_fill":    ("#B0BA99", 0.30),  # sage — visited tint
        "vis_stroke":  ("#B0BA99", 0.55),  # sage — visited edge
        # marker: brown dot + crisp 1px dark-brown ring (no glow)
        "marker": {"fill": ("#9D6638", 0.95), "ring": ("#4E220F", 0.90), "r": 0.007},
        "label": {"fill": ("#4E220F", 0.92), "halo": ("#F7F1DE", 0.85), "size": 0.045},
    },
}
OUT_BY_PALETTE = {"default": "map-bg.svg", "adventure": "map-bg-adventure.svg"}


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--palette", default="default", choices=list(PALETTES),
                    help="colour scheme (default: %(default)s)")
    ap.add_argument("--out", default=None,
                    help="output filename (default: derived from --palette)")
    ap.add_argument("--opacity", type=float, default=None,
                    help="absolute opacity (0–1) applied to every layer that "
                         "doesn't have its own knob below; omit to use palette "
                         "defaults")
    ap.add_argument("--no-dots", dest="dots", action="store_false",
                    help="don't plot a marker at every visited point "
                         "(dots are on by default)")
    ap.add_argument("--land-opacity", type=float, default=None,
                    help="absolute opacity (0–1) of the unvisited land base, "
                         "coastlines, and state dividers; overrides --opacity; "
                         "default uses the palette")
    ap.add_argument("--visited-opacity", type=float, default=None,
                    help="absolute opacity (0–1) of the visited regions (fill "
                         "and edge); overrides --opacity; default uses the palette")
    ap.add_argument("--dot-opacity", type=float, default=None,
                    help="absolute opacity (0–1) of the visited-point markers "
                         "(dot, ring, halo); overrides --opacity; default uses "
                         "the palette")
    ap.add_argument("--dot-size", type=float, default=None,
                    help="absolute radius (viewBox units) of the visited-point "
                         "markers; ring & halo scale with it; default uses the "
                         "palette (~0.007–0.010)")
    ap.add_argument("--crop-visited", action="store_true",
                    help="size the output to a bounding box around the visited "
                         "region (projected screen space) instead of the whole "
                         "world; non-visited land shows faintly as context")
    ap.add_argument("--pad", type=float, default=0.02,
                    help="padding around the map frame as a fraction of its size "
                         "(default %(default)s; try ~0.08 with --crop-visited)")
    ap.add_argument("--labels", action="store_true",
                    help="label visited countries (Natural Earth anchors, "
                         "decluttered by LABELRANK)")
    ap.add_argument("--label-leaders", action="store_true",
                    help="with --labels: nudge crowded labels aside and draw a "
                         "short leader line to the country; a label with no "
                         "clean spot nearby is omitted")
    ap.add_argument("--label-opacity", type=float, default=None,
                    help="absolute opacity (0–1) of country labels; overrides "
                         "--opacity; default uses the palette")
    args = ap.parse_args()
    for _k in ("opacity", "land_opacity", "visited_opacity", "dot_opacity",
               "label_opacity"):
        _v = getattr(args, _k)
        if _v is not None and not (0 <= _v <= 1.0):
            ap.error(f"--{_k.replace('_', '-')} must be between 0 and 1")
    if args.dot_size is not None and not (0 < args.dot_size <= 0.1):
        ap.error("--dot-size must be a positive radius (<= 0.1)")
    if not (0 <= args.pad <= 1.0):
        ap.error("--pad must be between 0 and 1")

    if not KML.exists():
        print(f"missing {KML}", file=sys.stderr)
        return 1
    out_path = REPO / "img" / (args.out or OUT_BY_PALETTE[args.palette])
    print(f"palette: {args.palette}  ->  {out_path.name}")

    countries = fetch_json_cached(COUNTRIES_URL, CACHE / "ne_110m_countries.geojson")
    states = fetch_json_cached(STATES_URL, CACHE / "ne_110m_states.geojson")

    ns = {"k": "http://www.opengis.net/kml/2.2"}
    pts = []
    for pm in ET.parse(KML).getroot().findall(".//k:Placemark", ns):
        c = pm.find("k:Point/k:coordinates", ns)
        if c is None or not c.text:
            continue
        lon, lat, *_ = [float(v) for v in c.text.strip().split(",")]
        pts.append((lon, lat))
    print(f"  visited points: {len(pts)}")

    # Unify features: countries (skip USA -> drawn via states) + US states.
    feats = []  # (fid, kind, geom, name)
    country_label = {}  # fid -> (name, labelrank, label_x, label_y)
    for f in countries["features"]:
        if not f["geometry"]:
            continue
        props = f.get("properties", {})
        if (props.get("ISO_A2_EH") or props.get("ISO_A2") or "") == "US":
            continue
        feats.append((id(f), "country", f["geometry"],
                      props.get("ADMIN") or props.get("NAME") or "?"))
        if props.get("LABEL_X") is not None and props.get("LABEL_Y") is not None:
            country_label[id(f)] = (
                props.get("NAME") or props.get("ADMIN") or "?",
                int(props.get("LABELRANK") or 9),
                float(props["LABEL_X"]), float(props["LABEL_Y"]))
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
    for lon, lat in pts:
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
        xs += rx; ys += ry
        bounds = (min(rx), max(rx), min(ry), max(ry))
        all_polys.append((prings, kind, fid in visited_ids, bounds, fid))

    if args.crop_visited:
        # Frame only the visited region: bound by visited polygons + the points.
        xs, ys = [], []
        for prings, kind, visited, (b0, b1, b2, b3), fid in all_polys:
            if not visited:
                continue
            xs += [b0, b1]; ys += [b2, b3]
        for lon, lat in pts:
            x, y = equal_earth(lon, lat)
            xs.append(x); ys.append(y)

    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = args.pad * max(maxx - minx, maxy - miny)
    minx -= pad; maxx += pad; miny -= pad; maxy += pad
    w, h = maxx - minx, maxy - miny

    def in_frame(bounds):
        b0, b1, b2, b3 = bounds
        return not (b1 < minx or b0 > maxx or b3 < miny or b2 > maxy)

    if args.crop_visited:
        all_polys = [p for p in all_polys if in_frame(p[3])]
        print(f"  cropped to visited region: {w:.3f} x {h:.3f} (pad {args.pad:g}), "
              f"{len(all_polys)} regions in frame")

    def path_d(rings):
        return "".join(
            "M" + " L".join(f"{(x - minx):.3f} {(maxy - y):.3f}" for x, y in ring) + " Z"
            for ring in rings)

    # Resolve ABSOLUTE opacities. Rule (override-precedence, all on a 0–1 scale):
    #   explicit per-layer knob  >  --opacity (catch-all)  >  palette default
    # Nothing multiplies; every value emitted is the element's final opacity.
    P = PALETTES[args.palette]

    def op(knob, default):
        if knob is not None:
            return knob
        if args.opacity is not None:
            return args.opacity
        return default

    LAND_FILL = P["land_fill"][0]
    LAND_STROKE = P["land_stroke"][0]
    STATE_STROKE = P["state_stroke"][0]
    LAND_FILL_OP = op(args.land_opacity, P["land_fill"][1])
    LAND_STROKE_OP = op(args.land_opacity, P["land_stroke"][1])
    STATE_STROKE_OP = op(args.land_opacity, P["state_stroke"][1])
    VIS_FILL = P["vis_fill"][0]
    VIS_STROKE = P["vis_stroke"][0]
    VIS_FILL_OP = op(args.visited_opacity, P["vis_fill"][1])
    VIS_STROKE_OP = op(args.visited_opacity, P["vis_stroke"][1])
    SW = 0.004

    # Marker geometry + opacities (used only when dots are on).
    m = P["marker"]
    dot_r = args.dot_size if args.dot_size is not None else m["r"]
    ring_r, halo_r = dot_r * 1.85, dot_r * 2.0
    halo, ring = m.get("halo"), m.get("ring")
    MARK_FILL, MARK_FILL_OP = m["fill"][0], op(args.dot_opacity, m["fill"][1])
    HALO_OP = op(args.dot_opacity, halo[1]) if halo else None
    RING_OP = op(args.dot_opacity, ring[1]) if ring else None

    # Country labels (visited only), anchored at Natural Earth LABEL_X/LABEL_Y and
    # decluttered by LABELRANK: place highest-priority (lowest rank) first, drop
    # any whose anchor is too close to one already placed.
    LABELS = []
    if args.labels:
        lab = P["label"]
        LFILL = lab["fill"][0]
        LFILL_OP = op(args.label_opacity, lab["fill"][1])
        LHALO = lab["halo"][0]
        LHALO_OP = op(args.label_opacity, lab["halo"][1])
        LSIZE = lab["size"]
        LEADER_OP = op(args.label_opacity, lab["fill"][1]) * 0.5
        cands = []
        for _r, _k, _v, _b, fid in all_polys:
            if _k != "country" or not _v:
                continue
            info = country_label.get(fid)
            if info:
                name, rank, lx, ly = info
                x, y = equal_earth(lx, ly)
                cands.append((rank, x, y, name))
        cands.sort(key=lambda c: (c[0], c[1]))
        # Box half-extents: char_w approximates the per-glyph half-advance, so
        # len(name) * char_w is the half-width of the rendered text.
        char_w, line_h, gap = LSIZE * 0.28, LSIZE * 0.35, LSIZE * 0.15

        def overlaps(x, y, hw, hh, placed):
            return any(abs(x - px) < (hw + phw + gap) and abs(y - py) < (hh + phh + gap)
                       for px, py, phw, phh in placed)

        def leader_hits_text(ax, ay, lx, ly, placed):
            """True if the anchor->label segment strikes the text of an
            already-placed label (its box shrunk to roughly the glyphs, since
            a leader grazing a box edge is fine but crossing text is not)."""
            for px, py, phw, phh in placed:
                xmin, xmax = px - phw * 0.7, px + phw * 0.7
                ymin, ymax = py - phh * 0.7, py + phh * 0.7
                dx, dy = lx - ax, ly - ay
                t0, t1 = 0.0, 1.0
                for d, q, lo, hi in ((dx, ax, xmin, xmax), (dy, ay, ymin, ymax)):
                    if abs(d) < 1e-12:
                        if q < lo or q > hi:
                            t0, t1 = 1.0, 0.0
                            break
                    else:
                        ta, tb = (lo - q) / d, (hi - q) / d
                        if ta > tb:
                            ta, tb = tb, ta
                        t0, t1 = max(t0, ta), min(t1, tb)
                if t0 <= t1:
                    return True
            return False

        placed = []  # (x, y, hw, hh) of label boxes already placed
        if args.label_leaders:
            # Try the anchor, then spiral outward for a free spot nearby. A
            # leader must stay short and may not cross another label's text;
            # a label with no clean spot within max_r is dropped rather than
            # flung far from its country by a long stray line.
            step, max_r = LSIZE * 0.45, LSIZE * 3.0
            for rank, ax, ay, name in cands:
                hw, hh = len(name) * char_w, line_h
                lx, ly = ax, ay
                if overlaps(ax, ay, hw, hh, placed):
                    found, r = False, step
                    while r <= max_r and not found:
                        n = max(8, int(2 * math.pi * r / step))
                        # stagger alternate rings so candidates don't retrace
                        off = 0.5 / n if int(round(r / step)) % 2 else 0.0
                        for i in range(n):
                            ang = 2 * math.pi * (i + off) / n
                            cx, cy = ax + r * math.cos(ang), ay + r * math.sin(ang)
                            if not overlaps(cx, cy, hw, hh, placed) and \
                               not leader_hits_text(ax, ay, cx, cy, placed):
                                lx, ly, found = cx, cy, True
                                break
                        r += step
                    if not found:
                        print(f"  dropping boxed-in label: {name}")
                        continue
                placed.append((lx, ly, hw, hh))
                LABELS.append((ax, ay, lx, ly, rank, name))
        else:
            # Declutter: drop a label if its anchor slot overlaps one placed.
            for rank, x, y, name in cands:
                hw, hh = len(name) * char_w, line_h
                if overlaps(x, y, hw, hh, placed):
                    continue
                placed.append((x, y, hw, hh))
                LABELS.append((x, y, x, y, rank, name))

    print(f"  opacities: land={LAND_FILL_OP} visited={VIS_FILL_OP}"
          + (f" dots={MARK_FILL_OP}" if args.dots else "")
          + (f" labels={len(LABELS)}" if args.labels else ""))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.3f} {h:.3f}" '
        f'preserveAspectRatio="xMidYMid slice" role="img" '
        f'aria-label="World map with visited regions highlighted">',
        '<title>Visited places</title>',
    ]
    if args.labels:
        lines.append(
            '<style>.label{font-family:ui-sans-serif,system-ui,-apple-system,'
            'Segoe UI,Roboto,sans-serif}'
            '@media (max-width:700px){.lr5,.lr6{display:none}}'
            '@media (max-width:480px){.lr4,.lr5,.lr6{display:none}}'
            '</style>')
    lines.append('<g shape-rendering="geometricPrecision">')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if kind == "country":
            lines.append(f'<path d="{path_d(prings)}" fill="{LAND_FILL}" '
                         f'fill-opacity="{LAND_FILL_OP}" stroke="{LAND_STROKE}" '
                         f'stroke-opacity="{LAND_STROKE_OP}" stroke-width="{SW}"/>')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if kind == "state":
            lines.append(f'<path d="{path_d(prings)}" fill="none" '
                         f'stroke="{STATE_STROKE}" stroke-opacity="{STATE_STROKE_OP}" '
                         f'stroke-width="0.003"/>')
    for prings, kind, visited, _bounds, _fid in all_polys:
        if visited:
            lines.append(f'<path d="{path_d(prings)}" fill="{VIS_FILL}" '
                         f'fill-opacity="{VIS_FILL_OP}" stroke="{VIS_STROKE}" '
                         f'stroke-opacity="{VIS_STROKE_OP}" stroke-width="{SW}"/>')
    # Visited-point markers: one per KML placemark, projected through Equal Earth.
    if args.dots:
        for lon, lat in pts:
            x, y = equal_earth(lon, lat)
            cx, cy = (x - minx), (maxy - y)
            if halo:
                lines.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{halo_r:.4f}" '
                             f'fill="{halo[0]}" fill-opacity="{HALO_OP}"/>')
            lines.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{dot_r}" '
                         f'fill="{MARK_FILL}" fill-opacity="{MARK_FILL_OP}"/>')
            if ring:
                # true 1px outline at any zoom; sits just outside the dot
                lines.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{ring_r:.4f}" '
                             f'fill="none" stroke="{ring[0]}" stroke-opacity="{RING_OP}" '
                             f'stroke-width="1" vector-effect="non-scaling-stroke"/>')
    if args.labels:
        for ax, ay, lx, ly, rank, name in LABELS:
            lcx, lcy = (lx - minx), (maxy - ly)
            if args.label_leaders and (abs(lx - ax) > 1e-6 or abs(ly - ay) > 1e-6):
                acx, acy = (ax - minx), (maxy - ay)
                lines.append(
                    f'<line x1="{acx:.3f}" y1="{acy:.3f}" x2="{lcx:.3f}" y2="{lcy:.3f}" '
                    f'stroke="{LFILL}" stroke-opacity="{LEADER_OP}" stroke-width="1" '
                    f'vector-effect="non-scaling-stroke"/>')
            lines.append(
                f'<text class="label lr{rank}" x="{lcx:.3f}" y="{lcy:.3f}" '
                f'font-size="{LSIZE}" fill="{LFILL}" fill-opacity="{LFILL_OP}" '
                f'stroke="{LHALO}" stroke-width="{LSIZE * 0.30:.4f}" '
                f'stroke-opacity="{LHALO_OP}" paint-order="stroke" '
                f'text-anchor="middle" dominant-baseline="central">'
                f'{html.escape(name)}</text>')
    lines.append('</g></svg>')
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}  ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
