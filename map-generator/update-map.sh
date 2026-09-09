#!/usr/bin/env bash
# One-click map update.
#
# Re-renders img/map-bg-adventure.svg (the map embedded in index.html) from the
# cached KML and boundary data. Everything it needs already lives under
# map-generator/map-data/ — no network, no arguments.
#
# Run from anywhere:
#   ./map-generator/update-map.sh
#
# To change how the map looks, edit LIVE_FLAGS below or see
# `python3 map-generator/generate_map_bg.py --help`.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

# The exact settings that produce the current live site map. Edit here, re-run.
LIVE_FLAGS=(
    --palette adventure
    --visited-opacity 0.3
    --land-opacity 0.2
    --dot-opacity 1
    --dot-size 0.0055
    --crop-visited
    --cluster-km 100
)

python3 "$here/generate_map_bg.py" "${LIVE_FLAGS[@]}"
