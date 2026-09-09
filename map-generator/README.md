# map-generator

Produces `img/map-bg-adventure.svg` — the Equal-Earth world map embedded in
`index.html`: visited countries and US states tinted, one dot per visited
city, and the city names in two legend columns flanking the map, each tied to
its dot by a 1px leader line. Cities left of the map's midline label in
the left column, the rest in the right one, so no leader line ever crosses
the midline. Within a column, labels are tangent-ordered — each slot, top
to bottom, takes the topmost remaining dot whose leader line leaves every
other remaining dot below it — so leaders on the same side never cross
either. The generator counts crossings itself and warns if a future dataset
ever breaks the invariant.

## One-click update

```sh
./map-generator/update-map.sh
```

That's it. It re-renders the live site map from the cached KML and boundary
data already in `map-data/`. No arguments, no network, no extra setup.

After it runs, commit the result:

```sh
git add img/map-bg-adventure.svg
git commit -m "chore(map): regenerate map background"
git push origin static-map
```

## Prerequisites — already in place

Everything the generator needs is checked into this directory, so the
one-click works offline out of the box:

| Input | Location | Refresh when |
|---|---|---|
| Visited points (KML export from Google My Maps) | `map-data/map.kml` | the master map changes — re-export and overwrite this file |
| Natural Earth country boundaries (cached) | `map-data/ne_110m_countries.geojson` | rarely; delete to force a re-download |
| Natural Earth US-state boundaries (cached) | `map-data/ne_110m_states.geojson` | rarely; delete to force a re-download |
| Natural Earth populated places (cached) | `map-data/ne_110m_populated_places_simple.geojson` | rarely; delete to force a re-download |
| City label overrides (optional, human-edited) | `map-data/label-overrides.json` | whenever a generated label reads wrong |

The only manual step in the whole flow is re-exporting `map-data/map.kml` from
Google My Maps when you add a new destination. `update-map.sh` then handles
the rest.

## How city labels are chosen

1. Visited points closer than `--cluster-km` (100 km live) merge into one
   city dot. The visited-region tints still use every original point.
2. A cluster is named after the biggest Natural Earth populated place within
   40 km of any member point, so a guesthouse outside Prague still reads
   "Prague" and six Camino stages collapse to one dot.
3. If no such city exists (resorts, rural places), the member names are
   cleaned ("Sámara, Costa Rica" -> "Sámara") and the most common name wins;
   ties go to the shortest.
4. `label-overrides.json` has the final say. It can rename raw KML names
   (keys match with any whitespace, so plain spaces are fine) and even
   Natural Earth city names (`"København": "Copenhagen"`). Plain JSON, one
   line per rename; a syntax error stops the run with the exact problem.

## Colours and sizes

All colours and line weights are emitted as CSS custom properties on `:root`
in one `<style>` block at the top of the SVG. Edit the block in the SVG for a
one-off look, or edit `PALETTES` / the `STROKE_*` constants in the script and
re-run to change future renders (a re-render overwrites manual SVG edits).

Colours: `--land`, `--coast`, `--state`, `--visited`, `--visited-edge`,
`--dot`, `--dot-ring`, `--label`, `--leader`.
Sizes (CSS px, rendered non-scaling): `--stroke-coast`, `--stroke-state`,
`--stroke-visited`, `--stroke-leader`, `--stroke-ring`.

The dot and ring radii deliberately stay numeric in the generator (the
palette's marker `r` or `--dot-size`): geometry attributes like `r` are not
CSS-cascaded in every engine (`var()` in `r` silently drops the dots in
Firefox), unlike colours and stroke widths. The same applies to the legend
font size, row pitch, and column widths, which define the canvas geometry;
they live as named constants (`LEGEND_*`, `FONT_MAX_DIV`, `H_CAP_FACTOR`)
at the top of `generate_map_bg.py`.

## Responsive behaviour (one file, two layouts)

Below `--legend-breakpoint` (700px of the rendered image width) a media
query inside the SVG hides the legend columns and leader lines and scales
the map strip to the full canvas width, so phones see the bare strip,
centred, filling the image. The SVG scales with `preserveAspectRatio="meet"`:
opening it full-size fits the window, letterboxed, never cropping labels.
On the site the figure simply fills the content column (50rem); the label
font is sized for that width. Keep the `width`/`height` attributes on the
`<img>` in `index.html` in sync with the generated canvas aspect.

## What it runs

`update-map.sh` is a thin wrapper around the exact command that produces the
current live map; the flags (and only the flags) live in its `LIVE_FLAGS`:

```sh
python3 map-generator/generate_map_bg.py \
    --palette adventure \
    --visited-opacity 0.3 --land-opacity 0.2 \
    --dot-opacity 1 \
    --crop-visited \
    --cluster-km 100
```

See `python3 map-generator/generate_map_bg.py --help` for every knob
(clustering, legend breakpoint, overrides path, `--no-legend`, dot sizing,
opacities, padding).

## Files

```
map-generator/
├── generate_map_bg.py     # the renderer (Python 3.10+, stdlib only)
├── update-map.sh          # one-click wrapper -> img/map-bg-adventure.svg
└── map-data/
    ├── map.kml                       # visited points (Google My Maps export)
    ├── label-overrides.json          # optional label renames (human-edited)
    ├── ne_110m_countries.geojson     # cached country boundaries
    ├── ne_110m_states.geojson        # cached US-state boundaries
    └── ne_110m_populated_places_simple.geojson  # cached city names/populations
```
