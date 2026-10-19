"""Which file holds a soccer team's logo.

Every soccer league shares one logo directory, and ESPN abbreviations are not
unique: in the Scottish Premiership Dundee and Dundee United are both DUN, the
EFL Cup has two BARs and two NEWs, Celta Vigo and Celtic are both CEL in the
Europa League, and across leagues BRE is Brentford and Brest. Named by
abbreviation alone, two clubs shared one file, and whichever downloaded first
was drawn for both. So a club's logo is kept under its ESPN team id as well
(``DUN_261.png``). ESPN soccer team ids are the same in every competition.

The logos core ships are named by abbreviation (``TOT.png``). When the club's
own file is missing, the shipped one is drawn at once and the club's own is
fetched in the background, at most once an hour, so a board that starts
offline keeps its crests without stalling on a download per club. The World Cup's ``national/`` flags stay named by
abbreviation: the plugin ships every nation's flag, and FIFA codes are unique.
"""

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.common.sports_helpers import logo_needs_refresh
from src.logo_downloader import LogoDownloader, download_missing_logo

#: The World Cup flags directory (soccer_managers._setup_national_flags_dir).
NATIONAL_DIR = "national"

#: Set in a loaded logo's ``info`` when it is a stand-in for the club's own.
FALLBACK = "soccer_logo_fallback"

#: How long to wait before fetching a club's own logo again.
RETRY_SECONDS = 60 * 60
_last_try: Dict[str, float] = {}
_last_try_lock = threading.Lock()


def _start(job) -> None:
    """Seam: run a background download (tests run it inline)."""
    threading.Thread(target=job, name="soccer-logo-fetch", daemon=True).start()


def _fetch_later(logo_path: Path, team_abbrev: str, team_id: Any,
                 logo_url: Optional[str], league: str) -> None:
    """Download the club's own logo in the background, at most once an hour."""
    key = str(logo_path)
    now = time.monotonic()
    with _last_try_lock:
        if key in _last_try and now - _last_try[key] < RETRY_SECONDS:
            return
        _last_try[key] = now
    _start(lambda: download_missing_logo(league, str(team_id or ""), team_abbrev,
                                         logo_path, logo_url, create_placeholder=False))


def _usable(p: Path) -> bool:
    return p.exists() and not logo_needs_refresh(p)


def soccer_logo_filename(logo_dir: Path, abbr: str, team_id: Any) -> str:
    """The file a team's logo is kept in under ``logo_dir``."""
    name = LogoDownloader.normalize_abbreviation(abbr)
    if not team_id or Path(logo_dir).name == NATIONAL_DIR:
        return f"{name}.png"
    return f"{name}_{team_id}.png"


def resolve_soccer_logo(logo_path, team_abbrev: str, team_id: Any,
                        logo_url: Optional[str], league: str) -> Optional[Path]:
    """The file to draw for one team.

    The team's own file; else the abbreviation-named logo core ships, while
    the club's own is fetched in the background; else one download into the
    team's own file, which leaves a placeholder there if it fails.
    """
    logo_path = Path(logo_path)
    shipped = [logo_path.parent / n
               for n in LogoDownloader.get_logo_filename_variations(team_abbrev)]
    own_is_shipped = logo_path.name in {p.name for p in shipped}
    if not own_is_shipped and _usable(logo_path):
        return logo_path
    found = next((p for p in shipped if _usable(p)), None)
    if found:
        if not own_is_shipped:
            _fetch_later(logo_path, team_abbrev, team_id, logo_url, league)
        return found
    download_missing_logo(league, str(team_id or ""), team_abbrev, logo_path, logo_url)
    return logo_path if logo_path.exists() else None


def club_logo_arrived(logo_path, team_abbrev: str, team_id: Any,
                      logo_url: Optional[str], league: str) -> bool:
    """For a cached stand-in: True once the club's own file is on disk.

    Until then it asks for the club's own again (at most once an hour), so a
    cache hit never waits on the network.
    """
    logo_path = Path(logo_path)
    if _usable(logo_path):
        return True
    _fetch_later(logo_path, team_abbrev, team_id, logo_url, league)
    return False
