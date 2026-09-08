# map-generator

Produces `img/map-bg-adventure.svg` — the Equal-Earth world map with the
family's visited countries and US states tinted — that `index.html` embeds.

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
git push origin main
```

## Prerequisites — already in place

Everything the generator needs is already checked into this directory, so the
one-click works offline out of the box:

| Input | Location | Refresh when |
|---|---|---|
| Visited points (KML export from Google My Maps) | `map-data/map.kml` | the master map changes — re-export and overwrite this file |
| Natural Earth country boundaries (cached) | `map-data/ne_110m_countries.geojson` | rarely; delete to force a re-download |
| Natural Earth US-state boundaries (cached) | `map-data/ne_110m_states.geojson` | rarely; delete to force a re-download |

The only manual step in the whole flow is re-exporting `map-data/map.kml` from
Google My Maps when you add a new destination. `update-map.sh` then handles the
rest.

## What it runs

`update-map.sh` is a thin wrapper around the exact command that produces the
current live map:

```sh
python3 map-generator/generate_map_bg.py \
    --palette adventure \
    --visited-opacity 0.3 --land-opacity 0.2 \
    --dot-opacity 1 --dot-size 0.004 \
    --crop-visited --labels --label-leaders
```

The flags (and only the flags) live in `update-map.sh`'s `LIVE_FLAGS`, so to
tweak the map you edit one place and re-run. See
`python3 map-generator/generate_map_bg.py --help` for every available knob, and
the project-level [`GENERATORS.md`](../GENERATORS.md) for the full design notes
(projection, palettes, point-in-polygon + coastal rescue, label decluttering).

## Files

```
map-generator/
├── generate_map_bg.py     # the renderer (Python 3.10+, stdlib only)
├── update-map.sh          # one-click wrapper -> img/map-bg-adventure.svg
└── map-data/
    ├── map.kml                       # visited points (Google My Maps export)
    ├── ne_110m_countries.geojson     # cached country boundaries
    └── ne_110m_states.geojson        # cached US-state boundaries
```
