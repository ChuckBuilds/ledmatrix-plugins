"""
Leaderboard Plugin for LEDMatrix

Displays scrolling leaderboards and standings for multiple sports leagues.
Shows team rankings, records, and statistics in a scrolling ticker format.

Features:
- Multi-sport leaderboard display (NFL, NBA, MLB, NCAA, NHL)
- Conference and division filtering
- NCAA rankings vs standings
- Scrolling ticker format with dynamic duration
- Configurable scroll speed and display options
- Background data fetching

API Version: 1.0.0
"""

import time
import logging
from typing import Dict, Any, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin
try:
    # Shared scroll pacing: resolves speed from any supported config shape,
    # snaps it to a speed the panel can show in whole pixels, and reports the
    # frame hold that keeps slow speeds crisp. Core docs: SCROLL_PERFORMANCE.md
    from src.common import scroll_config as _scroll_config
except ImportError:  # core predates the shared helper
    _scroll_config = None

from src.common.scroll_helper import ScrollHelper

from league_config import LeagueConfig
from data_fetcher import DataFetcher
from image_renderer import ImageRenderer

logger = logging.getLogger(__name__)


class LeaderboardPlugin(BasePlugin):
    """
    Leaderboard plugin for displaying sports standings and rankings.

    Supports multiple sports leagues with configurable display options,
    conference/division filtering, and scrolling ticker format.
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the leaderboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Get display dimensions
        self.display_width = display_manager.width
        self.display_height = display_manager.height
        
        # Configuration. Every config-derived setting is read by _load_config,
        # so on_config_change re-reads it exactly the same way.
        self._load_config(config)

        # Initialize components
        self.league_config = LeagueConfig(config, self.logger)
        self.data_fetcher = DataFetcher(cache_manager, self.logger, self.request_timeout)
        self.image_renderer = ImageRenderer(self.display_height, self.logger, self.appearance)

        # Initialize scroll helper. Speed, pacing and the frame hold come only
        # from the core's shared resolver; see _configure_scroll.
        self.scroll_helper = ScrollHelper(self.display_width, self.display_height, self.logger)
        self._configure_scroll()
        
        # State
        self.leaderboard_data = []
        self.last_update = 0
        self.last_warning_time = 0
        self.last_no_leagues_warning_time = 0
        self.warning_cooldown = 300  # Only warn once every 5 minutes if data is unavailable
        self.no_leagues_warning_cooldown = 300  # Only warn once every 5 minutes about no leagues enabled
        
        # Enable scrolling for high FPS
        self.enable_scrolling = True
        
        # Log enabled leagues
        enabled_leagues = self.league_config.get_enabled_leagues()
        self.logger.info("Leaderboard plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")
        self.logger.info(f"Display dimensions: {self.display_width}x{self.display_height}")
        self.logger.info("Scroll speed: %.1f px/s", self._effective_pixels_per_second())
        self.logger.info(f"Scroll mode: {'continuous' if self.loop else 'one_shot'}")
        self.logger.info(
            "Dynamic duration settings: enabled=%s, min=%ss, max=%ss, buffer=%.2f, controller_cap=%ss",
            self.dynamic_duration_enabled,
            self.min_duration,
            self.max_duration,
            self.duration_buffer,
            self.dynamic_duration_cap,
        )
        self._cycle_complete = False
        
        # Attempt initial data fetch (will use cached data if available)
        if enabled_leagues:
            self.logger.info("Attempting initial data fetch...")
            self.update(force=True)
        else:
            self.logger.warning("No leagues are enabled - leaderboard will not display any data")
    
    def _scroll_frame_hold(self) -> int:
        """Refreshes to hold each frame for, from the resolved scroll settings.

        1 without the shared helper, which is the old behaviour: a new frame
        every panel refresh.
        """
        settings = getattr(self, "_scroll_settings", None)
        return getattr(settings, "frame_hold", 1) if settings else 1

    #: How soon update() is asked for again while there is nothing to show.
    #: display() never fetches, so this is the only retry after a failed fetch;
    #: without it an ESPN outage at startup left the fallback up for a full
    #: update_interval (an hour by default).
    NO_DATA_RETRY_SECONDS = 300

    def _load_config(self, config: Dict[str, Any]) -> None:
        """Read every config-derived setting. Called from __init__ and on_config_change."""
        self.global_config = config.get('global', {}) or {}
        # update_interval is declared at the top level of the schema. The
        # global.update_interval this used to read is not in the schema, so the
        # web UI could never set it; it stays only as a fallback for hand-edited
        # configs. Default and minimum mirror config_schema.json.
        self.update_interval = self._safe_int(
            config.get('update_interval', self.global_config.get('update_interval', 3600)),
            3600, min_value=300,
        )

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        self.dynamic_duration_settings = self._load_dynamic_duration_settings(
            self.global_config.get('dynamic_duration')
        )
        self.dynamic_duration_enabled = self.dynamic_duration_settings['enabled']
        self.min_duration = self.dynamic_duration_settings['min_duration_seconds']
        self.max_duration = self.dynamic_duration_settings['max_duration_seconds']
        self.duration_buffer = self.dynamic_duration_settings['buffer_ratio']
        self.dynamic_duration_cap = self.dynamic_duration_settings['controller_cap_seconds']
        # Determine loop behavior: scroll_mode takes precedence, then loop boolean
        scroll_mode = self.global_config.get('scroll_mode', 'one_shot')
        self.loop = scroll_mode == 'continuous' or bool(self.global_config.get('loop', False))

        # Request timeout
        self.request_timeout = self.global_config.get('request_timeout', 30)
        self.appearance = self.global_config.get('appearance', {}) or {}

    def _configure_scroll(self) -> None:
        """Resolve scroll pacing through the core's shared resolver.

        The resolver reads global.display.scroll_speed / scroll_delay (pixels
        per step, seconds per step) from the block passed as global_config,
        snaps the speed to one the panel can draw in whole pixels, and applies
        it; display() passes the frame hold it reports to set_scrolling_state.
        Nothing writes the helper's speed or FPS afterwards, since that would
        override the resolved pacing.
        """
        if _scroll_config is not None:
            self._scroll_settings = _scroll_config.configure(
                self.scroll_helper,
                plugin_config=self.config,
                global_config=self.global_config,
                display_manager=self.display_manager,
                plugin_logger=self.logger,
            )
        else:
            # Unreachable on the 3.4.0 floor; the import stays guarded only
            # because the module gate does not yet list scroll_config as
            # released. The helper keeps its own default pacing.
            self._scroll_settings = None

        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer
        )

    def get_update_interval(self) -> Optional[float]:
        """Seconds between update() calls: the configured update_interval.

        The manifest's update_interval (3600) is only the default. Core prefers
        the manifest over the plugin's config, so without this hook a user's
        shorter update_interval was ignored. While nothing has been fetched,
        ask again sooner so a failed fetch is retried (NO_DATA_RETRY_SECONDS).
        Attribute reads only: core calls this on every scheduling tick.
        """
        interval = float(self.update_interval)
        if not self.leaderboard_data:
            return min(interval, float(self.NO_DATA_RETRY_SECONDS))
        return interval

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Apply a web-UI save without a restart.

        Re-reads every setting, rebuilds the league list and the renderer
        (appearance), re-runs the scroll resolver, and schedules a re-fetch.
        The fetch itself is left to update(): this runs on the web thread.
        """
        super().on_config_change(new_config)
        self._load_config(self.config)
        self.league_config = LeagueConfig(self.config, self.logger)
        self.data_fetcher.request_timeout = self.request_timeout
        self.image_renderer = ImageRenderer(self.display_height, self.logger, self.appearance)
        self._configure_scroll()
        self.scroll_helper.clear_cache()
        self._cycle_complete = False
        self.last_update = 0  # the next update() re-fetches with the new leagues
        self.logger.info(
            "Leaderboard config updated live: leagues=%s, update_interval=%ss, %.1f px/s",
            self.league_config.get_enabled_leagues(), self.update_interval,
            self._effective_pixels_per_second(),
        )

    def update(self, force: bool = False) -> None:
        """
        Update standings data for all enabled leagues.
        
        Args:
            force: If True, bypass the time check and force an update
        """
        current_time = time.time()
        
        # Check if it's time to update (unless forced). With nothing to show,
        # always fetch: the core's scheduler already spaces these calls out
        # (get_update_interval), and display() no longer fetches on its own.
        if (not force and self.leaderboard_data
                and current_time - self.last_update < self.update_interval):
            self.logger.debug(f"Skipping update - only {current_time - self.last_update:.1f}s since last update (interval: {self.update_interval}s)")
            return
        
        try:
            self.logger.info(f"Updating leaderboard data (force={force})")
            self.leaderboard_data = []
            
            # Fetch standings for each enabled league
            enabled_leagues = self.league_config.get_enabled_leagues()
            if not enabled_leagues:
                # Rate limit warning to avoid log spam
                current_time = time.time()
                if (current_time - self.last_no_leagues_warning_time) >= self.no_leagues_warning_cooldown:
                    self.logger.warning("No leagues are enabled in configuration")
                    self.last_no_leagues_warning_time = current_time
                return
            
            self.logger.info(f"Fetching data for {len(enabled_leagues)} enabled league(s): {enabled_leagues}")
            
            for league_key in enabled_leagues:
                league_config = self.league_config.get_league_config(league_key)
                if not league_config:
                    self.logger.warning(f"No configuration found for league: {league_key}")
                    continue
                
                self.logger.debug(f"Fetching standings for {league_key}")
                standings = self.data_fetcher.fetch_standings(league_config)
                
                if standings:
                    league_entry = {
                        'league': league_key,
                        'league_config': league_config,
                        'teams': standings
                    }
                    # Detect tournament data (teams have is_tournament flag from seed fetcher)
                    if any(t.get('is_tournament') for t in standings):
                        league_entry['is_tournament'] = True
                    self.leaderboard_data.append(league_entry)
                    self.logger.info(f"Successfully fetched {len(standings)} teams for {league_key}")
                else:
                    self.logger.warning(f"No standings data returned for {league_key}")
            
            self.last_update = current_time

            # Backfill any missing team logos here, off the render thread --
            # display() only ever reads local files, never downloads.
            self.image_renderer.download_missing_logos(self.leaderboard_data)

            # Clear scroll cache when data updates
            self.scroll_helper.clear_cache()
            
            total_teams = sum(len(d['teams']) for d in self.leaderboard_data)
            self.logger.info(f"Updated standings data: {len(self.leaderboard_data)} leagues, "
                           f"{total_teams} total teams")
            
            if not self.leaderboard_data:
                self.logger.error("No leaderboard data was fetched after attempting to update all enabled leagues")
            
        except Exception as e:
            self.logger.error(f"Error updating leaderboard data: {e}", exc_info=True)
    
    def display(self, force_clear: bool = False) -> None:
        """Display the scrolling leaderboard."""
        if not self.enabled:
            self.logger.debug("Leaderboard plugin is disabled")
            return
        
        if not self.leaderboard_data:
            # Never fetch from here. display() runs on the render loop, and a
            # league fetch is a blocking request with a 30s timeout: this used
            # to call update(force=True) on every frame while data was empty.
            # update() retries on the core's schedule (get_update_interval).
            current_time = time.time()
            if (current_time - self.last_warning_time) >= self.warning_cooldown:
                self.logger.warning(
                    "No leaderboard data available yet; showing fallback until update() fetches it")
                self.last_warning_time = current_time
            self.display_manager.set_scrolling_state(False)
            self._display_fallback_message()
            return
        
        # Create scrolling image if needed
        if not self.scroll_helper.cached_image or force_clear:
            self.logger.info("Creating leaderboard image...")
            self._create_leaderboard_image()
            if not self.scroll_helper.cached_image:
                self.logger.error("Failed to create leaderboard image, showing fallback")
                self.display_manager.set_scrolling_state(False)
                self._display_fallback_message()
                return
            self.logger.info("Leaderboard image created successfully")
            self._cycle_complete = False
        
        if force_clear:
            self.scroll_helper.reset_scroll()
            self._cycle_complete = False
        
        # In one-shot mode, stop scrolling once the cycle is complete
        if not self.loop and self._cycle_complete:
            self.display_manager.set_scrolling_state(False)
            return

        # Signal scrolling state
        self.display_manager.set_scrolling_state(
            True, frame_hold=self._scroll_frame_hold())
        self.display_manager.process_deferred_updates()

        # Update scroll position using the scroll helper
        self.scroll_helper.update_scroll_position()
        if self.scroll_helper.is_scroll_complete():
            if not self._cycle_complete:
                scroll_info = self.scroll_helper.get_scroll_info()
                elapsed_time = scroll_info.get('elapsed_time')
                self.logger.info(
                    "Leaderboard scroll cycle completed (elapsed=%.2fs, target=%.2fs)",
                    elapsed_time if elapsed_time is not None else -1.0,
                    scroll_info.get('dynamic_duration'),
                )
            self._cycle_complete = True
        
        # Get visible portion
        visible_portion = self.scroll_helper.get_visible_portion()
        if visible_portion:
            # Update display
            self.display_manager.image.paste(visible_portion, (0, 0))
            self.display_manager.update_display()
        
        # Log frame rate (less frequently to avoid spam)
        self.scroll_helper.log_frame_rate()
    
    def _create_leaderboard_image(self) -> None:
        """Create the scrolling leaderboard image."""
        try:
            leaderboard_image = self.image_renderer.create_leaderboard_image(self.leaderboard_data)
            
            if leaderboard_image:
                # Set up scroll helper with the image (properly initializes cached_array and state)
                self.scroll_helper.set_scrolling_image(leaderboard_image)
                # Dynamic duration is automatically calculated by set_scrolling_image()
                self._cycle_complete = False

                self.logger.info(f"Created leaderboard image: {leaderboard_image.width}x{leaderboard_image.height}")
                self.logger.info(f"Dynamic duration: {self.scroll_helper.get_dynamic_duration()}s")
                self._warn_if_content_will_be_truncated(leaderboard_image.width)
            else:
                self.logger.error("Failed to create leaderboard image")
                self.scroll_helper.clear_cache()
                
        except Exception as e:
            self.logger.error(f"Error creating leaderboard image: {e}")
            self.scroll_helper.clear_cache()
    
    #: The core's own fallback when display.dynamic_duration.max_duration_seconds
    #: is unset (DEFAULT_DYNAMIC_DURATION_CAP in src/display_controller.py).
    CORE_DEFAULT_DYNAMIC_CAP = 180.0

    def _core_dynamic_cap(self) -> float:
        """
        Read the core's global dynamic-duration cap.

        The display controller uses ``min(plugin cap, global cap)``, so the
        global value is frequently the one that decides how much of the ticker
        is actually reached. It cannot be read through ``self.global_config``
        here because this plugin reassigns that to its own config slice, so the
        core's config managers are consulted the same way BasePlugin does.
        """
        for owner in (self.plugin_manager, self.cache_manager):
            config_manager = getattr(owner, 'config_manager', None)
            if config_manager is None:
                continue
            try:
                core_config = config_manager.get_config()
            except Exception:
                # An unreadable core config must not stop the plugin loading;
                # fall through to the next source, then to the documented
                # default. Logged rather than swallowed so a persistently
                # broken config manager is diagnosable.
                self.logger.debug(
                    "Could not read core config from %s", type(owner).__name__,
                    exc_info=True,
                )
                continue
            if not isinstance(core_config, dict) or not core_config:
                continue
            cap = (core_config.get('display', {})
                   .get('dynamic_duration', {})
                   .get('max_duration_seconds'))
            try:
                cap = float(cap)
            except (TypeError, ValueError):
                return self.CORE_DEFAULT_DYNAMIC_CAP
            return cap if cap > 0 else float('inf')
        return self.CORE_DEFAULT_DYNAMIC_CAP

    def _effective_pixels_per_second(self) -> float:
        """The scroll speed the shared resolver applied, in pixels per second."""
        settings = getattr(self, '_scroll_settings', None)
        if settings is not None:
            return float(settings.pixels_per_second)
        return float(getattr(self.scroll_helper, 'scroll_speed', 0.0) or 0.0)

    def _warn_if_content_will_be_truncated(self, image_width: int) -> None:
        """
        Warn when the ticker is longer than the display controller will show.

        The controller caps a plugin's dynamic duration at
        ``min(plugin cap, core global cap)`` and moves on when that expires,
        mid-scroll. On a long list — a full 32-team league, say — that reads as
        the leaderboard simply cutting off partway through, with no error
        anywhere to explain it. Surfacing the arithmetic makes the fix obvious.
        """
        if not self.dynamic_duration_enabled:
            return

        try:
            pixels_per_second = self._effective_pixels_per_second()
            if pixels_per_second <= 0:
                return

            required = (image_width + self.display_width) / pixels_per_second
            required *= (1.0 + self.duration_buffer)

            core_cap = self._core_dynamic_cap()
            budget = min(self.max_duration, self.dynamic_duration_cap, core_cap)
            if required <= budget:
                return

            # Measure the shortfall over the same distance `required` used --
            # content plus the lead-in -- not over image_width alone. Mixing the
            # two under-reported how much is lost, and when only the safety
            # buffer pushed `required` over the budget the subtraction went
            # negative and the clamp printed the self-contradictory "roughly the
            # last 0% of the list will not be reached".
            total_travel = image_width + self.display_width
            shown_px = budget * pixels_per_second
            if shown_px >= total_travel:
                return  # fits without the buffer; not worth a warning
            limiter = ("the core's display.dynamic_duration.max_duration_seconds"
                       if core_cap <= min(self.max_duration, self.dynamic_duration_cap)
                       else "this plugin's global.dynamic_duration settings")
            self.logger.warning(
                "Leaderboard content (%dpx) needs %.0fs to scroll at %.0f px/s but the "
                "duration budget is only %.0fs (limited by %s) - roughly the last %.0f%% "
                "of the list will not be reached before the display moves on. Raise that "
                "cap, increase the scroll speed, or lower top_teams.",
                image_width, required, pixels_per_second, budget, limiter,
                100.0 * (total_travel - shown_px) / max(image_width, 1),
            )
        except Exception as e:  # pragma: no cover - diagnostics only
            self.logger.debug("Could not evaluate content duration budget: %s", e)

    def _display_fallback_message(self) -> None:
        """Display a fallback message when no data is available."""
        try:
            width = self.display_width
            height = self.display_height

            image = Image.new('RGB', (width, height), (0, 0, 0))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

            font, text = self._fit_fallback_text(draw, "No Leaderboard Data", width)

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]

            # Clamped: centring text wider than the panel started it off the
            # left edge, so both ends were cut.
            x = max(0, (width - text_width) // 2)
            y = max(0, (height - text_height) // 2)

            draw.text((x, y), text, font=font, fill=(255, 255, 255))

            self.display_manager.image = image
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying fallback message: {e}")

    def _fit_fallback_text(self, draw, text: str, max_width: int):
        """The largest font that fits ``text`` on the panel, as (font, text).

        "No Leaderboard Data" is 152px in the renderer's 8px Press Start 2P,
        wider than a 128px panel. Try the renderer's fonts, then its 4x6
        fallback face at its crisp 7px size; if even that is too wide, truncate
        with an ellipsis (the pattern news and stock-news use).
        """
        from PIL import ImageFont

        def width_of(candidate_text, font):
            return draw.textbbox((0, 0), candidate_text, font=font)[2]

        fonts = getattr(self.image_renderer, 'fonts', None) or {}
        candidates = [f for f in (fonts.get('medium'), fonts.get('small')) if f is not None]
        try:
            candidates.append(ImageFont.truetype(ImageRenderer.FALLBACK_FONT, 7))
        except (OSError, AttributeError):
            pass
        if not candidates:
            candidates = [ImageFont.load_default()]

        for font in candidates:
            if width_of(text, font) <= max_width:
                return font, text

        font = candidates[-1]
        ellipsis = ".."
        trimmed = text
        while trimmed and width_of(trimmed + ellipsis, font) > max_width:
            trimmed = trimmed[:-1]
        return font, (trimmed.rstrip() + ellipsis) if trimmed else ellipsis

    def _load_dynamic_duration_settings(self, dynamic_value: Any) -> Dict[str, Any]:
        """Normalize dynamic duration configuration with backward compatibility."""
        defaults = {
            'enabled': True,
            'min_duration_seconds': 45,
            'max_duration_seconds': 600,
            'buffer_ratio': 0.1,
            'controller_cap_seconds': 600,
        }
        settings = defaults.copy()

        if isinstance(dynamic_value, dict):
            settings['enabled'] = bool(dynamic_value.get('enabled', settings['enabled']))
            settings['min_duration_seconds'] = self._safe_int(
                dynamic_value.get('min_duration_seconds', dynamic_value.get('min_duration')),
                settings['min_duration_seconds'],
                min_value=10,
            )
            settings['max_duration_seconds'] = self._safe_int(
                dynamic_value.get('max_duration_seconds', dynamic_value.get('max_duration')),
                settings['max_duration_seconds'],
                min_value=30,
            )
            settings['buffer_ratio'] = self._safe_float(
                dynamic_value.get('buffer_ratio', dynamic_value.get('duration_buffer')),
                settings['buffer_ratio'],
                min_value=0.0,
                max_value=1.0,
            )
            settings['controller_cap_seconds'] = self._safe_int(
                dynamic_value.get('controller_cap_seconds', dynamic_value.get('max_display_time')),
                settings['controller_cap_seconds'],
                min_value=60,
            )
        elif isinstance(dynamic_value, bool):
            settings['enabled'] = dynamic_value
        elif dynamic_value is not None:
            try:
                settings['enabled'] = bool(dynamic_value)
            except (TypeError, ValueError):
                self.logger.debug("Unrecognized dynamic_duration value: %s", dynamic_value)

        # Legacy top-level overrides for existing configs
        legacy_overrides = {
            'min_duration': ('min_duration_seconds', self._safe_int, {'min_value': 10}),
            'max_duration': ('max_duration_seconds', self._safe_int, {'min_value': 30}),
            'duration_buffer': ('buffer_ratio', self._safe_float, {'min_value': 0.0, 'max_value': 1.0}),
            'max_display_time': ('controller_cap_seconds', self._safe_int, {'min_value': 60}),
        }

        for legacy_key, (target_key, converter, kwargs) in legacy_overrides.items():
            legacy_value = self.global_config.get(legacy_key)
            if legacy_value is not None:
                settings[target_key] = converter(legacy_value, settings[target_key], **kwargs)

        if settings['max_duration_seconds'] < settings['min_duration_seconds']:
            settings['max_duration_seconds'] = settings['min_duration_seconds']
        if settings['controller_cap_seconds'] < settings['max_duration_seconds']:
            settings['controller_cap_seconds'] = settings['max_duration_seconds']

        return settings

    @staticmethod
    def _safe_int(value: Any, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
        """Safely convert a value to int, enforcing optional bounds."""
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default

        if min_value is not None:
            result = max(min_value, result)
        if max_value is not None:
            result = min(max_value, result)
        return result

    @staticmethod
    def _safe_float(value: Any, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
        """Safely convert a value to float, enforcing optional bounds."""
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default

        if min_value is not None:
            result = max(min_value, result)
        if max_value is not None:
            result = min(max_value, result)
        return result

    def supports_dynamic_duration(self) -> bool:
        """Indicate whether dynamic duration is active for this plugin."""
        return self.dynamic_duration_enabled

    def get_dynamic_duration_cap(self) -> Optional[float]:
        """Provide dynamic duration cap value for the display controller."""
        if not self.dynamic_duration_enabled:
            return None
        return float(self.dynamic_duration_cap) if self.dynamic_duration_cap else None

    def reset_cycle_state(self) -> None:
        """Reset scrolling state when the display controller restarts duration timing."""
        super().reset_cycle_state()
        self._cycle_complete = False
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()

    def is_cycle_complete(self) -> bool:
        """Report whether the scrolling cycle has completed at least once."""
        if not self.dynamic_duration_enabled:
            return True
        # In continuous loop mode, never report completion so the display
        # controller keeps this plugin active until its duration expires
        if self.loop:
            return False
        return self._cycle_complete
    
    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """
        Calculate the expected cycle duration based on content width and scroll speed.
        
        This implements dynamic duration scaling where:
        - Duration is calculated from total scroll distance and scroll speed
        - Includes buffer time for smooth cycling
        - Respects min/max duration limits
        
        Args:
            display_mode: The display mode (unused for leaderboard as it has a single mode)
        
        Returns:
            Calculated duration in seconds, or None if dynamic duration is disabled or not available
        """
        # display_mode is unused but kept for API consistency with other plugins
        _ = display_mode
        if not self.dynamic_duration_enabled:
            return None
        
        # Check if we have a cached image with calculated duration
        if self.scroll_helper and self.scroll_helper.cached_image:
            try:
                dynamic_duration = self.scroll_helper.get_dynamic_duration()
                if dynamic_duration and dynamic_duration > 0:
                    self.logger.debug(
                        "get_cycle_duration() returning calculated duration: %.1fs",
                        dynamic_duration
                    )
                    return float(dynamic_duration)
            except Exception as e:
                self.logger.warning(
                    "Error getting dynamic duration from scroll helper: %s",
                    e
                )
        
        # If no cached image yet, return None (will be calculated when image is created)
        self.logger.debug("get_cycle_duration() returning None (no cached image yet)")
        return None
    
    def get_display_duration(self) -> float:
        """Get display duration from config or dynamic calculation."""
        if self.dynamic_duration_enabled and self.scroll_helper.cached_image:
            return float(self.scroll_helper.get_dynamic_duration())
        return float(self.display_duration)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        
        fetched_counts = {d['league']: len(d['teams']) for d in self.leaderboard_data}
        leagues_config = {}
        for league_key in self.league_config.get_enabled_leagues():
            league_config = self.league_config.get_league_config(league_key)
            if league_config:
                top_teams = league_config.get('top_teams', 10)
                leagues_config[league_key] = {
                    'enabled': True,
                    'top_teams': top_teams,
                    'show_all': not top_teams or top_teams <= 0,
                    'teams_displayed': fetched_counts.get(league_key, 0)
                }

        info.update({
            'total_teams': sum(len(d['teams']) for d in self.leaderboard_data),
            'enabled_leagues': self.league_config.get_enabled_leagues(),
            'last_update': self.last_update,
            'display_duration': self.get_display_duration(),
            'scroll_pixels_per_second': self._effective_pixels_per_second(),
            'dynamic_duration': self.dynamic_duration_enabled,
            'dynamic_duration_settings': self.dynamic_duration_settings,
            'dynamic_duration_cap': self.dynamic_duration_cap,
            'min_duration': self.min_duration,
            'max_duration': self.max_duration,
            'leagues_config': leagues_config,
            'appearance': {
                'pixel_perfect_text': self.image_renderer.pixel_perfect_text,
                'crisp_logos': self.image_renderer.crisp_logos,
                'text_outline': self.image_renderer.text_outline,
                'logo_scale': self.image_renderer.logo_scale,
                'font_size': self.image_renderer.fonts['large'].size,
            },
            'scroll_info': self.scroll_helper.get_scroll_info() if self.scroll_helper else None
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.leaderboard_data = []
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        self.logger.info("Leaderboard plugin cleaned up")
