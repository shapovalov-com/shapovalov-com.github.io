# Shapovalov Family Travel Site

A single-page static site: a world map of visited regions plus a year-by-year
log of family trips. Each trip is a small card that links out to a YouTube
video, a Google Photos gallery, and sometimes a Google My Maps map. Content
lives in one file, `index.html`. Hosted on GitHub Pages at `shapovalov.com`.

## Hard constraints

Non-negotiable. Every change to this repo must respect all four:

1. **Static site.** `index.html` plus assets is the whole site. No build step,
   no bundler, no templating, no runtime dependencies. What you commit is what
   gets served.
2. **No server.** Everything runs in the browser from plain files. The only
   scripts in the repo are offline Python helpers (map, thumbnails); they
   never run at request time.
3. **Publishing is copy-paste.** Adding a trip means copying an existing
   `<article>` in `index.html`, changing the text and links, and pushing. If a
   proposed change makes this harder (new required fields, a generator,
   preprocessed markup), the change is wrong. See "Publishing a new trip".
4. **bare-ui principles always apply.** See the next section.

## Styling: bare-ui

The site is styled by bare-ui, a classless stylesheet system built on semantic
HTML5. Its self-description: warm paper, ink accent, flat borders, native
controls. No classes. No components. No JavaScript.

Three stylesheets, linked in this order in `index.html`:

| Order | File | Role | May you edit it? |
|---|---|---|---|
| 1 | `theme.css` | The knobs. Every visible value: colors, type scale, spacing, shadows, radii, layout | Yes. Reskinning happens here |
| 2 | `bare.css` | The engine. Wires theme variables to elements. Vendored and shared | Never for this site |
| 3 | `site.css` | Site-local overrides, linked last (the override contract: the last sheet wins at equal specificity) | Yes. All site-specific CSS goes here |

### Rules that must hold

- **Semantic HTML5 only.** The engine styles elements, not classes. `body >
  header`, `body > nav`, `main > section`, `article`, `figure`, `time`,
  `small`, `strong` are the styling hooks. Do not add `div`/`span` scaffolding
  or class attributes to solve layout problems. There are no class attributes
  anywhere in `index.html`; IDs (`#trips`, `#y2025`) are anchors and scoping
  hooks only.
- **bare.css is untouchable.** Treat it as upstream. Site needs go in
  `site.css`, scoped with element selectors under an ID (`#trips article`,
  `#map figure`), reusing existing tokens (`--s-*`, `--r`, `--border`,
  `--surface`, `--shadow-*`). Never hardcode a value that a token already
  provides.
- **No JavaScript.** The only script on the page is the Google Analytics
  snippet in `index.html`, which is intentional. Do not add more. (Removing the
  two GA tags is the documented way to go tracker-free.)
- **Closed vocabularies.** Shadows: exactly four tokens (`--shadow-raised`,
  `--shadow-recessed`, `--shadow-bevel`, `--shadow-drawer`). No fifth token, no
  ad-hoc `box-shadow`; adding a shadow anywhere new requires explicit approval.
  Status colors: `ok` / `caution` / `warning` / `info` only, via
  `<data value="...">`, never decorative. Opt-in behaviors ship behind the
  `--extras` flag in `theme.css` (currently `off`).
- **Dark mode is two buckets in one file.** Light and dark values both live in
  `theme.css`; never drop or duplicate the `@media (prefers-color-scheme:
  dark)` wrapper or a light value leaks into dark mode.
- **Breakpoint discipline.** 48rem is the shared nav-wrap breakpoint. The
  `--header-h` media query in `theme.css` must match the nav rules in
  `bare.css` or anchors drift under the sticky nav.
- **Native controls.** No custom widgets, no shadow on native controls
  (checkbox/radio/range/file).
- **Accessibility ships with the engine.** Skip link, `:focus-visible`,
  reduced-motion, and print styles come from `bare.css`. Do not override them.

### In practice, when adding content

Use the semantic elements the engine already styles. Copy an existing block
and keep its structure. No inline styles. If a genuinely new pattern is
needed, extend `site.css` with an ID-scoped element selector built from
existing tokens.

## Publishing a new trip

Copy, paste, edit, push. The whole recipe:

1. Open `index.html` and find the year heading, e.g. `<h3 id="y2025">2025</h3>`.
   Years run newest-first; within a year, newest month first. Paste the new
   `<article>` at the top of its year.
2. Copy a recent `<article>` and edit it. Full form:

```html
<article>
  <img src="img/video-thumbnails/destination-2025-06.jpg" alt="Destination, Month 2025" width="480" height="270" loading="lazy">
  <p><strong>Destination</strong>, <time datetime="2025-06">June</time></p>
  <p><small>Optional one-line note.</small></p>
  <ul><li><a href="https://youtu.be/VIDEO_ID" target="_blank" rel="noopener">Video</a></li><li><a href="https://photos.app.goo.gl/GALLERY_ID" target="_blank" rel="noopener">Gallery</a></li><li><a href="https://www.google.com/maps/d/viewer?mid=MAP_ID" target="_blank" rel="noopener">Map</a></li></ul>
</article>
```

3. Know the optional parts:
   - The `<img>` line: only when a thumbnail exists. Drop the whole line
     otherwise (many older trips have none).
   - The `<p><small>...` note: only for trips that need a one-liner. Keep it
     short.
   - The links `<ul>`: include only the links that exist, in the order Video,
     Gallery, Map. A gallery-only trip is fine (most pre-2021 trips are that).
   - "New" badge: append ` <small>new</small>` inside the title paragraph,
     after `</time>`. Remove it when the next trip lands.
4. Escape `&` as `&amp;` in names (see "Costa Rica &amp; Nicaragua").
5. External links always carry `target="_blank" rel="noopener"`.
6. Recurring destinations reuse their shared map URL. All Iceland trips point
   at the same `mid=12cQOh...` map.
7. Commit (Conventional Commits, e.g. `feat: add Oregon trip`) and push to the
   deploy branch. Deployment is automatic; see below.

Nothing else needs touching: the page `<title>` and meta description are
generic and stay as they are.

### Adding a new year

When a trip falls in a year that has no section yet:

1. Add `<h3 id="y2027">2027</h3>` as the first year heading inside
   `#trips` (years descend).
2. Add `<li><a href="#y2027">2027</a></li>` in the `<nav>` as the first year
   link, right after the Map entry.

### Thumbnails

- Live in `img/video-thumbnails/`, named `<slug>-<YYYY-MM>.jpg`, where slug is
  the destination lowercased with non-alphanumerics as hyphens:
  `iceland-2025-11.jpg`, `faroe-islands-2023-07.jpg`,
  `xcaret-mexico-2023-12.jpg`.
- 480x270 JPEG (16:9). Keep the explicit `width`/`height` attributes and
  `loading="lazy"`; they prevent layout shift.
- To get one: fetch `https://img.youtube.com/vi/<video-id>/maxresdefault.jpg`
  (fall back to `hqdefault.jpg`), resize/crop to 480x270, save under the right
  name. `video-meta/fetch_thumbnails.py` automates this but is currently stale;
  see Known caveats.

## The map

The map embedded on the page, `img/map-bg-adventure.svg`, is generated offline
by `map-generator/`:

- Factual input: `map-generator/map-data/map.kml`, an export of visited
  points from the master Google My Maps map.
- The script classifies each point into a country or US state via
  point-in-polygon against cached Natural Earth 1:110m boundaries, then tints
  visited regions.
- Layout: [left legend][map][right legend]. Points within 100 km merge into
  one city dot; each city gets a label in a flanking legend column, tied to
  its dot by a 1px leader line. Cities left of the map's midline label in
  the left column, the rest in the right one, so no leader crosses the
  midline; within a column a tangent ordering keeps same-side leaders
  from crossing (the generator verifies this on every run). Clusters are
  named after the biggest
  Natural Earth populated place within 40 km (a guesthouse outside Prague
  reads "Prague"); manual renames live in `map-data/label-overrides.json`
  (plain JSON, whitespace-insensitive keys, can rename even the city names).
- Colours and line weights are CSS custom properties on `:root` inside the
  SVG (`--land`, `--coast`, `--visited`, `--dot`, `--label`, `--stroke-*`,
  ...): one block to restyle; the generator-side defaults live in
  `PALETTES` and the `STROKE_*` constants. Marker radii and legend
  font/pitch stay generator-side (see the map-generator README).
- One file, two layouts: below 700px image width an internal media query
  hides the legend columns and scales the map strip to the full canvas
  width (phones see the bare strip, centred, filling the image width).
  The SVG scales with "meet", so opening it full-size fits the window
  without ever cropping labels. The figure fills the content column like
  every other figure; the `<img>` takes its aspect ratio from the SVG's
  viewBox (no dimensions hardcoded in `index.html`).
- Workflow after visiting somewhere new: re-export the KML from Google My Maps
  over `map-data/map.kml`, run `./map-generator/update-map.sh`, commit the
  regenerated `img/map-bg-adventure.svg`.
- Render flags live in `update-map.sh` (`LIVE_FLAGS`); edit there and re-run.
  Details in `map-generator/README.md`.

## Deployment

- `.github/workflows/static.yml` deploys on every push to the default branch.
  There is no build step: the workflow uploads the repo as-is to GitHub Pages.
- The `CNAME` file pins the custom domain `shapovalov.com`.
- Use explicit `git push origin <branch>` syntax, never implicit `git push`.

## Repo layout

| Path | What it is |
|---|---|
| `index.html` | The entire site: header, year nav, map, trip cards, footer |
| `theme.css`, `bare.css`, `site.css` | The bare-ui stack; see Styling |
| `img/video-thumbnails/` | 480x270 JPEG thumbnails, one per trip with a video |
| `img/map-bg-adventure.svg` | The generated visited-world map |
| `map-generator/` | Offline map renderer + data (`update-map.sh`) |
| `video-meta/` | Offline YouTube thumbnail fetcher (stale; see caveats) |
| `fonts/` | Exo 2 (SIL OFL 1.1, see `fonts/OFL.txt`); used only for the header title and tagline via `site.css` |
| `avatar.png` | YouTube channel avatar, linked from the footer |
| `CNAME` | Custom domain: shapovalov.com |
| `.github/workflows/static.yml` | Pages deployment |
| `favicon*`, `apple-touch-icon.png`, `android-chrome-*`, `site.webmanifest` | Icons and PWA manifest |

## Known caveats

- `video-meta/fetch_thumbnails.py` still parses the pre-redesign table markup
  (`<tr>` / `<th scope="row">`). Against the current `<article>` markup it
  finds zero trips, so it does nothing until it is updated to read articles.
  Fetch thumbnails manually until then.
- `site.webmanifest` hardcodes white `theme_color` / `background_color`, which
  does not match the paper palette in dark mode.
- Opening the map SVG full-screen scales it to fit the window (letterboxed,
  never cropped); the responsive legend layout targets the embedded `<img>`.

## Conventions

- Conventional Commits 1.0.0; scope recommended for multi-component changes.
- LF line endings, final newline on all files.
- Keep this file current: after any commit that changes architecture,
  conventions, or structure, update `PROJECT.md` to match. `AGENTS.md` covers
  agent workflow (commits, pushes, writing voice) and points here for the
  architecture.
