"""
Game Renderer for Hockey Scoreboard Plugin

Extracts game rendering logic into a reusable component for scroll display mode.
Returns PIL Images instead of updating display directly.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class GameRenderer:
    """
    Renders individual game cards as PIL Images for display.

    This class extracts the rendering logic from the sports manager classes
    to provide a reusable component for both switch and scroll display modes.
    """

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the GameRenderer.

        Args:
            display_width: Width of the display/game card
            display_height: Height of the display/game card
            config: Configuration dictionary
            logo_cache: Optional shared logo cache dictionary
            custom_logger: Optional custom logger instance
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logger

        # Shared logo cache for performance
        self._logo_cache = logo_cache if logo_cache is not None else {}

        # Load fonts
        self.fonts = self._load_fonts()

        # Get logo directories from config
        self.logo_dirs = {
            'nhl': config.get('nhl', {}).get('logo_dir', 'assets/sports/nhl_logos'),
            'ncaa_mens': config.get('ncaa_mens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaa_womens': config.get('ncaa_womens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaam_hockey': config.get('ncaa_mens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaaw_hockey': config.get('ncaa_womens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
        }

        # Display options
        defaults = config.get('defaults', {})
        self.show_records = defaults.get('show_records', config.get('show_records', False))
        self.show_ranking = defaults.get('show_ranking', config.get('show_ranking', False))

        # Rankings cache (populated externally)
        self._team_rankings_cache: Dict[str, int] = {}

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}

        # Get customization config
        customization = self.config.get('customization', {})

        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        rank_config = customization.get('rank_text', {})

        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10)
            fonts["time"] = self._load_custom_font(period_config, default_size=8)
            fonts["team"] = self._load_custom_font(team_config, default_size=8)
            fonts["status"] = self._load_custom_font(status_config, default_size=6)
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6)
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10)
            self.logger.debug("Successfully loaded fonts from config")
        except Exception:
            self.logger.exception("Error loading fonts, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts["time"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["team"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["status"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["detail"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["rank"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}

        return fonts

    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8) -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', 'PressStart2P-Regular.ttf')
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)

        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf'):
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    try:
                        return ImageFont.truetype(font_path, font_size)
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}")

        # Fallback to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception:
            self.logger.debug(f"Could not load fallback font from {default_font_path}")

        return ImageFont.load_default()

    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings

    def preload_logos(self, games: list, logo_dir: Path) -> None:
        """
        Pre-load team logos for all games to improve scroll performance.

        Args:
            games: List of game dictionaries
            logo_dir: Path to logo directory
        """
        for game in games:
            league = game.get('league', 'nhl')
            for team_key in ['home_abbr', 'away_abbr']:
                abbr = game.get(team_key, '')
                # Use league-aware cache key to avoid collisions across leagues
                cache_key = f"{league}_{abbr}"
                if abbr and cache_key not in self._logo_cache:
                    # Get logo path from game or resolve from logo_dir
                    logo_path_str = game.get(f'{team_key.replace("abbr", "logo_path")}')
                    if logo_path_str:
                        # Resolve relative paths using logo_dir
                        logo_path = Path(logo_path_str) if os.path.isabs(logo_path_str) else logo_dir / logo_path_str
                    else:
                        logo_path = logo_dir / f"{abbr}.png"

                    # _load_and_resize_logo handles caching with league-aware key internally
                    self._load_and_resize_logo(abbr, logo_path, league)

        self.logger.debug(f"Preloaded {len(self._logo_cache)} team logos")

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        """Get the logo path for a team based on league."""
        logo_dir = self.logo_dirs.get(league, 'assets/sports/nhl_logos')
        return Path(logo_dir) / f"{team_abbrev}.png"

    def _load_and_resize_logo(
        self,
        team_abbrev: str,
        logo_path: Optional[Path] = None,
        league: str = 'nhl'
    ) -> Optional[Image.Image]:
        """Load and resize a team logo with caching."""
        cache_key = f"{league}_{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        # Also check without league prefix for backward compatibility
        if team_abbrev in self._logo_cache:
            return self._logo_cache[team_abbrev]

        try:
            # Use provided path or get from league config
            if logo_path is None or not os.path.exists(logo_path):
                logo_path = self._get_logo_path(league, team_abbrev)

            if logo_path and os.path.exists(logo_path):
                # Use context manager to ensure file handle is closed
                with Image.open(logo_path) as logo_file:
                    # Convert creates a copy; if already RGBA, use copy() to detach from file
                    if logo_file.mode != "RGBA":
                        logo = logo_file.convert("RGBA")
                    else:
                        logo = logo_file.copy()

                # Crop transparent padding then scale so ink fills display_height.
                # thumbnail into a display_height square box preserves aspect ratio
                # and prevents wide logos from exceeding their half-card slot.
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                logo.thumbnail((self.display_height, self.display_height), RESAMPLE_FILTER)

                self._logo_cache[cache_key] = logo
                return logo
            else:
                self.logger.debug(f"Logo not found at {logo_path}")
                return None

        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
            return None

    def _draw_text_with_outline(
        self,
        draw: ImageDraw.Draw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
        fill: Tuple[int, int, int] = (255, 255, 255),
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _normalize_game_payload(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize flat game payload fields into nested structure.

        This allows render_game_card to work with both flat payloads
        (home_abbr, home_score, away_abbr, away_score at top level) and
        nested payloads (home_team/away_team/status dicts).

        Args:
            game: Game dictionary (flat or nested format)

        Returns:
            Game dictionary with normalized nested structure
        """
        # Create a copy to avoid mutating the original
        normalized = dict(game)

        # Check if we have flat fields that need normalization
        has_flat_fields = any(
            key in normalized for key in [
                'home_abbr', 'home_score', 'away_abbr', 'away_score',
                'home_name', 'away_name', 'home_record', 'away_record'
            ]
        )

        if not has_flat_fields:
            # Already in nested format or empty, return as-is
            return normalized

        # Normalize home_team
        home_team = normalized.get('home_team', {})
        if not isinstance(home_team, dict):
            home_team = {}
        # Only set values if they exist at top level and not already in nested dict
        if 'home_abbr' in normalized and not home_team.get('abbrev'):
            home_team['abbrev'] = normalized.get('home_abbr', '')
        if 'home_score' in normalized and 'score' not in home_team:
            home_team['score'] = normalized.get('home_score', '0')
        if 'home_name' in normalized and not home_team.get('name'):
            home_team['name'] = normalized.get('home_name', '')
        if 'home_record' in normalized and not home_team.get('record'):
            home_team['record'] = normalized.get('home_record', '')
        normalized['home_team'] = home_team

        # Normalize away_team
        away_team = normalized.get('away_team', {})
        if not isinstance(away_team, dict):
            away_team = {}
        if 'away_abbr' in normalized and not away_team.get('abbrev'):
            away_team['abbrev'] = normalized.get('away_abbr', '')
        if 'away_score' in normalized and 'score' not in away_team:
            away_team['score'] = normalized.get('away_score', '0')
        if 'away_name' in normalized and not away_team.get('name'):
            away_team['name'] = normalized.get('away_name', '')
        if 'away_record' in normalized and not away_team.get('record'):
            away_team['record'] = normalized.get('away_record', '')
        normalized['away_team'] = away_team

        # Normalize status
        status = normalized.get('status', {})
        if not isinstance(status, dict):
            status = {}
        if 'status_text' in normalized and not status.get('detail'):
            status['detail'] = normalized.get('status_text', '')
        if 'period' in normalized and not status.get('period'):
            status['period'] = normalized.get('period', '')
        if 'clock' in normalized and not status.get('clock'):
            status['clock'] = normalized.get('clock', '')
        if 'state' in normalized and not status.get('state'):
            status['state'] = normalized.get('state', '')
        normalized['status'] = status

        return normalized

    # ------------------------------------------------------------------
    # Favorite-team result colors for finished games.
    #
    # This is the scroll/Vegas path, and it is where the setting earns its
    # keep: a series against the same opponent scrolls past as several
    # near-identical cards, so tinting the final score green or red is the
    # only quick way to tell a win from a loss. Off by default -- the score
    # keeps the color it has today until the user opts in.
    # ------------------------------------------------------------------

    FAVORITE_RESULT_COLOR_DEFAULTS: ClassVar[Dict[str, Tuple[int, int, int]]] = {
        "win": (0, 255, 0),
        "loss": (255, 0, 0),
        "tie": (255, 200, 0),
    }

    @staticmethod
    def _coerce_rgb(value, fallback):
        """Turn a configured [R, G, B] list into a clamped (r, g, b) tuple."""
        # Checked before unpacking: a 3-character string ("123") would otherwise
        # iterate into three digits and yield a colour rather than the fallback.
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return fallback
        try:
            r, g, b = (max(0, min(255, int(channel))) for channel in value)
        except (TypeError, ValueError):
            return fallback
        return (r, g, b)

    def _favorite_teams_for(self, game: Dict[str, Any]) -> list:
        """Favorite teams that apply to this game.

        Both sources are used. Games carry the league manager's *resolved*
        favorites, which is the only place dynamic groups such as AP_TOP_25
        appear expanded; the config is read as well so an edit takes effect on
        already-fetched games, and so hand-built game dicts (tests, other
        callers) still work.
        """
        favorites = list(game.get("favorite_teams") or [])
        league_config = self.config.get(str(game.get("league", "") or ""))
        if isinstance(league_config, dict):
            favorites += list(league_config.get("favorite_teams") or [])
        else:
            favorites += list(self.config.get("favorite_teams") or [])
        return favorites

    @staticmethod
    def _side_is_favorite(game: Dict[str, Any], side: str, favorites: set) -> bool:
        """Is the home/away side of this game a favorite team?

        Reads both the flat (``home_abbr``) and nested (``home_team.abbrev``)
        payload shapes, and matches on the ESPN id too, because a couple of
        leagues (NRL) key favorites by id where abbreviations collide.
        """
        candidates = [game.get(f"{side}_abbr"), game.get(f"{side}_id")]
        team = game.get(f"{side}_team")
        if isinstance(team, dict):
            candidates += [team.get("abbrev"), team.get("abbreviation"), team.get("id")]
        for value in candidates:
            if value is not None and str(value).strip().upper() in favorites:
                return True
        return False

    @staticmethod
    def _side_score(game: Dict[str, Any], side: str) -> Optional[int]:
        """Numeric score for one side, from either payload shape."""
        raw = None
        team = game.get(f"{side}_team")
        if isinstance(team, dict) and team.get("score") is not None:
            raw = team.get("score")
        if raw is None:
            raw = game.get(f"{side}_score")
        try:
            return int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return None

    def _favorite_result(self, game: Dict[str, Any]) -> Optional[str]:
        """Say how the favorite team did in a finished game.

        Returns 'win', 'loss' or 'tie', or None when there is no single team
        to root for: no favorites configured, neither side is a favorite, or
        *both* are -- a favorite-vs-favorite game has no losing side worth
        flagging in red. Also None when the scores are not usable numbers.
        """
        favorites = {
            str(team).strip().upper()
            for team in self._favorite_teams_for(game)
            if str(team).strip()
        }
        if not favorites:
            return None

        home_fav = self._side_is_favorite(game, "home", favorites)
        away_fav = self._side_is_favorite(game, "away", favorites)
        if home_fav == away_fav:
            return None

        home_score = self._side_score(game, "home")
        away_score = self._side_score(game, "away")
        if home_score is None or away_score is None:
            return None

        if home_score == away_score:
            return "tie"
        favorite_score, other_score = (
            (home_score, away_score) if home_fav else (away_score, home_score)
        )
        return "win" if favorite_score > other_score else "loss"

    def _score_color_for(self, game: Dict[str, Any], game_type: str, default=(255, 255, 255)):
        """Fill color for a game card's score. Only finished games are tinted."""
        if game_type != "recent":
            return default
        return self._recent_score_color(game, default)

    def _recent_score_color(self, game: Dict[str, Any], default):
        """Fill color for a finished game's score, per favorite_result_colors."""
        try:
            settings = (self.config.get("customization") or {}).get(
                "favorite_result_colors"
            ) or {}
            if not settings.get("enabled", False):
                return default
            result = self._favorite_result(game)
            if result is None:
                return default
            return self._coerce_rgb(
                settings.get(f"{result}_color"),
                self.FAVORITE_RESULT_COLOR_DEFAULTS[result],
            )
        except Exception:
            self.logger.debug(
                "Could not resolve favorite result color", exc_info=True
            )
            return default

    def render_game_card(
        self,
        game: Dict[str, Any],
        game_type: str = "live"
    ) -> Image.Image:
        """
        Render a single game card as a PIL Image.

        Args:
            game: Game dictionary with team info, scores, status, etc.
            game_type: Type of game - 'live', 'recent', or 'upcoming'

        Returns:
            PIL Image of the rendered game card
        """
        # Normalize flat payload fields into nested structure if needed
        # This allows render_game_card to work with both flat and nested game dicts
        game = self._normalize_game_payload(game)

        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        # Get league for logo directory
        league = game.get('league', 'nhl')
        logo_dir = Path(self.logo_dirs.get(league, 'assets/sports/nhl_logos'))

        # Get team info (hockey uses home_team/away_team dicts)
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        home_abbr = home_team.get('abbrev', '')
        away_abbr = away_team.get('abbrev', '')

        # Load logos
        home_logo = self._load_and_resize_logo(
            home_abbr,
            logo_dir / f"{home_abbr}.png",
            league
        )
        away_logo = self._load_and_resize_logo(
            away_abbr,
            logo_dir / f"{away_abbr}.png",
            league
        )

        if not home_logo or not away_logo:
            return self._render_error_card(f"{away_abbr or '?'}@{home_abbr or '?'}")

        center_y = self.display_height // 2

        # Draw logos — each centered within a slot on its side; cap at half the card
        # width so home_slot_start stays non-negative on square/tall displays
        logo_slot = min(self.display_height, self.display_width // 2)
        away_x = (logo_slot - away_logo.width) // 2
        away_y = center_y - (away_logo.height // 2)
        main_img.paste(away_logo, (away_x, away_y), away_logo)

        home_slot_start = self.display_width - logo_slot
        home_x = home_slot_start + (logo_slot - home_logo.width) // 2
        home_y = center_y - (home_logo.height // 2)
        main_img.paste(home_logo, (home_x, home_y), home_logo)

        # Draw scores (centered) - only for live and recent games
        if game_type in ("live", "recent"):
            home_score = str(home_team.get("score", "0"))
            away_score = str(away_team.get("score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts['score'])
            score_x = (self.display_width - score_width) // 2
            score_y = (self.display_height // 2) - 3
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts['score'],
                fill=self._score_color_for(game, game_type)
            )
        elif game_type == "upcoming":
            # Draw "VS" for upcoming games
            vs_text = "VS"
            vs_width = draw_overlay.textlength(vs_text, font=self.fonts['score'])
            vs_x = (self.display_width - vs_width) // 2
            vs_y = (self.display_height // 2) - 3
            self._draw_text_with_outline(draw_overlay, vs_text, (vs_x, vs_y), self.fonts['score'])

        # Draw period/status based on game type
        if game_type == "live":
            self._draw_live_game_status(draw_overlay, game)
        elif game_type == "recent":
            self._draw_recent_game_status(draw_overlay, game)
        elif game_type == "upcoming":
            self._draw_upcoming_game_status(draw_overlay, game)

        # Draw records or rankings if enabled
        if self.show_records or self.show_ranking:
            self._draw_records_or_rankings(draw_overlay, game)

        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')

    def _render_error_card(self, message: str) -> Image.Image:
        """Render an error message card."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts['status'])
        return img

    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live hockey game."""
        # Period and Clock (Top center)
        status = game.get('status', {})
        period = status.get('period', 0)
        clock = status.get('display_clock', '')
        state = status.get('state', '')

        if state == 'in':
            period_clock_text = f"P{period} {clock}".strip()
        elif state == 'post':
            period_clock_text = "Final"
        else:
            period_clock_text = status.get('short_detail', '')

        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])

        # Draw shots on goal (optional)
        league = game.get('league', 'nhl')
        show_shots = self.config.get(league, {}).get('show_shots', False)
        if show_shots:
            shots_font = self.fonts['detail']
            home_shots = str(game.get("home_shots", "0"))
            away_shots = str(game.get("away_shots", "0"))
            shots_text = f"{away_shots}   SHOTS   {home_shots}"
            shots_bbox = draw.textbbox((0, 0), shots_text, font=shots_font)
            shots_height = shots_bbox[3] - shots_bbox[1]
            shots_y = self.display_height - shots_height - 1
            shots_width = draw.textlength(shots_text, font=shots_font)
            shots_x = (self.display_width - shots_width) // 2
            self._draw_text_with_outline(draw, shots_text, (shots_x, shots_y), shots_font)

    def _draw_recent_game_status(self, draw: ImageDraw.Draw, _game: Dict) -> None:
        """Draw status elements for a recently completed hockey game.

        Note: _game parameter reserved for future enhancements (e.g., OT indicator).
        """
        # Final status (Top center)
        status_text = "Final"
        status_width = draw.textlength(status_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), self.fonts['time'])

    def _upcoming_date_and_time(self, game: Dict) -> Tuple[str, str]:
        """Resolve (date, time) text for an upcoming game from any payload shape.

        The scroll/Vegas path feeds cards straight from the sports extractor,
        which emits flat ``game_date``/``game_time`` (already localized) and a
        ``start_time_utc`` datetime -- it has no ``status.short_detail`` and no
        ``start_time``. Reading only the nested keys is what left these cards
        showing a bare "VS": both lookups missed and each branch drew nothing.
        Prefer the flat keys, then the nested payload built by data_fetcher.py,
        then parse the raw start time as a last resort.
        """
        date_text = str(game.get("game_date", "") or "")
        time_text = str(game.get("game_time", "") or "")
        if date_text or time_text:
            return date_text, time_text

        # Nested shape (data_fetcher.py): "9/19 - 7:00 PM EDT" carries both
        # halves in one string, which overflows the card if drawn as-is.
        short_detail = str(game.get("status", {}).get("short_detail", "") or "")
        if short_detail:
            head, sep, tail = short_detail.partition(" - ")
            date_part, time_part = (head, tail) if sep else ("", head)
            return date_part.strip(), self._compact_time(time_part)

        raw_start = game.get("start_time_utc") or game.get("start_time") or ""
        if not raw_start:
            return "", ""
        try:
            if isinstance(raw_start, datetime):
                start_dt = raw_start
            else:
                start_dt = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            local_dt = start_dt.astimezone(self._display_tzinfo())
            return local_dt.strftime("%m/%d").lstrip("0"), local_dt.strftime("%I:%M%p").lstrip("0")
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Failed to parse start time '{raw_start}': {e}")
            return "", ""

    @staticmethod
    def _compact_time(text: str) -> str:
        """Trim "7:00 PM EDT" to "7:00PM" so it fits a 64px-wide half-card."""
        tokens = text.split()
        if not tokens:
            return ""
        # Drop a trailing timezone abbreviation ("EDT"), keeping the meridiem.
        if len(tokens) > 1 and tokens[-1].upper() not in {"AM", "PM"}:
            tokens = tokens[:-1]
        if len(tokens) >= 2 and tokens[-1].upper() in {"AM", "PM"}:
            return "".join(tokens[-2:])
        return tokens[-1]

    def _display_tzinfo(self):
        """Timezone for rendering raw start times; falls back to UTC."""
        try:
            configured = (self.config or {}).get("timezone")
            if configured:
                return ZoneInfo(configured)
        except Exception:
            pass
        return timezone.utc

    def _draw_upcoming_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw date/time for an upcoming hockey game.

        Matches the other sports' scroll cards: time top-center, date
        bottom-center, so the two logos are never left touching with a bare
        "VS" between them.
        """
        date_text, time_text = self._upcoming_date_and_time(game)

        if time_text:
            time_width = draw.textlength(time_text, font=self.fonts['time'])
            time_x = (self.display_width - time_width) // 2
            self._draw_text_with_outline(
                draw, time_text, (time_x, 1), self.fonts['time']
            )

        if date_text:
            date_font = self.fonts.get('detail') or self.fonts['time']
            date_width = draw.textlength(date_text, font=date_font)
            date_x = (self.display_width - date_width) // 2
            date_y = self.display_height - 7
            self._draw_text_with_outline(
                draw, date_text, (date_x, date_y), date_font
            )

    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw team records or rankings."""
        # Use configurable detail font, with fallback to hardcoded default
        record_font = self.fonts.get('detail')
        if record_font is None:
            record_font = getattr(self, '_record_font', None)
            if record_font is None:
                try:
                    record_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                except OSError:
                    record_font = ImageFont.load_default()
                self._record_font = record_font

        # Get team info (hockey uses home_team/away_team dicts)
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        away_abbr = away_team.get('abbrev', '')
        home_abbr = home_team.get('abbrev', '')
        away_record = away_team.get('record', '')
        home_record = home_team.get('record', '')

        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4

        # Away team info
        if away_abbr:
            away_text = self._get_team_display_text(away_abbr, away_record)
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)

        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, home_record)
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)

    def _get_team_display_text(self, abbr: str, record: str) -> str:
        """Get the display text for a team (ranking or record).

        Rankings take precedence over records when both are enabled.
        """
        if self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        if self.show_records:
            return record
        return ''
