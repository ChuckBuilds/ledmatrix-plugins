#!/usr/bin/env python3
"""
The readout is a timezone list: one "LABEL  time" row per zone.

1. Cities get short uniform labels (initials or three letters, or an explicit
   label), so the times line up in a column.
2. The local zone comes first; a city in the same zone folds into that row
   rather than repeating it.
3. No coordinates or seconds: they crowded out the city times.
4. More zones than rows: the local row stays pinned and the cities page
   evenly (4 + 3, not 6 + 1), driven by the clock.
5. The sidebar widens to fit the list, never past half the panel.
6. The date heads the list when there is a row to spare, and the midnight
   line sits where the date turns over, sweeping west 15 degrees an hour.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import pytz
    import geochron_renderer as gr
except ImportError as exc:
    print(f"SKIP: renderer dependencies not importable: {exc}")
    sys.exit(2)

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


NOW = datetime(2025, 8, 1, 15, 25, 0, tzinfo=timezone.utc)
CITIES = [
    ("New York", "America/New_York"), ("Los Angeles", "America/Los_Angeles"),
    ("Rio de Janeiro", "America/Sao_Paulo"), ("London", "Europe/London"),
    ("Cairo", "Africa/Cairo"), ("Moscow", "Europe/Moscow"),
    ("Tokyo", "Asia/Tokyo"), ("Sydney", "Australia/Sydney"),
]


def cities(names=None):
    out = []
    for name, tz in CITIES:
        if names is None or name in names:
            out.append({"label": gr.city_label({"name": name}),
                        "local_dt": NOW.astimezone(pytz.timezone(tz)), "tz": tz})
    return out


def measure(text):
    return len(text) * 5  # the 4x6 face at 7px advances 5px per glyph


def main():
    print("labels")
    check("multi-word names use initials",
          [gr.city_label({"name": n}) for n in ("New York", "Los Angeles", "Rio de Janeiro")]
          == ["NY", "LA", "RJ"])
    check("single words use three letters", gr.city_label({"name": "Tokyo"}) == "TOK")
    check("an explicit label wins, capped at 4", gr.city_label({"name": "New York", "label": "nycx1"}) == "NYCX")
    check("the local zone is labelled from its name", gr.tz_label("America/Chicago") == "CHI")
    check("UTC stays UTC", gr.tz_label("UTC") == "UTC")

    print("zones")
    ny = pytz.timezone("America/New_York")
    zones = gr.build_zones(NOW.astimezone(ny), "America/New_York",
                           cities({"New York", "London"}), "12h")
    check("a city in the local zone folds into the local row",
          zones == [("NY", "11:25AM", True), ("LON", "4:25PM", False)])
    check("times carry no seconds", all(t.count(":") == 1 for _, t, _ in zones))

    wide = gr._layout(256, 64, sidebar_w=gr.sidebar_width(measure, "12h"))
    readout = gr.build_readout(wide, NOW, zones)
    texts = [label + t for label, t, _, _ in readout["rows"]]
    check("no coordinates in the zone rows",
          not any("," in t or "-" in t for t in texts))

    print("paging")
    all_zones = gr.build_zones(NOW.astimezone(ny), "America/New_York", cities(), "24h")
    pages = []
    for step in range(2):
        r = gr.build_readout(wide, NOW + timedelta(seconds=gr.PAGE_SECONDS * step), all_zones)
        pages.append([label for label, _, _, _ in r["rows"]])
    check("the local row is pinned on every page", all(p[0] == "NY" for p in pages))
    check("pages split evenly", sorted(len(p) - 1 for p in pages) == [3, 4])
    check("every city appears across the pages",
          sorted(sum((p[1:] for p in pages), [])) == sorted(z[0] for z in all_zones[1:]))
    rows = gr.build_readout(wide, NOW, all_zones)["rows"]
    check("rows stay inside the panel", all(0 <= y and y + gr.ROW_H <= 64 for *_, y in rows))

    print("sidebar width")
    check("12h needs a wider sidebar than 24h",
          gr.sidebar_width(measure, "12h") > gr.sidebar_width(measure, "24h"))
    check("the sidebar never takes more than half the panel",
          gr._layout(128, 32, sidebar_w=500)["sidebar_w"] == 64)
    check("default layout is unchanged without a width", gr._layout(256, 64)["sidebar_w"] == 56)
    no_clock = gr._layout(256, 64, sidebar_w=0)
    check("with the clock off the map takes the full width",
          no_clock["sidebar_w"] == 0 and no_clock["map_w"] == 256)

    print("date")
    local = NOW.astimezone(ny)
    check("the longest date form that fits is used",
          gr.sidebar_date(local, measure, 55) == "FRI AUG 1")
    check("a narrow sidebar falls back to a shorter form",
          gr.sidebar_date(local, measure, 40) == "FRI 8/1")
    r = gr.build_readout(wide, NOW, zones, date_text="FRI AUG 1")
    check("the date heads the list, above the first zone",
          r["header"][0] == "FRI AUG 1" and r["header"][1] < r["rows"][0][3])
    short = gr._layout(128, 16, sidebar_w=gr.sidebar_width(measure, "12h"))
    r = gr.build_readout(short, NOW, zones, date_text="FRI AUG 1")
    check("with room for one row the time wins over the date",
          r["header"] is None and len(r["rows"]) == 1)
    check("midnight is at the prime meridian at 00:00 UTC",
          gr.midnight_longitude(NOW.replace(hour=0, minute=0)) == 0.0)
    check("it sweeps west 15 degrees an hour",
          gr.midnight_longitude(NOW.replace(hour=6, minute=0)) == -90.0)
    check("at 15:25 UTC it sits at 128.75E, just west of Tokyo",
          gr.midnight_longitude(NOW) == 128.75)

    print(f"\n{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
