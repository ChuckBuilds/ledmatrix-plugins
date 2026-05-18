"""
Historical Olympics statistics.

Provides historical medal data for context and comparison.
Data covers Winter Olympics medal totals through 2022 Beijing.
"""

from dataclasses import dataclass
from typing import Dict, Optional

# Historical all-time Winter Olympics medal counts (through Beijing 2022)
# Source: Olympics.com
WINTER_OLYMPICS_ALL_TIME = {
    "NOR": {"gold": 148, "silver": 133, "bronze": 124, "total": 405, "name": "Norway"},
    "GER": {"gold": 102, "silver": 107, "bronze": 90, "total": 299, "name": "Germany"},
    "USA": {"gold": 113, "silver": 122, "bronze": 95, "total": 330, "name": "United States"},
    "AUT": {"gold": 64, "silver": 81, "bronze": 87, "total": 232, "name": "Austria"},
    "CAN": {"gold": 77, "silver": 72, "bronze": 72, "total": 221, "name": "Canada"},
    "SWE": {"gold": 65, "silver": 60, "bronze": 62, "total": 187, "name": "Sweden"},
    "SUI": {"gold": 65, "silver": 49, "bronze": 58, "total": 172, "name": "Switzerland"},
    "RUS": {"gold": 49, "silver": 50, "bronze": 52, "total": 151, "name": "Russia"},
    "FIN": {"gold": 47, "silver": 62, "bronze": 61, "total": 170, "name": "Finland"},
    "NED": {"gold": 50, "silver": 48, "bronze": 44, "total": 142, "name": "Netherlands"},
    "ITA": {"gold": 42, "silver": 41, "bronze": 52, "total": 135, "name": "Italy"},
    "FRA": {"gold": 41, "silver": 42, "bronze": 51, "total": 134, "name": "France"},
    "JPN": {"gold": 17, "silver": 28, "bronze": 27, "total": 72, "name": "Japan"},
    "CHN": {"gold": 22, "silver": 32, "bronze": 23, "total": 77, "name": "China"},
    "KOR": {"gold": 34, "silver": 21, "bronze": 18, "total": 73, "name": "South Korea"},
    "CZE": {"gold": 14, "silver": 16, "bronze": 16, "total": 46, "name": "Czechia"},
    "GBR": {"gold": 13, "silver": 6, "bronze": 17, "total": 36, "name": "Great Britain"},
    "AUS": {"gold": 7, "silver": 6, "bronze": 8, "total": 21, "name": "Australia"},
}

# Records by sport (simplified selection)
WINTER_OLYMPIC_RECORDS = {
    "speed_skating": {
        "500m_men": {"time": "33.98", "athlete": "Gao Tingyu", "country": "CHN", "year": 2022},
        "1000m_men": {"time": "1:08.94", "athlete": "Thomas Krol", "country": "NED", "year": 2022},
        "1500m_men": {"time": "1:43.21", "athlete": "Kjeld Nuis", "country": "NED", "year": 2022},
    },
    "short_track": {
        "500m_men": {"time": "39.584", "athlete": "Wu Dajing", "country": "CHN", "year": 2018},
        "1000m_men": {"time": "1:23.357", "athlete": "Hwang Dae-heon", "country": "KOR", "year": 2022},
    },
    "alpine_skiing": {
        "downhill_men": {"time": "1:42.69", "athlete": "Beat Feuz", "country": "SUI", "year": 2022},
        "slalom_men": {"time": "1:44.09", "athlete": "Clement Noel", "country": "FRA", "year": 2022},
    },
}


@dataclass
class HistoricalStats:
    """Historical statistics for a country."""
    country_code: str
    country_name: str
    all_time_gold: int
    all_time_silver: int
    all_time_bronze: int
    all_time_total: int
    all_time_rank: int


def get_historical_stats(country_code: str) -> Optional[HistoricalStats]:
    """
    Get historical statistics for a country.

    Args:
        country_code: ISO 3166-1 alpha-3 code

    Returns:
        HistoricalStats or None if country not found
    """
    code = country_code.upper()
    if code not in WINTER_OLYMPICS_ALL_TIME:
        return None

    data = WINTER_OLYMPICS_ALL_TIME[code]

    # Calculate rank
    sorted_countries = sorted(
        WINTER_OLYMPICS_ALL_TIME.items(),
        key=lambda x: (x[1]["gold"], x[1]["silver"], x[1]["bronze"]),
        reverse=True
    )
    rank = next(
        (i + 1 for i, (c, _) in enumerate(sorted_countries) if c == code),
        0
    )

    return HistoricalStats(
        country_code=code,
        country_name=data["name"],
        all_time_gold=data["gold"],
        all_time_silver=data["silver"],
        all_time_bronze=data["bronze"],
        all_time_total=data["total"],
        all_time_rank=rank
    )


def get_country_sport_history(country_code: str, sport: str) -> Dict:
    """
    Get a country's historical performance in a specific sport.

    Note: This function is a stub that returns placeholder data.
    Full implementation would require sport-specific historical data
    that is not currently included in this module.

    Args:
        country_code: ISO 3166-1 alpha-3 code
        sport: Sport name (normalized)

    Returns:
        Dict with placeholder values (all zeros/empty lists)
    """
    # Stub implementation - returns empty/zero values
    # Future implementation would require sport-specific data sources
    return {
        "country": country_code,
        "sport": sport,
        "all_time_golds": 0,
        "notable_athletes": [],
    }


def format_historical_comparison(
    country_code: str,
    current_gold: int,
) -> Optional[str]:
    """
    Format a historical comparison string.

    Example: "USA's 5th gold - now 118 all-time"

    Args:
        country_code: Country code
        current_gold: Gold medals in current games

    Returns:
        Formatted comparison string or None
    """
    stats = get_historical_stats(country_code)
    if not stats:
        return None

    new_total_gold = stats.all_time_gold + current_gold

    if current_gold == 0:
        return f"{country_code}: {new_total_gold} all-time gold"

    ordinal = _ordinal(current_gold)
    return f"{country_code}'s {ordinal} gold - {new_total_gold} all-time"


def _ordinal(n: int) -> str:
    """Convert number to ordinal string (1st, 2nd, 3rd, etc.)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def get_olympic_record(sport: str, event: str) -> Optional[Dict]:
    """
    Get the Olympic record for a specific event.

    Args:
        sport: Sport name (normalized)
        event: Event name (normalized)

    Returns:
        Record data dict or None
    """
    sport_key = sport.lower().replace(" ", "_").replace("-", "_")
    if sport_key not in WINTER_OLYMPIC_RECORDS:
        return None

    # Try to find matching event
    records = WINTER_OLYMPIC_RECORDS[sport_key]
    event_key = event.lower().replace(" ", "_").replace("'", "")

    # First try exact match
    if event_key in records:
        return records[event_key]

    # Fallback: token-based matching (all tokens in key must be in event_key or vice versa)
    event_tokens = set(event_key.split("_"))
    for key, record in records.items():
        key_tokens = set(key.split("_"))
        # Check if one set of tokens is a subset of the other
        if key_tokens.issubset(event_tokens) or event_tokens.issubset(key_tokens):
            return record

    return None
