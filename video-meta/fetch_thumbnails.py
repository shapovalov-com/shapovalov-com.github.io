#!/usr/bin/env python3
"""Fetch YouTube thumbnails for every trip video listed in index.html.

- Single videos (youtu.be/<id>): fetch maxresdefault.jpg, fall back to hqdefault.jpg.
- Playlists (youtube.com/playlist?list=...): fetch the playlist page and read its
  og:image meta tag.

Gentle: one HTTP request per item, a descriptive User-Agent, short sleeps between
requests, and clear skip-on-existing so re-runs are cheap and non-abusive.
"""

import html
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML_FILE = REPO / "index.html"
OUT_DIR = REPO / "img" / "video-thumbnails"

USER_AGENT = "shapovalov-thumbs/1.0 (personal site; fetching public YouTube thumbnails)"
SLEEP = 0.6  # seconds between requests


def slugify(text: str) -> str:
    text = html.unescape(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "trip"


def parse_rows(markup: str):
    """Yield (trip_label, date, video_url) for every trip row that has a video."""
    # Each trip is a <tr> ... </tr>; the row header holds name + <time datetime>.
    for row in re.finditer(r"<tr>(.*?)</tr>", markup, re.S | re.I):
        body = row.group(1)
        if "youtu.be/" not in body and "youtube.com/playlist" not in body:
            continue

        # Trip name = text of the first <a> inside the <th scope="row">.
        th = re.search(r'<th[^>]*scope="row"[^>]*>(.*?)</th>', body, re.S | re.I)
        name = "trip"
        if th:
            header = th.group(1)
            # Prefer the album-link text; otherwise the leading text before <small>.
            header_name = re.split(r"<small\b", header, maxsplit=1, flags=re.I)[0]
            a = re.search(r"<a[^>]*>(.*?)</a>", header_name, re.S | re.I)
            name = slugify(re.sub(r"<.*?>", " ", a.group(1) if a else header_name))

        # Date from <time datetime="...">.
        date_m = re.search(r'<time[^>]*datetime="([^"]+)"', body, re.I)
        date = date_m.group(1) if date_m else "nodate"

        # Video link: youtu.be/<id> or youtube.com/playlist?list=...
        vid_m = re.search(r'href="(https?://(?:youtu\.be/[A-Za-z0-9_-]+|youtube\.com/playlist\?list=[A-Za-z0-9_-]+))"', body, re.I)
        if not vid_m:
            continue

        yield name, date, vid_m.group(1)


def fetch(url: str, *, timeout: int = 20) -> tuple[int, bytes | str | None, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return resp.status, data, resp.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except Exception as e:  # noqa: BLE001
        return 0, str(e), None


def download_single(video_url: str, dest: Path) -> str:
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]+)", video_url)
    if not m:
        return f"  ? not a single video: {video_url}"
    vid = m.group(1)
    for thumb in (f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg",
                  f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"):
        status, data, ctype = fetch(thumb)
        if status == 200 and isinstance(data, (bytes, bytearray)) and len(data) > 1024:
            dest.write_bytes(data)
            which = thumb.rsplit("/", 1)[-1]
            return f"  + {dest.name}  ({len(data)} bytes, {which})"
        time.sleep(SLEEP)
    return f"  ! failed to fetch thumbnail for {vid} (last status {status})"


def download_playlist(playlist_url: str, dest: Path) -> str:
    status, data, ctype = fetch(playlist_url)
    if status != 200 or not isinstance(data, (bytes, bytearray)):
        return f"  ! playlist page fetch failed (status {status})"
    text = data.decode("utf-8", "replace")
    og = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', text, re.I)
    if not og:
        # Some pages use a different attribute order.
        og = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', text, re.I)
    if not og:
        return f"  ! no og:image found on {playlist_url}"
    img_url = html.unescape(og.group(1))
    status, idata, _ = fetch(img_url)
    if status == 200 and isinstance(idata, (bytes, bytearray)) and len(idata) > 1024:
        dest.write_bytes(idata)
        return f"  + {dest.name}  ({len(idata)} bytes, playlist banner)"
    return f"  ! og:image fetch failed (status {status}): {img_url}"


def main() -> int:
    if not HTML_FILE.exists():
        print(f"index.html not found at {HTML_FILE}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(exist_ok=True)
    markup = HTML_FILE.read_text(encoding="utf-8")

    rows = list(parse_rows(markup))
    print(f"Found {len(rows)} trip(s) with a video link.\n")

    ok = 0
    for name, date, url in rows:
        dest = OUT_DIR / f"{name}-{date}.jpg"
        print(f"- {name} ({date})")
        if dest.exists():
            print(f"  = {dest.name}  (already present, skipped)")
            ok += 1
            continue
        if "youtube.com/playlist" in url:
            msg = download_playlist(url, dest)
        else:
            msg = download_single(url, dest)
        print(msg)
        if msg.startswith("  +"):
            ok += 1
        time.sleep(SLEEP)

    print(f"\nDone. {ok}/{len(rows)} thumbnails in {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
