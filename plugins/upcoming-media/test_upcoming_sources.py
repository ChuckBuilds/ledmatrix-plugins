"""
Parsing, window selection and text formatting for upcoming-media.

Pure functions only, fed canned payloads in the shape Sonarr v4, Radarr v5
and Jellyfin 10.10 return. Run: pytest plugins/upcoming-media/test_upcoming_sources.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upcoming_media_sources import (  # noqa: E402
    ImageStore,
    UpcomingItem,
    parse_iso,
    parse_jellyfin_upcoming,
    parse_radarr_calendar,
    parse_sonarr_calendar,
    select_items,
    short_description,
)
from upcoming_media_renderer import (  # noqa: E402
    format_episode_number,
    format_runtime,
    format_when,
    size_tier,
)

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)  # Mon 1PM in New York


def sonarr_ep(eid, series_id, title, air, season=1, number=1, runtime=None, series_runtime=45,
              images=None, has_file=False, ep_title="Pilot"):
    return {
        "id": eid, "seriesId": series_id, "seasonNumber": season, "episodeNumber": number,
        "title": ep_title, "airDateUtc": air, "runtime": runtime, "hasFile": has_file,
        "overview": "First sentence here. Second sentence.",
        "series": {"id": series_id, "title": title, "runtime": series_runtime,
                   "images": images if images is not None else [
                       {"coverType": "poster", "url": "/sonarr/MediaCover/1/poster.jpg",
                        "remoteUrl": "https://img.example/poster.jpg"},
                       {"coverType": "clearlogo", "url": "/sonarr/MediaCover/1/clearlogo.png"},
                       {"coverType": "fanart", "url": "/sonarr/MediaCover/1/fanart.jpg"},
                   ]},
    }


# -- Sonarr -----------------------------------------------------------------

def test_sonarr_runtime_prefers_episode_then_series():
    items = parse_sonarr_calendar([
        sonarr_ep(1, 1, "A", "2026-11-17T02:00:00Z", runtime=52),
        sonarr_ep(2, 2, "B", "2026-11-17T02:00:00Z", runtime=0, series_runtime=30),
    ], "http://host:8989/sonarr", "key")
    assert [i.runtime_min for i in items] == [52, 30]


def test_sonarr_images_keep_url_base_and_send_key():
    item = parse_sonarr_calendar([sonarr_ep(1, 1, "A", "2026-11-17T02:00:00Z")],
                                 "http://host:8989/sonarr", "key")[0]
    assert item.images["poster"] == "http://host:8989/sonarr/MediaCover/1/poster.jpg"
    assert item.images["logo"] == "http://host:8989/sonarr/MediaCover/1/clearlogo.png"
    assert "fanart" not in item.images
    assert item.image_headers["poster"] == {"X-Api-Key": "key"}


def test_sonarr_remote_images_when_not_preferring_local():
    item = parse_sonarr_calendar([sonarr_ep(1, 1, "A", "2026-11-17T02:00:00Z")],
                                 "http://host:8989", "key", prefer_local_images=False)[0]
    assert item.images["poster"] == "https://img.example/poster.jpg"
    assert "poster" not in item.image_headers  # no API key to a third party


def test_sonarr_tba_title_dropped_and_time_known():
    item = parse_sonarr_calendar([sonarr_ep(1, 1, "A", "2026-11-17T02:00:00Z", ep_title="TBA")],
                                 "http://h", "k")[0]
    assert item.episode_title == ""
    assert item.has_time
    assert item.local_date(NY).isoformat() == "2026-11-16"  # 9PM Monday in New York


def test_sonarr_garbage_is_skipped():
    assert parse_sonarr_calendar({"error": "x"}, "http://h") == []
    assert parse_sonarr_calendar([None, {"id": 1}], "http://h") == []


# -- Radarr -----------------------------------------------------------------

MOVIE = {
    "id": 9, "title": "Film", "runtime": 101, "overview": "o",
    "inCinemas": "2026-11-18T00:00:00Z", "digitalRelease": "2026-11-20T00:00:00Z",
    "physicalRelease": "2026-11-20T00:00:00Z",
    "images": [{"coverType": "poster", "url": "/MediaCover/9/poster.jpg"}],
}


def test_radarr_one_item_per_release_date():
    items = parse_radarr_calendar([MOVIE], "http://r:7878", "k")
    # physical lands on the same day as digital, so it is not repeated
    assert [(i.release_label, i.when.date().isoformat()) for i in items] == [
        ("In Theaters", "2026-11-18"), ("Digital", "2026-11-20")]
    assert all(not i.has_time and i.kind == "movie" for i in items)


def test_radarr_release_type_filter():
    items = parse_radarr_calendar([MOVIE], "http://r", "k", release_types=["physical"])
    assert [i.release_label for i in items] == ["Physical"]


def test_date_only_keeps_its_day_west_of_utc():
    item = parse_radarr_calendar([MOVIE], "http://r", "k", release_types=["cinema"])[0]
    # Midnight UTC is the previous evening in New York; the release day must not move.
    assert item.local_date(NY).isoformat() == "2026-11-18"


# -- Jellyfin ---------------------------------------------------------------

def test_jellyfin_upcoming_parsing():
    payload = {"Items": [{
        "Id": "e1", "Name": "The Return", "SeriesName": "Show", "SeriesId": "s1",
        "ParentIndexNumber": 2, "IndexNumber": 5, "PremiereDate": "2026-11-19T00:00:00.0000000Z",
        "RunTimeTicks": 27_000_000_000, "Overview": "Desc.", "LocationType": "Virtual",
    }]}
    item = parse_jellyfin_upcoming(payload, "http://jf:8096/", "abc")[0]
    assert (item.title, item.season, item.episode, item.episode_title) == ("Show", 2, 5, "The Return")
    assert item.runtime_min == 45
    assert not item.has_time  # midnight filler
    assert not item.has_file
    assert item.images["logo"] == "http://jf:8096/Items/s1/Images/Logo"
    assert item.image_headers["logo"]["Authorization"] == 'MediaBrowser Token="abc"'


def test_parse_iso_handles_dotnet_fractions():
    assert parse_iso("2026-11-19T21:30:00.1234567Z") == datetime(2026, 11, 19, 21, 30, 0, 123456,
                                                                 tzinfo=timezone.utc)
    assert parse_iso("2026-11-19") == datetime(2026, 11, 19, tzinfo=timezone.utc)
    assert parse_iso("nope") is None


# -- window -----------------------------------------------------------------

def _ep(uid, group, when, has_time=True, has_file=False):
    return UpcomingItem(kind="episode", uid=uid, group_id=group, title=group,
                        when=parse_iso(when), has_time=has_time, season=1, episode=1,
                        has_file=has_file)


ITEMS = [
    _ep("a1", "A", "2026-11-16T15:00:00Z"),            # earlier today (aired)
    _ep("a2", "A", "2026-11-18T02:00:00Z"),
    _ep("b1", "B", "2026-11-17T02:00:00Z"),
    _ep("c1", "C", "2026-11-24T02:00:00Z"),            # 23 Nov in New York: day 7
    _ep("d1", "D", "2026-11-26T02:00:00Z"),            # beyond a week
    _ep("e0", "E", "2026-11-15T23:00:00Z"),            # yesterday in New York
]


def test_week_window_and_order():
    got = select_items(ITEMS, NOW, NY, 7)
    assert [i.uid for i in got] == ["a1", "b1", "a2", "c1"]


def test_aired_today_can_be_hidden():
    got = select_items(ITEMS, NOW, NY, 7, include_aired_today=False)
    assert "a1" not in [i.uid for i in got]


def test_next_per_show():
    got = select_items(ITEMS, NOW, NY, 7, window="next_per_show", include_aired_today=False)
    assert [i.uid for i in got] == ["b1", "a2", "c1"]


def test_max_items_and_downloaded_filter():
    items = ITEMS + [_ep("f1", "F", "2026-11-17T03:00:00Z", has_file=True)]
    assert len(select_items(items, NOW, NY, 7, max_items=2)) == 2
    assert "f1" not in [i.uid for i in select_items(items, NOW, NY, 7, include_downloaded=False)]


def test_today_only():
    assert [i.uid for i in select_items(ITEMS, NOW, NY, 0)] == ["a1", "b1"]


# -- formatting -------------------------------------------------------------

def test_episode_formats():
    item = _ep("x", "X", "2026-11-17T02:00:00Z")
    item.season, item.episode = 3, 4
    assert format_episode_number(item, "compact") == "S3E4"
    assert format_episode_number(item, "padded") == "S03E04"
    assert format_episode_number(item, "long") == "Season 3 Episode 4"


def test_runtime_format():
    assert format_runtime(45) == "45m"
    assert format_runtime(125) == "2h 5m"
    assert format_runtime(125, compact=True) == "2h05"
    assert format_runtime(120) == "2h"
    assert format_runtime(None) == ""


def test_relative_dates():
    tonight = _ep("x", "X", "2026-11-17T02:00:00Z")      # Mon 9PM New York
    assert format_when(tonight, NOW, NY) == "Today 9PM"
    assert format_when(tonight, NOW, NY, time_format="24h") == "Today 21:00"
    tomorrow = _ep("y", "Y", "2026-11-18T01:30:00Z")
    assert format_when(tomorrow, NOW, NY) == "Tomorrow 8:30PM"
    assert format_when(tomorrow, NOW, NY, level=1) == "Tmrw 8P"
    assert format_when(tomorrow, NOW, NY, level=2) == "Tmrw"
    thursday = _ep("z", "Z", "2026-11-19T00:00:00Z", has_time=False)
    assert format_when(thursday, NOW, NY) == "Thu"
    assert format_when(thursday, NOW, NY, date_format="short") == "Nov 19"
    assert format_when(thursday, NOW, NY, date_format="numeric") == "11/19"
    later = _ep("w", "W", "2026-11-30T00:00:00Z", has_time=False)
    assert format_when(later, NOW, NY) == "Nov 30"


def test_short_description():
    text = "A storm strands the crew. Then things get worse and worse for everyone aboard."
    assert short_description(text, 60) == "A storm strands the crew."
    long = "One very long sentence that keeps going on and on without stopping anywhere soon"
    out = short_description(long, 30)
    assert out.endswith("...") and len(out) <= 30


def test_size_tiers():
    assert size_tier(64, 32) == "small"
    assert size_tier(256, 32) == "small"
    assert size_tier(64, 64) == "small"
    assert size_tier(128, 64) == "medium"
    assert size_tier(256, 128) == "large"


def test_image_store_cache_roundtrip():
    from PIL import Image

    class Cache(dict):
        def get(self, key, max_age=None):
            return dict.get(self, key)

        def set(self, key, value, ttl=None):
            self[key] = value

    cache = Cache()
    url = "http://h/MediaCover/1/poster.jpg"
    cache[ImageStore.cache_key(url)] = ImageStore.encode(Image.new("RGBA", (20, 30), (255, 0, 0, 255)))
    store = ImageStore(cache=cache)
    assert store.prefetch(url)  # served from the cache, no request
    fitted = store.fitted(url, (10, 10))
    assert fitted is not None and fitted.size == (6, 10)


# -- same-day grouping ------------------------------------------------------

def _numbered(uid, group, when, episode, season=3, title=None):
    item = _ep(uid, group, when)
    item.season, item.episode = season, episode
    item.episode_title = title or f"Ep {episode}"
    item.runtime_min = 50
    return item


def test_back_to_back_episodes_merge_into_one_card():
    items = [
        _numbered("r5", "R", "2026-11-18T08:00:00Z", 5),       # Wed 3AM NY
        _numbered("r6", "R", "2026-11-18T09:07:00Z", 6),       # same NY day
        _numbered("t1", "T", "2026-11-18T08:30:00Z", 1),       # another show between them
        _numbered("r7", "R", "2026-11-19T08:00:00Z", 7),       # next day: separate
    ]
    got = select_items(items, NOW, NY, 7)
    assert [i.title for i in got] == ["R", "T", "R"]
    merged = got[0]
    assert (merged.episode, merged.episode_end, merged.episode_count) == (5, 6, 2)
    assert merged.episode_title == "2 episodes"
    assert merged.when == parse_iso("2026-11-18T08:00:00Z")   # first air time
    assert merged.uid != "r5"                                 # redraws when the group changes
    assert format_episode_number(merged, "compact") == "S3E5-6"
    assert format_episode_number(merged, "padded") == "S03E05-06"
    assert format_episode_number(merged, "long") == "Season 3 Episodes 5-6"
    assert got[2].episode_end is None


def test_whole_season_drop_and_gaps():
    drop = [_numbered(f"s{n}", "S", "2026-11-20T08:00:00Z", n, season=1) for n in range(1, 9)]
    got = select_items(drop, NOW, NY, 7)
    assert len(got) == 1 and format_episode_number(got[0], "compact") == "S1E1-8"
    assert got[0].episode_title == "8 episodes"
    gap = [_numbered("g5", "G", "2026-11-18T08:00:00Z", 5),
           _numbered("g7", "G", "2026-11-18T09:00:00Z", 7)]
    assert len(select_items(gap, NOW, NY, 7)) == 2           # E6 missing: no merge


def test_grouping_can_be_turned_off_and_counts_toward_max_items():
    items = [_numbered(f"x{n}", "X", "2026-11-18T08:00:00Z", n) for n in (1, 2, 3)] + \
        [_numbered("y1", "Y", "2026-11-18T10:00:00Z", 1)]
    assert len(select_items(items, NOW, NY, 7, group_episodes=False)) == 4
    assert [i.title for i in select_items(items, NOW, NY, 7, max_items=2)] == ["X", "Y"]


# -- logo readability -------------------------------------------------------

def _logo(rgb, fill=1.0, size=(60, 20)):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((0, 0, int(size[0] * fill) - 1, size[1] - 1), fill=rgb + (255,))
    return img


def test_dim_logo_is_brightened_keeping_its_hue():
    dark_green = _logo((20, 60, 30))
    lifted = ImageStore.brighten(dark_green)
    r, g, b, _ = lifted.getpixel((5, 5))
    assert g > 150 and g > r and g > b
    bright = _logo((250, 250, 250))
    assert ImageStore.brighten(bright).getpixel((5, 5)) == (250, 250, 250, 255)


def test_unreadable_logos_are_rejected():
    assert ImageStore.readable(ImageStore.brighten(_logo((20, 60, 30))))
    assert not ImageStore.readable(ImageStore.brighten(_logo((0, 0, 0))))       # black art
    assert not ImageStore.readable(ImageStore.brighten(_logo((255, 255, 255), fill=0.05)))  # hairline
    assert not ImageStore.readable(None)


def test_foreign_host_image_never_gets_the_api_key():
    ep = sonarr_ep(1, 1, "Show", "2026-11-17T02:00:00Z", images=[
        {"coverType": "poster", "url": "http://evil.example/x.jpg",
         "remoteUrl": "https://img.example/poster.jpg"}])
    item = parse_sonarr_calendar([ep], "http://sonarr:8989", "secret")[0]
    assert item.images["poster"] == "https://img.example/poster.jpg"
    assert "poster" not in item.image_headers
    own = sonarr_ep(2, 2, "Show", "2026-11-17T02:00:00Z", images=[
        {"coverType": "poster", "url": "/MediaCover/2/poster.jpg"}])
    item = parse_sonarr_calendar([own], "http://SONARR:8989/", "secret")[0]
    assert item.image_headers["poster"] == {"X-Api-Key": "secret"}
