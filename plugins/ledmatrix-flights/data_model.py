"""
Data model definitions for the Flight Tracker plugin.

Dataclasses representing aircraft state, tracked flights, flight records, and
the immutable snapshot the map is drawn from.
These provide type-safe alternatives to the raw dicts used internally.
"""

import dataclasses
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from utils import (MAX_POS_AGE_SECONDS, clamp_pos_age, is_number, is_real_track,
                   plane_offset_miles)


@dataclass
class AircraftState:
    """Unified aircraft state from any data source (SkyAware, FR24, OpenSky).

    Field units match the internal convention:
      - altitude: feet
      - speed: knots (ground speed)
      - heading: degrees from north (0-360)
      - vertical_rate: feet/minute
      - distance_miles: statute miles from configured center
    """
    icao: str
    callsign: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    vertical_rate: Optional[float] = None
    distance_miles: Optional[float] = None
    color: Tuple[int, int, int] = (255, 255, 255)
    on_ground: bool = False
    category: str = ""
    registration: str = ""
    aircraft_type: str = "Unknown"
    origin: str = ""
    destination: str = ""
    airline_icao: str = ""
    airline_name: str = ""
    fr24_id: str = ""
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    fr24_time: Optional[Dict[str, Any]] = None
    last_seen: float = 0.0

    # --- dict bridge methods (backward compat with existing code) ---

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AircraftState":
        """Create an AircraftState from a legacy aircraft info dict."""
        return cls(
            icao=d.get("icao", ""),
            callsign=d.get("callsign", ""),
            lat=d.get("lat"),
            lon=d.get("lon"),
            altitude=d.get("altitude"),
            speed=d.get("speed"),
            heading=d.get("heading"),
            vertical_rate=d.get("vertical_rate"),
            distance_miles=d.get("distance_miles"),
            color=tuple(d.get("color", (255, 255, 255))),
            on_ground=d.get("on_ground", False),
            category=d.get("category", ""),
            registration=d.get("registration", ""),
            aircraft_type=d.get("aircraft_type", "Unknown"),
            origin=d.get("origin", ""),
            destination=d.get("destination", ""),
            airline_icao=d.get("airline_icao", ""),
            airline_name=d.get("airline_name", ""),
            fr24_id=d.get("fr24_id", ""),
            origin_lat=d.get("origin_lat"),
            origin_lon=d.get("origin_lon"),
            dest_lat=d.get("dest_lat"),
            dest_lon=d.get("dest_lon"),
            fr24_time=d.get("fr24_time"),
            last_seen=d.get("last_seen", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to a legacy aircraft info dict."""
        d = {
            "icao": self.icao,
            "callsign": self.callsign,
            "lat": self.lat,
            "lon": self.lon,
            "altitude": self.altitude,
            "speed": self.speed,
            "heading": self.heading,
            "distance_miles": self.distance_miles,
            "color": self.color,
            "last_seen": self.last_seen,
            "registration": self.registration,
            "aircraft_type": self.aircraft_type,
        }
        # Only include optional enrichment fields if non-default
        if self.vertical_rate is not None:
            d["vertical_rate"] = self.vertical_rate
        if self.on_ground:
            d["on_ground"] = self.on_ground
        if self.category:
            d["category"] = self.category
        if self.origin:
            d["origin"] = self.origin
        if self.destination:
            d["destination"] = self.destination
        if self.airline_icao:
            d["airline_icao"] = self.airline_icao
        if self.airline_name:
            d["airline_name"] = self.airline_name
        if self.fr24_id:
            d["fr24_id"] = self.fr24_id
        if self.origin_lat is not None:
            d["origin_lat"] = self.origin_lat
            d["origin_lon"] = self.origin_lon
        if self.dest_lat is not None:
            d["dest_lat"] = self.dest_lat
            d["dest_lon"] = self.dest_lon
        if self.fr24_time is not None:
            d["fr24_time"] = self.fr24_time
        return d


@dataclass
class TrackedFlight:
    """A user-configured flight to track specifically.

    Populated from enrichment sources (OpenSky routes, FR24 detail, FlightAware).
    """
    identifier: str
    status: str = "UNKNOWN"  # SCHEDULED, AIRBORNE, LANDED, UNKNOWN
    origin: str = ""
    destination: str = ""
    origin_name: str = ""
    destination_name: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    progress_pct: Optional[float] = None
    aircraft_state: Optional[AircraftState] = None
    city_overfly: str = ""
    last_updated: float = 0.0


@dataclass
class FlightRecord:
    """Snapshot of an aircraft for closest/farthest records."""
    callsign: str = ""
    registration: str = ""
    aircraft_type: str = ""
    altitude: float = 0.0
    speed: float = 0.0
    distance_miles: float = 0.0
    origin: str = ""
    destination: str = ""
    airline_name: str = ""
    timestamp: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlightRecord":
        """Create from a saved record dict."""
        return cls(
            callsign=d.get("callsign", ""),
            registration=d.get("registration", ""),
            aircraft_type=d.get("aircraft_type", ""),
            altitude=d.get("altitude", 0.0),
            speed=d.get("speed", 0.0),
            distance_miles=d.get("distance_miles", 0.0),
            origin=d.get("origin", ""),
            destination=d.get("destination", ""),
            airline_name=d.get("airline_name", ""),
            timestamp=d.get("timestamp", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "callsign": self.callsign,
            "registration": self.registration,
            "aircraft_type": self.aircraft_type,
            "altitude": self.altitude,
            "speed": self.speed,
            "distance_miles": self.distance_miles,
            "origin": self.origin,
            "destination": self.destination,
            "airline_name": self.airline_name,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Map snapshot
#
# update() rebuilds aircraft_data and aircraft_trails in place, on the update
# worker, while the map can be drawn from another thread (a Vegas redraw runs
# without the plugin lock). So the map is drawn from a frozen copy that
# update() swaps in with a single attribute store: a reader holding one sees
# one consistent sky, never a half-applied poll.
# ---------------------------------------------------------------------------

#: Slower than this (knots) is taxiing, hovering or parked: not worth moving.
MIN_EXTRAPOLATE_SPEED_KT = 30.0

#: Dead reckoning carries an aircraft on for at most this long past the moment
#: its position was true, then holds it there: one that went quiet stops
#: rather than flying on. It counts from the position time, so the source's
#: own delay uses it up too. A local receiver's positions arrive a second or
#: two old, so a 5 s poll never gets near it; OpenSky's arrive 5-25 s old, and
#: with it (or an update_interval over ~15 s) a dot can reach the cap and wait
#: for the next poll.
MAX_GLIDE_SECONDS = 20.0

#: A new poll's correction to where the map was gliding an aircraft is spread
#: over this long instead of landing in one frame.
EASE_SECONDS = 1.5

#: Speeds are knots; the map works in statute miles.
_MILES_PER_NM = 1.150779

_WHITE = (255, 255, 255)


def _color_tuple(value) -> Tuple[int, ...]:
    """An aircraft's colour as a tuple, or white when it has none usable.

    The dot has always fallen back to white for a missing colour; a malformed
    one (which used to take the whole map to ERR) now does the same.
    """
    value = value or _WHITE
    try:
        color = tuple(value)
    except TypeError:
        return _WHITE
    if len(color) not in (3, 4) or not all(is_number(c) for c in color):
        return _WHITE
    return color


@dataclass(frozen=True)
class MapAircraft:
    """One aircraft as the map draws it.

    ``pos_mono`` is the time.monotonic() the position was true at (receipt
    time less the source's own position age), or None when the record did
    not say when it was received. ``speed_kt``/``track_deg`` and
    ``can_extrapolate`` are for dead reckoning between polls (glide_miles).
    ``can_extrapolate`` is decided at publish, against the position's age
    then -- or kept from the previous snapshot while the report has not
    moved (MapSnapshot.held_from).
    """
    icao: str
    lat: float
    lon: float
    color: Tuple[int, ...]
    trail: Tuple[Tuple[float, float], ...]
    pos_mono: Optional[float]
    speed_kt: float
    track_deg: float
    can_extrapolate: bool

    def draw_key(self, show_trails: bool) -> tuple:
        """What this aircraft's pixels depend on. Motion only counts when it
        can be used, so a parked aircraft re-reported at the same spot (a new
        pos_mono, same pixels) does not look like a change."""
        motion = ((self.pos_mono, self.speed_kt, self.track_deg)
                  if self.can_extrapolate else None)
        return (self.icao, self.lat, self.lon, self.color,
                self.trail if show_trails else None, motion)

    def glide_miles(self, at: float) -> Tuple[float, float]:
        """(east, north) statute miles dead reckoning carries this aircraft from
        its reported position by ``at`` (a time.monotonic()).

        Along track_deg at speed_kt for the position's age at ``at``, capped at
        MAX_GLIDE_SECONDS, where it holds: a position that goes stale stops
        moving, and never goes back to where it was reported. Nothing for an
        aircraft that cannot extrapolate.
        """
        if not self.can_extrapolate or self.pos_mono is None:
            return 0.0, 0.0
        seconds = min(max(at - self.pos_mono, 0.0), MAX_GLIDE_SECONDS)
        miles = self.speed_kt * _MILES_PER_NM * seconds / 3600.0
        track = math.radians(self.track_deg)
        return miles * math.sin(track), miles * math.cos(track)


@dataclass(frozen=True)
class MapSnapshot:
    """Everything the map draws, frozen at publish time.

    ``aircraft`` is in aircraft_data order (dots are drawn in it) and
    ``trail_order`` indexes it in aircraft_trails order (trails are drawn in
    that one). The two orders can differ, and where trails cross the one drawn
    last wins, so both are kept to draw exactly what the dicts did.

    ``seq`` rises by one each time a snapshot with a different ``draw_key()``
    is published, so a reader can tell "new sky" from "same sky again".

    ``published_mono`` and ``corrections`` are set when it is published after
    another (with_corrections): per aircraft, the (east, north) miles from
    where this snapshot places it to where the previous one was drawing it
    then, eased out over EASE_SECONDS from ``published_mono`` so a new poll
    does not make a gliding dot jump. They are how it is drawn over time,
    not what it shows, so they are not part of draw_key().
    """
    seq: int
    center_lat: float
    center_lon: float
    map_radius_miles: float
    zoom_factor: float
    show_trails: bool
    aircraft: Tuple[MapAircraft, ...] = ()
    trail_order: Tuple[int, ...] = ()
    published_mono: Optional[float] = None
    corrections: Tuple[Tuple[float, float], ...] = ()

    def draw_key(self) -> tuple:
        """Everything the pixels depend on, seq aside: snapshots with equal
        keys draw the same map at any size and any time."""
        return (self.center_lat, self.center_lon, self.map_radius_miles,
                self.zoom_factor, self.show_trails,
                self.trail_order if self.show_trails else None,
                tuple(a.draw_key(self.show_trails) for a in self.aircraft))

    def ease(self, at: float) -> float:
        """How much of each correction still applies at ``at``: 1 at publish,
        falling linearly to 0 over EASE_SECONDS."""
        if self.published_mono is None:
            return 0.0
        return min(1.0, max(0.0, 1.0 - (at - self.published_mono) / EASE_SECONDS))

    def eased_correction(self, index: int, at: float) -> Tuple[float, float]:
        """(east, north) miles of aircraft ``index``'s correction left at ``at``."""
        if index >= len(self.corrections):
            return 0.0, 0.0
        k = self.ease(at)
        if k <= 0.0:
            return 0.0, 0.0
        east, north = self.corrections[index]
        return east * k, north * k

    def _offset_miles(self, index: int, at: float, center_lat: float,
                      center_lon: float, corrected: bool) -> Tuple[float, float]:
        """(east, north) miles from the given centre to where aircraft
        ``index`` is placed at ``at``: reported, carried on, and (if
        ``corrected``) plus what is left of its correction."""
        ac = self.aircraft[index]
        east, north = plane_offset_miles(center_lat, center_lon, ac.lat, ac.lon)
        glide_east, glide_north = ac.glide_miles(at)
        east, north = east + glide_east, north + glide_north
        if corrected:
            corr_east, corr_north = self.eased_correction(index, at)
            east, north = east + corr_east, north + corr_north
        return east, north

    def with_corrections(self, prev: Optional["MapSnapshot"],
                         now_mono: float) -> "MapSnapshot":
        """This snapshot as published at ``now_mono``, after ``prev``.

        For an aircraft in both, the correction is where ``prev`` was drawing
        it at that moment -- carried on, with its own correction's remainder,
        so two publishes close together do not jump either -- less where this
        one puts it. A new aircraft gets none: it appears where it is. Both
        are measured from this snapshot's centre, so a moved view cannot turn
        into a correction.

        The remainder is carried whether or not the render eased it (the map
        snaps a correction over 6 px at the size drawn). That only matters for
        two publishes that change the drawing within EASE_SECONDS, and those
        come one per fetch, 5 s or more apart.
        """
        index = ({ac.icao: i for i, ac in enumerate(prev.aircraft)}
                 if prev is not None else {})
        corrections = []
        for i, ac in enumerate(self.aircraft):
            j = index.get(ac.icao)
            if j is None:
                corrections.append((0.0, 0.0))
                continue
            was_east, was_north = prev._offset_miles(
                j, now_mono, self.center_lat, self.center_lon, corrected=True)
            now_east, now_north = self._offset_miles(
                i, now_mono, self.center_lat, self.center_lon, corrected=False)
            corrections.append((was_east - now_east, was_north - now_north))
        return dataclasses.replace(self, published_mono=now_mono,
                                   corrections=tuple(corrections))

    def held_from(self, prev: Optional["MapSnapshot"]) -> "MapSnapshot":
        """This snapshot, with every aircraft ``prev`` was carrying on whose
        report has not moved since, but which can no longer be carried on
        itself (it went stale, or lost its speed or track), still carried as
        ``prev`` carried it.

        glide_miles stops it at MAX_GLIDE_SECONDS and holds it there. Without
        this, the publish after a report aged out would put the dot back on
        it: up to 20 s of flight backwards in one frame, for every aircraft
        that drops out of the feed and for the whole sky when a fallback
        payload ages. A report already stale when first seen has no ``prev``
        entry to keep, so it never moves.
        """
        if prev is None:
            return self
        was = {ac.icao: ac for ac in prev.aircraft if ac.can_extrapolate}
        aircraft = []
        for ac in self.aircraft:
            old = was.get(ac.icao)
            if (old is not None and not ac.can_extrapolate
                    and (old.lat, old.lon) == (ac.lat, ac.lon)):
                ac = dataclasses.replace(ac, pos_mono=old.pos_mono, speed_kt=old.speed_kt,
                                         track_deg=old.track_deg, can_extrapolate=True)
            aircraft.append(ac)
        return dataclasses.replace(self, aircraft=tuple(aircraft))

    @classmethod
    def build(cls, seq: int, aircraft_data: Mapping[str, Dict],
              aircraft_trails: Mapping[str, Any], *, center_lat: float,
              center_lon: float, map_radius_miles: float, zoom_factor: float,
              show_trails: bool, now_mono: Optional[float] = None) -> "MapSnapshot":
        """Copy what the map draws out of the live dicts.

        Everything is copied into tuples, so later in-place edits to the dicts
        or trail lists cannot reach a published snapshot. An entry without a
        usable position is left off (drawing it used to raise), as is a trail
        point without one. ``now_mono`` is the time.monotonic() of publishing
        (now, if omitted).
        """
        if now_mono is None:
            now_mono = time.monotonic()
        aircraft = []
        index: Dict[str, int] = {}
        for icao, ac in aircraft_data.items():
            if not isinstance(ac, Mapping):
                continue
            lat, lon = ac.get('lat'), ac.get('lon')
            if not (is_number(lat) and is_number(lon)):
                continue
            trail = tuple(
                (point[0], point[1]) for point in (aircraft_trails.get(icao) or ())
                if isinstance(point, (tuple, list)) and len(point) >= 2
                and is_number(point[0]) and is_number(point[1]))

            pos_age = clamp_pos_age(ac.get('pos_age', 0.0))
            received = ac.get('received_mono')
            pos_mono = received - pos_age if is_number(received) else None
            speed = ac.get('speed')
            speed_kt = float(speed) if is_number(speed) else 0.0
            heading = ac.get('heading')
            track_valid = bool(ac.get('track_valid')) and is_real_track(heading)
            # Too old to move on from: the source already said so (pos_stale,
            # which the clamped pos_age cannot), or it has become so since
            # receipt -- a fallback payload, or a record kept for up to 60 s
            # after it left the feed.
            fresh = (pos_mono is not None
                     and not ac.get('pos_stale', False)
                     and now_mono - pos_mono <= MAX_POS_AGE_SECONDS)
            can_extrapolate = (track_valid
                               and fresh
                               and not ac.get('on_ground', False)
                               and speed_kt >= MIN_EXTRAPOLATE_SPEED_KT)

            index[icao] = len(aircraft)
            aircraft.append(MapAircraft(
                icao=str(icao),
                lat=lat,
                lon=lon,
                color=_color_tuple(ac.get('color')),
                trail=trail,
                pos_mono=pos_mono,
                speed_kt=speed_kt,
                track_deg=float(heading) if track_valid else 0.0,
                can_extrapolate=can_extrapolate,
            ))

        return cls(
            seq=seq,
            center_lat=center_lat,
            center_lon=center_lon,
            map_radius_miles=map_radius_miles,
            zoom_factor=zoom_factor,
            show_trails=bool(show_trails),
            aircraft=tuple(aircraft),
            trail_order=tuple(index[icao] for icao in aircraft_trails
                              if icao in index),
        )
