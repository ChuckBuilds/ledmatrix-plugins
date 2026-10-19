"""Which file holds a soccer team's logo.

Every soccer league shares one logo directory, and ESPN abbreviations are not
unique: in the Scottish Premiership Dundee and Dundee United are both DUN, the
EFL Cup has two BARs and two NEWs, Celta Vigo and Celtic are both CEL in the
Europa League, and across leagues BRE is Brentford and Brest. Named by
abbreviation alone, two clubs shared one file, and whichever downloaded first
was drawn for both. So a club's logo is kept under its ESPN team id as well
(``DUN_261.png``). ESPN soccer team ids are the same in every competition.

The logos core ships are named by abbreviation (``TOT.png``). They are still
used, but only when the club's own file cannot be downloaded, so an offline
board keeps its crests. The World Cup's ``national/`` flags stay named by
abbreviation: the plugin ships every nation's flag, and FIFA codes are unique.
"""

from pathlib import Path
from typing import Any, Optional

from src.common.sports_helpers import logo_needs_refresh
from src.logo_downloader import LogoDownloader, download_missing_logo

#: The World Cup flags directory (soccer_managers._setup_national_flags_dir).
NATIONAL_DIR = "national"


def soccer_logo_filename(logo_dir: Path, abbr: str, team_id: Any) -> str:
    """The file a team's logo is kept in under ``logo_dir``."""
    name = LogoDownloader.normalize_abbreviation(abbr)
    if not team_id or Path(logo_dir).name == NATIONAL_DIR:
        return f"{name}.png"
    return f"{name}_{team_id}.png"


def resolve_soccer_logo(logo_path, team_abbrev: str, team_id: Any,
                        logo_url: Optional[str], league: str) -> Optional[Path]:
    """The file to draw for one team, downloading the club's own when missing.

    Order: the team's own file; a download into it; the abbreviation-named
    logo core ships; finally a placeholder in the team's own file.
    """
    logo_path = Path(logo_path)

    def usable(p: Path) -> bool:
        return p.exists() and not logo_needs_refresh(p)

    shipped = [logo_path.parent / n
               for n in LogoDownloader.get_logo_filename_variations(team_abbrev)]
    if logo_path.name in {p.name for p in shipped}:
        # Named by abbreviation already (a flag, or no team id): the old
        # lookup, which also finds TA&M.png under TAANDM.png.
        found = next((p for p in shipped if usable(p)), None)
        if found:
            return found
    elif usable(logo_path):
        return logo_path

    download_missing_logo(league, str(team_id or ""), team_abbrev, logo_path,
                          logo_url, create_placeholder=False)
    if usable(logo_path):
        return logo_path
    found = next((p for p in shipped if usable(p)), None)
    if found:
        return found
    download_missing_logo(league, str(team_id or ""), team_abbrev, logo_path, logo_url)
    return logo_path if logo_path.exists() else None
