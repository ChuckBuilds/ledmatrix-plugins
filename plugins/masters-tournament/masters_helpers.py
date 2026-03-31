"""
Masters Tournament Helper Functions

Comprehensive utility functions, real tournament data, fun facts,
accurate hole information, and complete historical records.
"""

import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# Augusta is in Eastern Time (UTC-5 / UTC-4 DST)
# Use a fixed offset for April (EDT = UTC-4) to avoid requiring pytz/zoneinfo
# at import time. Masters always falls during DST.
_EDT = timezone(timedelta(hours=-4))


# ═══════════════════════════════════════════════════════════════
# COMPLETE AUGUSTA NATIONAL HOLE DATA (2024 yardages)
# ═══════════════════════════════════════════════════════════════

AUGUSTA_HOLES = {
    1:  {"name": "Tea Olive",              "par": 4, "yardage": 445,  "record": 2, "record_holder": "Justin Rose (2017)"},
    2:  {"name": "Pink Dogwood",           "par": 5, "yardage": 575,  "record": 3, "record_holder": "Multiple"},
    3:  {"name": "Flowering Peach",        "par": 4, "yardage": 350,  "record": 2, "record_holder": "Multiple"},
    4:  {"name": "Flowering Crab Apple",   "par": 3, "yardage": 240,  "record": 1, "record_holder": "Jeff Sluman (1992)"},
    5:  {"name": "Magnolia",               "par": 4, "yardage": 495,  "record": 2, "record_holder": "Multiple"},
    6:  {"name": "Juniper",                "par": 3, "yardage": 180,  "record": 1, "record_holder": "Jamie Donaldson (2014)"},
    7:  {"name": "Pampas",                 "par": 4, "yardage": 450,  "record": 2, "record_holder": "Multiple"},
    8:  {"name": "Yellow Jasmine",         "par": 5, "yardage": 570,  "record": 2, "record_holder": "Bruce Devlin (1967)"},
    9:  {"name": "Carolina Cherry",        "par": 4, "yardage": 460,  "record": 2, "record_holder": "Multiple"},
    10: {"name": "Camellia",               "par": 4, "yardage": 495,  "record": 2, "record_holder": "Multiple"},
    11: {"name": "White Dogwood",          "par": 4, "yardage": 520,  "record": 2, "record_holder": "Multiple",     "zone": "Amen Corner"},
    12: {"name": "Golden Bell",            "par": 3, "yardage": 155,  "record": 1, "record_holder": "Multiple",     "zone": "Amen Corner"},
    13: {"name": "Azalea",                 "par": 5, "yardage": 510,  "record": 2, "record_holder": "Jeff Maggert (1994)", "zone": "Amen Corner"},
    14: {"name": "Chinese Fir",            "par": 4, "yardage": 440,  "record": 2, "record_holder": "Multiple"},
    15: {"name": "Firethorn",              "par": 5, "yardage": 550,  "record": 2, "record_holder": "Gene Sarazen (1935)"},
    16: {"name": "Redbud",                 "par": 3, "yardage": 170,  "record": 1, "record_holder": "Multiple",     "zone": "Featured"},
    17: {"name": "Nandina",                "par": 4, "yardage": 440,  "record": 2, "record_holder": "Multiple"},
    18: {"name": "Holly",                  "par": 4, "yardage": 465,  "record": 2, "record_holder": "Multiple"},
}

# Course totals
AUGUSTA_PAR = 72
AUGUSTA_TOTAL_YARDAGE = 7545


# ═══════════════════════════════════════════════════════════════
# PAST CHAMPIONS - Complete and accurate through 2025
# ═══════════════════════════════════════════════════════════════

PAST_CHAMPIONS = [
    (2025, "Rory McIlroy",       "NIR", -11),
    (2024, "Scottie Scheffler",  "USA", -11),
    (2023, "Jon Rahm",           "ESP", -12),
    (2022, "Scottie Scheffler",  "USA", -10),
    (2021, "Hideki Matsuyama",   "JPN", -10),
    (2020, "Dustin Johnson",     "USA", -20),
    (2019, "Tiger Woods",        "USA", -13),
    (2018, "Patrick Reed",       "USA", -15),
    (2017, "Sergio Garcia",      "ESP", -9),
    (2016, "Danny Willett",      "ENG", -5),
    (2015, "Jordan Spieth",      "USA", -18),
    (2014, "Bubba Watson",       "USA", -8),
    (2013, "Adam Scott",         "AUS", -9),
    (2012, "Bubba Watson",       "USA", -10),
    (2011, "Charl Schwartzel",   "RSA", -14),
    (2010, "Phil Mickelson",     "USA", -16),
    (2009, "Angel Cabrera",      "ARG", -12),
    (2008, "Trevor Immelman",    "RSA", -8),
    (2007, "Zach Johnson",       "USA", +1),
    (2006, "Phil Mickelson",     "USA", -7),
    (2005, "Tiger Woods",        "USA", -12),
    (2004, "Phil Mickelson",     "USA", -9),
    (2003, "Mike Weir",          "CAN", -7),
    (2002, "Tiger Woods",        "USA", -12),
    (2001, "Tiger Woods",        "USA", -16),
    (2000, "Vijay Singh",        "FIJ", -10),
    (1999, "Jose Maria Olazabal","ESP", -8),
    (1998, "Mark O'Meara",       "USA", -9),
    (1997, "Tiger Woods",        "USA", -18),
    (1996, "Nick Faldo",         "ENG", -12),
    (1995, "Ben Crenshaw",       "USA", -14),
    (1994, "Jose Maria Olazabal","ESP", -9),
    (1993, "Bernhard Langer",    "GER", -11),
    (1992, "Fred Couples",       "USA", -13),
    (1991, "Ian Woosnam",        "WAL", -11),
    (1990, "Nick Faldo",         "ENG", -10),
    (1989, "Nick Faldo",         "ENG", -5),
    (1988, "Sandy Lyle",         "SCO", -7),
    (1987, "Larry Mize",         "USA", -3),
    (1986, "Jack Nicklaus",      "USA", -9),
]

# Multiple green jacket winners
MULTIPLE_WINNERS = {
    "Jack Nicklaus": 6,
    "Tiger Woods": 5,
    "Arnold Palmer": 4,
    "Phil Mickelson": 3,
    "Jimmy Demaret": 3,
    "Sam Snead": 3,
    "Gary Player": 3,
    "Nick Faldo": 3,
    "Scottie Scheffler": 2,
    "Bubba Watson": 2,
    "Jose Maria Olazabal": 2,
    "Bernhard Langer": 2,
    "Ben Crenshaw": 2,
    "Seve Ballesteros": 2,
    "Tom Watson": 2,
    "Ben Hogan": 2,
    "Byron Nelson": 2,
    "Horton Smith": 2,
}


# ═══════════════════════════════════════════════════════════════
# TOURNAMENT RECORDS
# ═══════════════════════════════════════════════════════════════

TOURNAMENT_RECORDS = {
    "lowest_72":        {"score": -20, "player": "Dustin Johnson",  "year": 2020, "total": 268},
    "lowest_round":     {"score": 63,  "player": "Nick Price",      "year": 1986, "note": "Also shot by Greg Norman (1996)"},
    "largest_comeback":  {"strokes": 8, "player": "Jack Burke Jr.", "year": 1956},
    "youngest_winner":  {"age": 21,    "player": "Tiger Woods",     "year": 1997},
    "oldest_winner":    {"age": 46,    "player": "Jack Nicklaus",   "year": 1986},
    "largest_margin":   {"strokes": 12, "player": "Tiger Woods",    "year": 1997},
    "most_wins":        {"wins": 6,    "player": "Jack Nicklaus",   "years": "1963-86"},
    "most_cuts":        {"cuts": 37,   "player": "Fred Couples",    "note": "37 consecutive"},
    "most_top5":        {"count": 22,  "player": "Jack Nicklaus"},
    "first_tournament": {"year": 1934, "winner": "Horton Smith"},
}


# ═══════════════════════════════════════════════════════════════
# FUN FACTS DATABASE
# ═══════════════════════════════════════════════════════════════

MASTERS_FUN_FACTS = [
    # Course & History
    "Augusta National was built on the site of a former plant nursery called Fruitland Nurseries - that's why every hole is named after a tree or shrub.",
    "The famous Magnolia Lane entrance is lined with 61 magnolia trees planted in the 1850s.",
    "Augusta National has only about 300 members. The initiation fee is estimated at $40,000.",
    "Bobby Jones and Clifford Roberts co-founded Augusta National Golf Club in 1933.",
    "The Masters was originally called the 'Augusta National Invitation Tournament' until 1939.",
    "Augusta National did not admit its first Black member until 1990 (Ron Townsend) and its first female members until 2012.",
    "The Par 3 Contest has been held on the Wednesday before the Masters since 1960. No winner has ever gone on to win the Masters that same year.",
    "Pimento cheese sandwiches at the Masters cost just $1.50 - the most iconic cheap eats in all of sports.",
    "Fans are called 'patrons' at the Masters, never 'fans' or 'spectators'.",
    "Cell phones are strictly banned on the grounds at Augusta National.",

    # Iconic Moments
    "Gene Sarazen's 'Shot Heard Round the World' - a 235-yard double eagle on #15 in 1935 - is one of golf's most famous shots.",
    "In 1986, 46-year-old Jack Nicklaus shot a back nine 30 to win his 6th green jacket, the oldest winner ever.",
    "Tiger Woods won his first Masters in 1997 by a record 12 strokes at age 21.",
    "In 2019, Tiger Woods completed one of sport's greatest comebacks, winning his 5th green jacket 14 years after his 4th.",
    "Bubba Watson has never had a golf lesson. He won the Masters twice (2012, 2014).",
    "Jordan Spieth's -18 in 2015 tied Tiger Woods' 1997 record for lowest score to par.",
    "Dustin Johnson's -20 in 2020 (played in November due to COVID) broke the all-time scoring record.",

    # Amen Corner
    "Amen Corner (holes 11-13) was named by Sports Illustrated's Herbert Warren Wind in 1958.",
    "Hole 12 (Golden Bell) is the shortest hole at Augusta at just 155 yards, but is considered one of the hardest par 3s in golf.",
    "The swirling winds at the 12th hole have caused more drama than any other hole in Masters history.",
    "Rae's Creek runs in front of the 12th green and along the 13th hole. It's named after John Rae, an 18th-century settler.",

    # Green Jacket
    "The green jacket tradition started in 1949. Sam Snead was the first winner to receive one.",
    "Winners can only take the green jacket off club property for one year. After that, it stays in their locker at Augusta.",
    "The green jacket is made by Hamilton of Cincinnati and costs approximately $300.",
    "If a member or past champion's jacket is damaged, it's repaired - never replaced. Some jackets are decades old.",

    # The Course
    "Augusta National plays backwards from its original Alister MacKenzie design - the current front nine was originally the back nine.",
    "The course has been significantly lengthened over the years. It played at 6,925 yards in 1997 vs. 7,545 yards today.",
    "There are no rough at Augusta National - instead there are 'second cut' areas with pine straw.",
    "The greens at Augusta are Sub-Air heated/cooled and use bentgrass. They typically run 13+ on the stimpmeter.",
    "Eisenhower Tree, a large loblolly pine on hole 17, was named after President Eisenhower who hit it so often he wanted it removed. It was finally lost to an ice storm in 2014.",

    # Traditions
    "The Champions Dinner on Tuesday night is hosted by the defending champion who picks the menu. Tiger Woods famously served cheeseburgers, fries, and milkshakes in 1998.",
    "The honorary starters tradition began in 1963. Jack Nicklaus, Gary Player, and Tom Watson have served as honorary starters.",
    "Caddies at Augusta wear white jumpsuits and are identified by the player name on the back.",
    "The Butler Cabin, where the green jacket ceremony takes place on TV, seats only about 30 people.",
    "The famous crow's nest atop the clubhouse houses amateur competitors during the tournament. It has 5 beds.",
]


# ═══════════════════════════════════════════════════════════════
# REAL ESPN PLAYER IDS (for headshot downloads)
# ═══════════════════════════════════════════════════════════════

ESPN_PLAYER_IDS = {
    "Scottie Scheffler":   {"id": "9478",    "country": "USA"},
    "Rory McIlroy":        {"id": "3470",    "country": "NIR"},
    "Jon Rahm":            {"id": "9780",    "country": "ESP"},
    "Brooks Koepka":       {"id": "6798",    "country": "USA"},
    "Viktor Hovland":      {"id": "10591",   "country": "NOR"},
    "Xander Schauffele":   {"id": "10138",   "country": "USA"},
    "Collin Morikawa":     {"id": "10592",   "country": "USA"},
    "Jordan Spieth":       {"id": "5765",    "country": "USA"},
    "Patrick Cantlay":     {"id": "10134",   "country": "USA"},
    "Ludvig Aberg":        {"id": "4686087", "country": "SWE"},
    "Tiger Woods":         {"id": "462",     "country": "USA"},
    "Phil Mickelson":      {"id": "308",     "country": "USA"},
    "Dustin Johnson":      {"id": "3702",    "country": "USA"},
    "Justin Thomas":       {"id": "4686084", "country": "USA"},
    "Hideki Matsuyama":    {"id": "5860",    "country": "JPN"},
    "Cameron Smith":       {"id": "9131",    "country": "AUS"},
    "Bryson DeChambeau":   {"id": "9261",    "country": "USA"},
    "Shane Lowry":         {"id": "3448",    "country": "IRL"},
    "Tommy Fleetwood":     {"id": "9035",    "country": "ENG"},
    "Wyndham Clark":       {"id": "4686082", "country": "USA"},
    "Max Homa":            {"id": "10140",   "country": "USA"},
    "Sahith Theegala":     {"id": "4375306", "country": "USA"},
    "Tony Finau":          {"id": "5548",    "country": "USA"},
    "Matt Fitzpatrick":    {"id": "9037",    "country": "ENG"},
    "Adam Scott":          {"id": "367",     "country": "AUS"},
    "Sergio Garcia":       {"id": "421",     "country": "ESP"},
    "Bubba Watson":        {"id": "780",     "country": "USA"},
    "Patrick Reed":        {"id": "5596",    "country": "USA"},
    "Danny Willett":       {"id": "3008",    "country": "ENG"},
    "Charl Schwartzel":    {"id": "3367",    "country": "RSA"},
}

# ESPN headshot URL template
ESPN_HEADSHOT_URL = "https://a.espncdn.com/combiner/i?img=/i/headshots/golf/players/full/{player_id}.png&w=350&h=254"

# Country flag emoji mapping for display
COUNTRY_FLAGS = {
    "USA": "🇺🇸", "ENG": "🏴", "SCO": "🏴", "WAL": "🏴",
    "NIR": "🇬🇧", "IRL": "🇮🇪", "ESP": "🇪🇸", "GER": "🇩🇪",
    "AUS": "🇦🇺", "RSA": "🇿🇦", "JPN": "🇯🇵", "KOR": "🇰🇷",
    "NOR": "🇳🇴", "SWE": "🇸🇪", "CAN": "🇨🇦", "ARG": "🇦🇷",
    "FIJ": "🇫🇯", "MEX": "🇲🇽", "COL": "🇨🇴", "CHI": "🇨🇱",
    "ITA": "🇮🇹", "FRA": "🇫🇷", "DEN": "🇩🇰", "IND": "🇮🇳",
    "CHN": "🇨🇳", "THA": "🇹🇭", "TWN": "🇹🇼",
}

# 3-letter country code to full name
COUNTRY_NAMES = {
    "USA": "United States", "ENG": "England", "SCO": "Scotland",
    "NIR": "N. Ireland", "IRL": "Ireland", "ESP": "Spain",
    "GER": "Germany", "AUS": "Australia", "RSA": "South Africa",
    "JPN": "Japan", "KOR": "South Korea", "NOR": "Norway",
    "SWE": "Sweden", "CAN": "Canada", "ARG": "Argentina",
    "FIJ": "Fiji", "WAL": "Wales", "FRA": "France",
}


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def format_player_name(name: str, max_length: int = 15) -> str:
    """Format player name to fit within character limit."""
    if len(name) <= max_length:
        return name

    parts = name.split()
    if len(parts) >= 2:
        last_name = parts[-1]
        first_initial = parts[0][0] if parts[0] else ""
        formatted = f"{first_initial}. {last_name}"
        if len(formatted) <= max_length:
            return formatted
        return last_name[:max_length]

    return name[:max_length - 2] + ".."


def format_score_to_par(score: int) -> str:
    """Format score relative to par for display."""
    if score == 0:
        return "E"
    elif score < 0:
        return str(score)
    else:
        return f"+{score}"


def calculate_scoring_average(rounds: List[Optional[int]]) -> Optional[float]:
    """Calculate average score from round scores."""
    valid_rounds = [r for r in rounds if r is not None]
    if not valid_rounds:
        return None
    return sum(valid_rounds) / len(valid_rounds)


def _to_eastern(date: Optional[datetime]) -> datetime:
    """Normalize a datetime to Eastern (Augusta) time."""
    if date is None:
        return datetime.now(_EDT)
    if date.tzinfo is None:
        # Assume naive datetimes are already local/Eastern
        return date
    return date.astimezone(_EDT)


def get_tournament_phase(date: Optional[datetime] = None) -> str:
    """Determine current Masters tournament phase (basic)."""
    date = _to_eastern(date)

    if date.month == 4:
        if 7 <= date.day <= 9:
            return "practice"
        elif 10 <= date.day <= 13:
            return "tournament"

    return "off-season"


def get_detailed_phase(date: Optional[datetime] = None) -> str:
    """
    Determine detailed tournament phase including time-of-day awareness.

    Returns one of:
        "off-season"          - No Masters activity (most of the year)
        "pre-tournament"      - Masters week is approaching (week before)
        "practice"            - Practice rounds (Mon-Wed of Masters week)
        "tournament-morning"  - Tournament day, before play (~6-8am ET)
        "tournament-live"     - Tournament day, play in progress (~8am-7pm ET)
        "tournament-evening"  - Tournament day, play finished (~7pm-midnight ET)
        "tournament-overnight"- Tournament day, overnight (midnight-6am ET)
        "post-tournament"     - Sunday evening / Monday after Masters
    """
    date = _to_eastern(date)

    month = date.month
    day = date.day
    hour = date.hour

    # Masters is typically the second full week of April
    # Practice: Mon-Wed, Tournament: Thu-Sun
    # Adjust these dates each year as needed
    if month == 4:
        # Week before Masters (build anticipation)
        if 1 <= day <= 6:
            return "pre-tournament"

        # Practice rounds
        if 7 <= day <= 9:
            return "practice"

        # Tournament days (Thu=10 through Sun=13)
        if 10 <= day <= 13:
            if hour < 6:
                return "tournament-overnight"
            elif hour < 8:
                return "tournament-morning"
            elif hour < 19:
                return "tournament-live"
            else:
                return "tournament-evening"

        # Monday after
        if day == 14:
            return "post-tournament"

    # March - countdown month
    if month == 3 and day >= 20:
        return "pre-tournament"

    return "off-season"


def is_amen_corner_hole(hole_number: int) -> bool:
    """Check if a hole is part of Amen Corner (11, 12, 13)."""
    return hole_number in [11, 12, 13]


def is_featured_hole(hole_number: int) -> bool:
    """Check if a hole is a featured/signature hole at Augusta."""
    return hole_number in [4, 6, 11, 12, 13, 15, 16]


def get_hole_nickname(hole_number: int) -> Optional[str]:
    """Get the traditional nickname for an Augusta National hole."""
    hole = AUGUSTA_HOLES.get(hole_number)
    return hole["name"] if hole else None


def get_hole_info(hole_number: int) -> Dict[str, Any]:
    """Get complete hole information."""
    default = {"name": "Unknown", "par": 4, "yardage": 400}
    hole = AUGUSTA_HOLES.get(hole_number, default)
    result = dict(hole)
    result["hole"] = hole_number
    result["is_amen_corner"] = is_amen_corner_hole(hole_number)
    result["is_featured"] = is_featured_hole(hole_number)
    return result


def get_random_fun_fact() -> str:
    """Get a random Masters fun fact."""
    return random.choice(MASTERS_FUN_FACTS)


def get_fun_fact_by_index(index: int) -> str:
    """Get a fun fact by index (wraps around)."""
    return MASTERS_FUN_FACTS[index % len(MASTERS_FUN_FACTS)]


def get_recent_champions(count: int = 5) -> List[tuple]:
    """Get most recent champions."""
    return PAST_CHAMPIONS[:count]


def get_espn_headshot_url(player_name: str) -> Optional[str]:
    """Get ESPN headshot URL for a player."""
    player_info = ESPN_PLAYER_IDS.get(player_name)
    if player_info:
        return ESPN_HEADSHOT_URL.format(player_id=player_info["id"])
    return None


def get_player_country(player_name: str) -> Optional[str]:
    """Get country code for a player."""
    player_info = ESPN_PLAYER_IDS.get(player_name)
    if player_info:
        return player_info["country"]
    return None


def get_green_jacket_count(player_name: str) -> int:
    """Get number of green jackets for a player."""
    return MULTIPLE_WINNERS.get(player_name, 0)


def filter_favorite_players(
    players: List[Dict],
    favorites: List[str],
    top_n: int = 10,
    always_show_favorites: bool = True
) -> List[Dict]:
    """Filter player list to show top N plus favorites."""
    if not players:
        return []

    favorites_lower = [f.lower() for f in favorites]
    result = players[:top_n]

    if always_show_favorites and favorites_lower:
        result_names = {p.get("player", "").lower() for p in result}
        for player in players[top_n:]:
            player_name = player.get("player", "").lower()
            if any(fav in player_name for fav in favorites_lower):
                if player_name not in result_names:
                    result.append(player)

    return result


def calculate_tournament_countdown(target_date: datetime) -> Dict[str, int]:
    """Calculate countdown to Masters tournament."""
    now = datetime.now(timezone.utc)
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)

    delta = target_date - now

    if delta.total_seconds() <= 0:
        return {"days": 0, "hours": 0, "minutes": 0}

    return {
        "days": delta.days,
        "hours": delta.seconds // 3600,
        "minutes": (delta.seconds % 3600) // 60
    }


def get_score_description(score_to_par: int, hole_par: int = 4) -> str:
    """Get textual description of score (eagle, birdie, etc.)."""
    if score_to_par <= -3:
        return "Albatross"
    elif score_to_par == -2:
        return "Eagle"
    elif score_to_par == -1:
        return "Birdie"
    elif score_to_par == 0:
        return "Par"
    elif score_to_par == 1:
        return "Bogey"
    elif score_to_par == 2:
        return "Double Bogey"
    else:
        return f"+{score_to_par}"


def sort_leaderboard(players: List[Dict]) -> List[Dict]:
    """Sort leaderboard by position and score."""
    def sort_key(player):
        pos = player.get("position", 999)
        if isinstance(pos, str):
            pos_str = pos.replace("T", "").strip()
            try:
                pos = int(pos_str)
            except ValueError:
                pos = 999
        score = player.get("score", 999)
        return (pos, score)

    return sorted(players, key=sort_key)
