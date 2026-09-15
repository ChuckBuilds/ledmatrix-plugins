"""
Olympics data layer for fetching and caching Olympics information.
"""

from .data_models import MedalCount, OlympicEvent, EventResult, OlympicsData
from .olympics_api import OlympicsDataFetcher
from .historical_stats import (
    get_historical_stats,
    format_historical_comparison,
    HistoricalStats,
)

__all__ = [
    'MedalCount',
    'OlympicEvent',
    'EventResult',
    'OlympicsData',
    'OlympicsDataFetcher',
    'get_historical_stats',
    'format_historical_comparison',
    'HistoricalStats',
]
