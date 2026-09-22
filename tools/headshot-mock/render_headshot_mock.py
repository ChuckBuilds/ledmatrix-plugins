#!/usr/bin/env python3
"""Render the NFL stat ticker with REAL ESPN headshots, for a look-and-see.

Run this anywhere with internet (your Pi, your laptop). It fetches the live
leaders feed, downloads each leader's ESPN headshot cutout, and renders the
same row three ways at four panel sizes:

    1. club crest            -- what the plugin ships today
    2. headshot only         -- crest replaced by the player
    3. headshot + small crest

    python3 render_headshot_mock.py \
        --core   ~/LEDMatrix \
        --plugin ~/ledmatrix-plugins/plugins/nfl-stat-leaders \
        --out    /tmp/headshot-mock

Nothing here touches the plugin: it subclasses the shipped renderer, so the
fonts, bands, badge and spacing are the real ones. Headshots are cached under
<out>/headshots so a re-run is instant.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PORTRAIT_ASPECT = 0.80          # width / height of a head-and-shoulders cutout
HEADSHOT_URL = ("https://a.espncdn.com/combiner/i?img=/i/headshots/nfl/"
                "players/full/{athlete_id}.png&w=350&h=254")
SIZES = ((64, 32, 8), (128, 32, 6), (128, 64, 6), (256, 64, 4))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--core", required=True, type=Path,
                   help="LEDMatrix core checkout (for fonts and club crests)")
    p.add_argument("--plugin", required=True, type=Path,
                   help="the nfl-stat-leaders plugin directory")
    p.add_argument("--out", default=Path("/tmp/headshot-mock"), type=Path)
    p.add_argument("--season", type=int, default=0, help="0 = current season")
    p.add_argument("--players", type=int, default=3)
    return p.parse_args()


args = parse_args()
sys.path.insert(0, str(args.plugin.resolve()))
sys.path.insert(0, str(args.core.resolve()))

import src  # noqa: E402
import requests  # noqa: E402

# Importing the core package is what lets the renderer resolve its crest and
# font assets; the reference keeps linters from calling the import unused.
_CORE_ROOT = Path(src.__file__).resolve().parent.parent
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import nfl_stat_renderer as R  # noqa: E402
from nfl_stat_fetcher import StatFetcher, current_season_year  # noqa: E402
from nfl_stat_categories import CATEGORIES  # noqa: E402


class MemoryCache:
    """The two methods StatFetcher needs, backed by a dict."""

    def __init__(self) -> None:
        self.data: dict = {}

    def get(self, key, max_age=None):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


def athlete_ids(payload) -> dict:
    """Map each leader's drawn name to their ESPN athlete id.

    The plugin's own LeaderEntry does not keep the id -- it never needs one,
    because club crests come off the disk -- so read it back off the raw
    payload rather than widening the plugin for a one-off render.
    """
    ids = {}
    for category in (payload or {}).get("categories") or []:
        for item in category.get("leaders") or []:
            athlete = item.get("athlete")
            if not isinstance(athlete, dict):
                continue
            name = ""
            for field in ("shortName", "displayName", "fullName", "name"):
                value = athlete.get(field)
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    break
            athlete_id = athlete.get("id")
            if name and athlete_id:
                ids.setdefault(name, str(athlete_id))
    return ids


def headshot(athlete_id: str, cache_dir: Path):
    """The player's ESPN cutout, downloaded once and cached on disk."""
    if not athlete_id:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{athlete_id}.png"
    if not path.exists():
        url = HEADSHOT_URL.format(athlete_id=athlete_id)
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            path.write_bytes(response.content)
        except Exception as exc:  # noqa: BLE001 - a missing face is not fatal
            print(f"  no headshot for {athlete_id}: {exc}")
            return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable headshot {path}: {exc}")
        return None


class HeadshotRenderer(R.TickerRenderer):
    """The shipped renderer with the crest slot given over to a portrait."""

    def __init__(self, *a, faces=None, keep_crest: bool = False, **kw):
        super().__init__(*a, **kw)
        self.faces = faces or {}
        self.keep_crest = keep_crest

    def _portrait_size(self):
        height = max(10, self.display_height - 2 * self.pad_y)
        return max(8, int(height * PORTRAIT_ASPECT)), height

    def _portrait(self, name, box):
        art = self.faces.get(name)
        if art is None:
            return None
        box_w, box_h = box
        art = art.crop(art.getbbox()) if art.getbbox() else art
        scale = min(box_w / art.width, box_h / art.height)
        art = art.resize((max(1, int(art.width * scale)),
                          max(1, int(art.height * scale))), R.RESAMPLE_FILTER)
        if self.crisp_logos:
            r, g, b, alpha = art.split()
            art = Image.merge("RGBA", (r, g, b,
                                       alpha.point(lambda p: 255 if p >= 128 else 0)))
        return art

    def _entry_plan(self, leader):
        plan = super()._entry_plan(leader)
        portrait_w, portrait_h = self._portrait_size()
        crest = plan["logo_box"] // 2 if self.keep_crest else 0
        plan["width"] += portrait_w - plan["logo_box"]
        if crest:
            plan["width"] += crest + self._gap(R.LOGO_GAP)
        plan["portrait"] = (portrait_w, portrait_h)
        plan["crest_box"] = crest
        return plan

    def _draw_entry(self, strip, draw, x, plan):
        badge_w, badge_h = plan["badge"]
        rank_text = plan["rank_text"]
        accent = self.team_accent(plan["team"])

        badge_color = accent
        if self.highlight_top_three:
            try:
                rank = int(rank_text)
            except (TypeError, ValueError):
                rank = 0
            if 1 <= rank <= len(R.MEDAL_COLORS):
                badge_color = R.MEDAL_COLORS[rank - 1]
        badge_top = (self.display_height - badge_h) // 2
        draw.rectangle([x, badge_top, x + badge_w - 1, badge_top + badge_h - 1],
                       fill=badge_color)
        rank_x = x + (badge_w - self._advance(rank_text, self.font_small)) // 2
        draw.text((rank_x, self._baseline_y(rank_text, self.font_small,
                                            badge_top, badge_h)),
                  rank_text, font=self.font_small, fill=R._readable_on(badge_color))

        cursor = x + badge_w + self._gap(R.BADGE_GAP)
        portrait_w, portrait_h = plan["portrait"]
        art = self._portrait(plan["name"], (portrait_w, portrait_h))
        if art is not None:
            strip.paste(art, (cursor + (portrait_w - art.width) // 2,
                              self.display_height - self.pad_y - art.height), art)
        cursor += portrait_w + self._gap(R.LOGO_GAP)

        if plan["crest_box"]:
            box = plan["crest_box"]
            crest = self._logo(plan["team"], box, box)
            if crest is not None:
                strip.paste(crest, (cursor + (box - crest.width) // 2,
                                    (self.display_height - crest.height) // 2), crest)
            cursor += box + self._gap(R.LOGO_GAP)

        bands = plan["bands"]
        if self.three_band:
            rows = ((plan["name"], self.font_primary, R.WHITE),
                    (plan["value"], self.font_primary, accent),
                    (plan["meta"], self.font_small, R.DIM))
            for (text, font, colour), (band_top, band_h) in zip(rows, bands):
                self._draw_text(draw, text, cursor,
                                self._baseline_y(text, font, band_top, band_h),
                                font, colour)
            return

        name_top, name_h = bands[0]
        self._draw_text(draw, plan["name"], cursor,
                        self._baseline_y(plan["name"], self.font_primary,
                                         name_top, name_h),
                        self.font_primary, R.WHITE)
        value_top, value_h = bands[1]
        self._draw_text(draw, plan["value"], cursor,
                        self._baseline_y(plan["value"], self.font_primary,
                                         value_top, value_h),
                        self.font_primary, accent)
        if plan["meta"]:
            meta_x = (cursor + self._advance(plan["value"], self.font_primary)
                      + self._gap(R.META_GAP))
            self._draw_text(draw, plan["meta"], meta_x,
                            self._baseline_y(plan["meta"], self.font_small,
                                             value_top, value_h),
                            self.font_small, R.DIM)


def label_font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/Library/Fonts/Arial.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def first_entry_x(renderer, boards) -> int:
    """Where the first leaderboard row starts, so the window lands on a row."""
    x = renderer._card_plan("STAT LEADERS", "LEADERS", "season")["width"]
    x += renderer._card_plan(str(boards[0]["title"]),
                             str(boards[0]["short_title"]), "")["width"]
    return x


def main() -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    fetcher = StatFetcher(MemoryCache())
    season = args.season or current_season_year()
    categories = [c for c in CATEGORIES if c.default_enabled][:2]

    print(f"fetching leaders for {season}...")
    boards = fetcher.fetch_boards(categories, season, 2, args.players, max_age=0)
    if not boards:
        print("no leaders came back -- is ESPN reachable from here?")
        return 1

    # The cache the fetcher just filled still holds the raw payload, so this
    # reads the athlete ids back without asking ESPN a second time.
    ids = athlete_ids((fetcher._get_payload(season, 2, max_age=10 ** 9) or {}))

    print("downloading headshots...")
    faces = {}
    for board in boards:
        for leader in board["leaders"]:
            name = str(leader.get("name", ""))
            art = headshot(ids.get(name, ""), args.out / "headshots")
            if art is not None:
                faces[name] = art
    print(f"  {len(faces)} of {sum(len(b['leaders']) for b in boards)} headshot(s)")
    if not faces:
        print("  no headshots downloaded -- the renders below will show the "
              "crest layout with an empty slot")

    rows = (("Now: club crest", R.TickerRenderer, {}),
            ("Headshot instead of the crest", HeadshotRenderer, {"faces": faces}),
            ("Headshot + small crest",
             HeadshotRenderer, {"faces": faces, "keep_crest": True}))

    for panel_w, panel_h, zoom in SIZES:
        tiles = []
        for title, cls, kw in rows:
            renderer = cls(panel_h, appearance={"show_league_logo": False}, **kw)
            strip = renderer.build_strip(boards, str(season))
            offset = first_entry_x(renderer, boards)
            window = Image.new("RGB", (panel_w, panel_h), (0, 0, 0))
            window.paste(strip.crop((offset, 0, min(offset + panel_w, strip.width),
                                     strip.height)), (0, 0))
            tiles.append((title, window.resize((panel_w * zoom, panel_h * zoom),
                                               Image.Resampling.NEAREST)))

        pad, gap, label_h = 24, 18, 30
        width = panel_w * zoom + 2 * pad
        height = pad + sum(label_h + t.height + gap for _n, t in tiles) + 24
        canvas = Image.new("RGB", (width, height), (18, 18, 20))
        draw = ImageDraw.Draw(canvas)
        draw.text((pad, 6), f"{panel_w}x{panel_h} panel, shown at {zoom}x",
                  font=label_font(17), fill=(150, 150, 158))
        y = pad + 14
        for title, tile in tiles:
            draw.text((pad, y), title, font=label_font(20), fill=(235, 235, 240))
            y += label_h
            canvas.paste(tile, (pad, y))
            draw.rectangle([pad - 1, y - 1, pad + tile.width, y + tile.height],
                           outline=(60, 60, 66))
            y += tile.height + gap
        out = args.out / f"headshots-{panel_w}x{panel_h}.png"
        canvas.save(out)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
