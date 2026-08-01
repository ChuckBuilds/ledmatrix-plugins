"""
Countdown Plugin for LEDMatrix

Display customizable countdowns with images. Perfect for birthdays, holidays,
events, and special occasions.

Features:
- Multiple countdown entries with individual enable/disable
- Per-countdown image upload with thumbnail preview
- Configurable fonts, colors, and display settings per countdown
- Per-countdown layout: custom image/text positioning
- Adaptive time display: Days → Hours:Minutes → Minutes as event approaches
- "Until" mode (days/hours until) and "Since" mode (elapsed days)
- Automatic rotation through enabled countdowns

API Version: 1.0.0
"""

import os
import time
import uuid
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, date, time as dtime
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin
from src.logging_config import get_logger


class CountdownPlugin(BasePlugin):
    """
    Countdown display plugin for LED matrix.

    Supports multiple countdowns with per-countdown images, fonts, colors,
    layout positioning, and adaptive time granularity.
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.logger = get_logger(self.plugin_id)

        # Global display settings
        self.fit_to_display = config.get('fit_to_display', True)
        self.preserve_aspect_ratio = config.get('preserve_aspect_ratio', True)
        self.show_expired = config.get('show_expired', False)

        bg_color = config.get('background_color', [0, 0, 0])
        self.background_color = self._parse_color(bg_color, (0, 0, 0))

        # Global font settings (used when per-countdown style is not set)
        self.font_family = config.get('font_family', 'press_start')
        self.font_size = config.get('font_size', 8)
        self.font_color = self._parse_color(config.get('font_color', [255, 255, 255]), (255, 255, 255))
        # Per-element font face for the name line. None (the schema default)
        # inherits font_family, so existing configs render exactly as before.
        self.name_font_family = config.get('name_font_family', None)
        self.name_font_size = config.get('name_font_size', 8)
        self.name_font_color = self._parse_color(config.get('name_font_color', [200, 200, 200]), (200, 200, 200))

        # Countdown entries
        self.countdowns = self._normalize_countdowns(config.get('countdowns', []))
        self._countdown_signature = self._build_countdown_signature(self.countdowns)

        # Rotation state
        self.current_countdown_index = 0
        self.last_rotation_time = time.time()

        # Image cache: {countdown_id: PIL.Image}
        self.cached_images = {}
        # Countdown calculation cache: {countdown_id: dict}
        self.countdown_values = {}

        self.logger.info(f"Countdown plugin initialized with {len(self.countdowns)} countdown(s)")
        self._register_fonts()

    # ─── Color / bool helpers ────────────────────────────────────────────────

    def _parse_color(self, color_value: Any, default: Tuple[int, int, int]) -> Optional[Tuple[int, int, int]]:
        """Parse RGB color from list/tuple. Returns None if color_value is None (per-countdown override absent)."""
        if color_value is None:
            return None
        if isinstance(color_value, (list, tuple)) and len(color_value) == 3:
            try:
                result = []
                for c in color_value:
                    if isinstance(c, str):
                        c = int(float(c))
                    elif isinstance(c, float):
                        c = int(c)
                    elif not isinstance(c, int):
                        raise ValueError(f"Invalid color value type: {type(c)}")
                    if not (0 <= c <= 255):
                        raise ValueError(f"Color value {c} out of range 0-255")
                    result.append(c)
                return tuple(result)
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Invalid color values: {e}, using default")
                return default
        self.logger.warning(f"Invalid color type: {type(color_value)}, using default")
        return default

    def _parse_bool(self, value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("false", "0", "off", "no", ""):
                return False
            if normalized in ("true", "1", "on", "yes"):
                return True
            return default
        if isinstance(value, (int, float)):
            return value != 0
        return bool(value)

    # ─── ID generation ───────────────────────────────────────────────────────

    def _generate_unique_countdown_id(self, used_ids: set, preferred_id: str = "") -> str:
        candidate = preferred_id.strip()
        if candidate and candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        base = candidate if candidate else "countdown"
        suffix = 1
        while True:
            if candidate:
                unique_id = f"{base}-{suffix}"
            else:
                unique_id = f"cd_{uuid.uuid4().hex[:12]}"
            if unique_id not in used_ids:
                used_ids.add(unique_id)
                return unique_id
            suffix += 1

    # ─── Normalization ───────────────────────────────────────────────────────

    def _normalize_layout(self, raw: Any) -> Dict[str, Any]:
        d = raw if isinstance(raw, dict) else {}
        return {
            "image_x":      max(0, int(d.get("image_x", 0) or 0)),
            "image_y":      max(0, int(d.get("image_y", 0) or 0)),
            "image_width":  max(0, int(d.get("image_width", 0) or 0)),
            "image_height": max(0, int(d.get("image_height", 0) or 0)),
            "name_x":       d.get("name_x"),
            "name_y":       d.get("name_y"),
            "value_x":      d.get("value_x"),
            "value_y":      d.get("value_y"),
        }

    def _normalize_style(self, raw: Any) -> Dict[str, Any]:
        d = raw if isinstance(raw, dict) else {}
        font_color = d.get("font_color")
        name_color = d.get("name_font_color")
        bg_color   = d.get("background_color")
        return {
            "font_family":      d.get("font_family") or None,
            "font_size":        d.get("font_size") or None,
            "font_color":       self._parse_color(font_color, None) if font_color is not None else None,
            "name_font_family": d.get("name_font_family") or None,
            "name_font_size":   d.get("name_font_size") or None,
            "name_font_color":  self._parse_color(name_color, None) if name_color is not None else None,
            "background_color": self._parse_color(bg_color, None) if bg_color is not None else None,
        }

    def _normalize_countdowns(self, raw_countdowns: Any) -> List[Dict[str, Any]]:
        """Normalize countdown entries for consistent runtime behavior."""
        if not isinstance(raw_countdowns, list):
            self.logger.warning(f"Countdowns is not a list: {type(raw_countdowns)}, defaulting to empty")
            return []

        incoming_ids = {
            str(item.get("id", "")).strip()
            for item in raw_countdowns
            if isinstance(item, dict)
        }
        incoming_ids.discard("")

        used_ids = set()
        if isinstance(getattr(self, "cached_images", None), dict):
            used_ids.update(str(k) for k in self.cached_images.keys() if str(k) not in incoming_ids)
        if isinstance(getattr(self, "countdown_values", None), dict):
            used_ids.update(str(k) for k in self.countdown_values.keys() if str(k) not in incoming_ids)

        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_countdowns):
            if not isinstance(item, dict):
                self.logger.warning(f"Skipping invalid countdown item at index {index}: {item}")
                continue

            entry = dict(item)
            provided_id = str(entry.get("id", "")).strip()
            entry["id"] = self._generate_unique_countdown_id(used_ids, provided_id)
            entry["enabled"] = self._parse_bool(entry.get("enabled", True), default=True)

            try:
                entry["display_order"] = int(entry.get("display_order", 0))
            except (ValueError, TypeError):
                entry["display_order"] = 0

            entry["name"] = str(entry.get("name", "")).strip()
            entry["target_date"] = str(entry.get("target_date", "")).strip()
            entry["target_time"] = str(entry.get("target_time", "00:00") or "00:00").strip()
            entry["mode"] = entry.get("mode", "until") if entry.get("mode") in ("until", "since") else "until"
            _valid_presets = ("image-left", "image-right", "text-only", "image-only")
            entry["layout_preset"] = entry.get("layout_preset", "image-left") if entry.get("layout_preset") in _valid_presets else "image-left"
            entry["text_align"] = entry.get("text_align", "center") if entry.get("text_align") in ("left", "center", "right") else "center"

            # Migrate legacy image array format to image_path string
            image_path = entry.get("image_path")
            if not image_path:
                legacy = entry.get("image", [])
                if isinstance(legacy, list) and legacy and isinstance(legacy[0], dict):
                    image_path = legacy[0].get("path")
            entry["image_path"] = str(image_path).strip() if image_path else ""

            entry["layout"] = self._normalize_layout(entry.get("layout"))
            entry["style"]  = self._normalize_style(entry.get("style"))

            normalized.append(entry)

        normalized.sort(key=lambda x: x.get("display_order", 0))
        return normalized

    # ─── Signature (cache invalidation) ──────────────────────────────────────

    def _build_countdown_signature(self, countdowns: Optional[List[Dict[str, Any]]] = None) -> Tuple:
        if countdowns is None:
            countdowns = self.countdowns
        items = tuple(
            (
                c.get("id", ""),
                c.get("name", ""),
                c.get("target_date", ""),
                c.get("target_time", "00:00"),
                c.get("mode", "until"),
                c.get("layout_preset", "image-left"),
                c.get("text_align", "center"),
                c.get("enabled", True),
                c.get("display_order", 0),
                c.get("image_path", ""),
                tuple(sorted(c.get("layout", {}).items())),
                tuple(sorted((k, str(v)) for k, v in c.get("style", {}).items())),
            )
            for c in countdowns
        )
        return (
            self.fit_to_display,
            self.preserve_aspect_ratio,
            self.background_color,
            self.show_expired,
            items,
        )

    # ─── Font registration ────────────────────────────────────────────────────

    def _register_fonts(self):
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return
            fm = self.plugin_manager.font_manager
            fm.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.countdown_value",
                family=self.font_family,
                size_px=self.font_size,
                color=self.font_color
            )
            fm.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.countdown_name",
                family=self.name_font_family or self.font_family,
                size_px=self.name_font_size,
                color=self.name_font_color
            )
            fm.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.error",
                family="press_start",
                size_px=8,
                color=(255, 0, 0)
            )
            self.logger.info("Countdown fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    # Mirror of the core FontManager's family -> file table for the families
    # this plugin offers, used only by the cwd-independent fallback below.
    _FAMILY_FILES = {
        "press_start": "assets/fonts/PressStart2P-Regular.ttf",
        "four_by_six": "assets/fonts/4x6-font.ttf",
        "five_by_seven": "assets/fonts/5x7.bdf",
    }

    def _load_family_font_direct(self, family: str, size_px: int):
        """Load a family's font file without relying on the process cwd.

        The core FontManager resolves families via cwd-relative
        assets/fonts paths, so when the process runs from outside the core
        root (the CI safety harness does) it silently degrades to PIL's
        default bitmap font. Resolve the same file against the core install
        the display manager was loaded from instead. Returns None when the
        family is unknown or nothing loads.
        """
        rel = self._FAMILY_FILES.get(family)
        if not rel:
            return None
        cache = getattr(self, '_direct_font_cache', None)
        if cache is None:
            cache = self._direct_font_cache = {}
        key = (family, int(size_px))
        if key in cache:
            return cache[key]
        font = None
        candidates = [Path(rel)]
        try:
            import inspect
            module_path = Path(inspect.getfile(type(self.display_manager))).resolve()
            candidates.extend(ancestor / rel for ancestor in module_path.parents)
        except Exception as exc:
            self.logger.debug("Module-relative font resolution failed: %s", exc)
        for candidate in candidates:
            try:
                if candidate.exists():
                    font = ImageFont.truetype(str(candidate), int(size_px))
                    break
            except Exception as exc:
                self.logger.debug("Font candidate %s failed to load: %s", candidate, exc)
                continue
        cache[key] = font
        return font

    def _is_family_missing(self, fm, family: str) -> bool:
        """True when the FontManager's catalog can't serve this family.

        Memoized per family: the check stats the filesystem and _resolve_font
        runs on every render. The catalog only changes on core restart, so a
        cached answer stays correct for this plugin instance's lifetime.
        """
        cache = getattr(self, '_family_missing_cache', None)
        if cache is None:
            cache = self._family_missing_cache = {}
        if family in cache:
            return cache[family]
        try:
            catalog_path = getattr(fm, 'font_catalog', {}).get(family)
            missing = not catalog_path or not os.path.exists(catalog_path)
        except Exception:
            missing = False
        cache[family] = missing
        return missing

    def _resolve_font(self, countdown_id: str, role: str, family: str, size_px: int, color: Tuple):
        """Resolve a font. color is used only for registration, not resolution.

        Always returns a usable font -- never None. A missing/failing
        font_manager (e.g. under the plugin safety harness, or an
        unexpected runtime issue) used to leave name/value text silently
        undrawn (display() skips drawing when the font is None), producing
        a blank screen for an otherwise perfectly valid countdown. Falling
        back to ImageFont.load_default() means the text is always visible,
        even if not in the configured font/size.
        """
        font = None
        try:
            if hasattr(self.plugin_manager, 'font_manager') and self.plugin_manager.font_manager:
                fm = self.plugin_manager.font_manager
                # Register per-countdown key so it carries the right color, then resolve it.
                fm.register_manager_font(
                    manager_id=self.plugin_id,
                    element_key=f"{self.plugin_id}.{countdown_id}.{role}",
                    family=family,
                    size_px=size_px,
                    color=color
                )
                font = fm.resolve_font(
                    element_key=f"{self.plugin_id}.{countdown_id}.{role}",
                    family=family,
                    size_px=size_px
                )
                # When the FontManager's catalog missed this family (it scans
                # assets/fonts relative to the process cwd), resolve_font
                # silently degrades to PIL's default face — which in current
                # Pillow is itself a FreeTypeFont, so the type gives no
                # signal. Detect the miss via the catalog and prefer loading
                # the real file cwd-independently so rendering doesn't depend
                # on the working directory.
                if font is not None and self._is_family_missing(fm, family):
                    direct = self._load_family_font_direct(family, size_px)
                    if direct is not None:
                        return direct
                if font is not None:
                    return font
        except Exception as e:
            self.logger.warning(f"Error resolving font for {countdown_id}.{role}: {e}")
        direct = self._load_family_font_direct(family, size_px)
        if direct is not None:
            return direct
        return font if font is not None else ImageFont.load_default()

    # ─── Image loading ────────────────────────────────────────────────────────

    def _resolve_image_path(self, image_path: str) -> Optional[str]:
        if not image_path:
            return None
        if os.path.isabs(image_path) and os.path.exists(image_path):
            return image_path
        if os.path.exists(image_path):
            return os.path.abspath(image_path)
        project_root = Path(__file__).resolve().parent.parent.parent
        p = project_root / image_path
        if p.exists():
            return str(p)
        return image_path

    def _load_and_scale_image(self, image_path: str, target_width: int, target_height: int,
                               bg_color: Tuple[int, int, int]) -> Optional[Image.Image]:
        if not image_path:
            return None
        resolved = self._resolve_image_path(image_path)
        if not resolved or not os.path.exists(resolved):
            self.logger.warning(f"Image not found: {image_path}")
            return None
        try:
            img = Image.open(resolved)
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            if self.fit_to_display and self.preserve_aspect_ratio:
                target_size = self._calculate_fit_size(img.size, (target_width, target_height))
            elif self.fit_to_display:
                target_size = (target_width, target_height)
            else:
                target_size = img.size

            if target_size != img.size:
                img = img.resize(target_size, Image.Resampling.LANCZOS)

            canvas = Image.new('RGB', (target_width, target_height), bg_color)
            paste_x = (target_width - img.width) // 2
            paste_y = (target_height - img.height) // 2
            canvas.paste(img, (paste_x, paste_y), img)
            img.close()
            return canvas
        except Exception as e:
            self.logger.error(f"Error loading image {image_path}: {e}")
            return None

    def _calculate_fit_size(self, image_size: Tuple[int, int], display_size: Tuple[int, int]) -> Tuple[int, int]:
        iw, ih = image_size
        dw, dh = display_size
        scale = min(dw / iw, dh / ih)
        return (int(iw * scale), int(ih * scale))

    # ─── Time calculation ─────────────────────────────────────────────────────

    def _calculate_time_remaining(self, target_date_str: str,
                                   target_time_str: str = "00:00",
                                   mode: str = "until") -> Dict[str, Any]:
        """
        Calculate adaptive countdown text.

        Thresholds (until mode):
          > 2 days   → "N Days"
          1–2 days   → "Tomorrow"
          1h – 24h   → "Nh Nm"
          1m – 1h    → "Nm"
          < 1m       → "NOW!"
          past       → "Nd ago"

        Since mode mirrors: shows elapsed time using the same granularity.
        """
        try:
            target_time = datetime.strptime(target_time_str or "00:00", '%H:%M').time()
            target_dt = datetime.combine(
                datetime.strptime(target_date_str, '%Y-%m-%d').date(),
                target_time
            )
            now = datetime.now()
            delta_seconds = (target_dt - now).total_seconds()

            if mode == "since":
                elapsed = abs(delta_seconds)
                text = self._format_elapsed(elapsed)
                return {
                    'days': int(elapsed // 86400),
                    'hours': int((elapsed % 86400) // 3600),
                    'minutes': int((elapsed % 3600) // 60),
                    'total_seconds': elapsed,
                    'is_expired': False,
                    'is_today': elapsed < 86400,
                    'text': text,
                }

            # "until" mode
            if delta_seconds < 0:
                elapsed = abs(delta_seconds)
                days_ago = int(elapsed // 86400)
                return {
                    'days': days_ago,
                    'hours': 0,
                    'minutes': 0,
                    'total_seconds': delta_seconds,
                    'is_expired': True,
                    'is_today': False,
                    'text': f"{days_ago}d ago",
                }

            text = self._format_remaining(delta_seconds)
            is_today = delta_seconds < 86400
            return {
                'days': int(delta_seconds // 86400),
                'hours': int((delta_seconds % 86400) // 3600),
                'minutes': int((delta_seconds % 3600) // 60),
                'total_seconds': delta_seconds,
                'is_expired': False,
                'is_today': is_today,
                'text': text,
            }

        except Exception as e:
            self.logger.error(f"Error calculating time for {target_date_str}: {e}")
            return {'days': 0, 'hours': 0, 'minutes': 0, 'total_seconds': 0,
                    'is_expired': False, 'is_today': False, 'text': "Error"}

    def _format_remaining(self, seconds: float) -> str:
        if seconds < 60:
            return "NOW!"
        if seconds < 3600:
            return f"{int(seconds // 60)}m"
        if seconds < 86400:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
        if seconds < 172800:
            return "Tomorrow"
        return f"{int(seconds // 86400)} Days"

    def _format_elapsed(self, seconds: float) -> str:
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        if seconds < 86400:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m ago"
        days = int(seconds // 86400)
        return f"{days} Days ago"

    # ─── Rotation helpers ─────────────────────────────────────────────────────

    def _get_enabled_countdowns(self) -> List[Dict[str, Any]]:
        enabled = []
        for cd in self.countdowns:
            if not cd.get('enabled', True):
                continue
            cd_id = cd.get('id')
            if cd_id in self.countdown_values:
                is_expired = self.countdown_values[cd_id].get('is_expired', False)
                mode = cd.get('mode', 'until')
                if mode == 'until' and is_expired and not self.show_expired:
                    continue
            enabled.append(cd)
        return enabled

    def _get_current_countdown(self) -> Optional[Dict[str, Any]]:
        enabled = self._get_enabled_countdowns()
        if not enabled:
            return None
        if self.current_countdown_index >= len(enabled):
            self.current_countdown_index = 0
        return enabled[self.current_countdown_index]

    def _rotate_to_next_countdown(self) -> None:
        enabled = self._get_enabled_countdowns()
        if not enabled:
            return
        self.current_countdown_index = (self.current_countdown_index + 1) % len(enabled)
        self.last_rotation_time = time.time()

    # ─── BasePlugin lifecycle ─────────────────────────────────────────────────

    def update(self) -> None:
        try:
            for cd in self.countdowns:
                cd_id = cd.get('id')
                target_date = cd.get('target_date')
                if cd_id and target_date:
                    self.countdown_values[cd_id] = self._calculate_time_remaining(
                        target_date,
                        cd.get('target_time', '00:00'),
                        cd.get('mode', 'until')
                    )
            self.logger.debug(f"Updated {len(self.countdown_values)} countdown values")
        except Exception as e:
            self.logger.error(f"Error updating countdowns: {e}")

    def display(self, force_clear: bool = False) -> None:
        current = self._get_current_countdown()
        if not current:
            self._display_no_countdowns()
            return

        try:
            dw = self.display_manager.matrix.width
            dh = self.display_manager.matrix.height

            cd_id       = current.get('id')
            cd_name     = current.get('name', 'Countdown')
            cd_image    = current.get('image_path', '')
            layout      = current.get('layout', {})
            style       = current.get('style', {})

            # Effective style: per-countdown overrides fall back to global
            eff_font_family    = style.get('font_family')    or self.font_family
            eff_font_size      = style.get('font_size')      or self.font_size
            eff_font_color     = style.get('font_color')     or self.font_color
            # Name font face: per-countdown override → global name face → the
            # shared font_family (the pre-existing behavior when unset).
            eff_name_font_family = style.get('name_font_family') or self.name_font_family or eff_font_family
            eff_name_font_size = style.get('name_font_size') or self.name_font_size
            eff_name_color     = style.get('name_font_color')or self.name_font_color
            eff_bg             = style.get('background_color') or self.background_color

            # Layout preset + per-pixel overrides
            layout_preset = current.get('layout_preset', 'image-left')
            text_align    = current.get('text_align', 'center')

            # Pixel overrides (from advanced modal) take precedence over preset
            _has_px_override = any(layout.get(k) for k in ('image_x','image_y','image_width','image_height'))

            img_w = layout.get('image_width')  or (dw // 3)
            img_h = layout.get('image_height') or dh

            if _has_px_override:
                # User set explicit pixel positions — honour them directly
                img_x = layout.get('image_x', 0)
                img_y = layout.get('image_y', 0)
                text_area_x = img_x + img_w if cd_image else 0
                text_area_w = dw - text_area_x
            elif layout_preset == 'image-left':
                img_x, img_y = 0, 0
                text_area_x  = img_w if cd_image else 0
                text_area_w  = dw - text_area_x
            elif layout_preset == 'image-right':
                img_x, img_y = dw - img_w, 0
                text_area_x  = 0
                text_area_w  = img_x if cd_image else dw
            elif layout_preset in ('text-only', 'image-only'):
                img_x, img_y = 0, 0
                text_area_x  = 0
                text_area_w  = dw
            else:
                img_x, img_y = 0, 0
                text_area_x  = img_w if cd_image else 0
                text_area_w  = dw - text_area_x

            # Vertical position overrides or smart defaults
            name_y  = layout.get('name_y')  if layout.get('name_y')  is not None else (dh // 3)
            value_y = layout.get('value_y') if layout.get('value_y') is not None else ((dh * 2) // 3)

            # Horizontal position: respect pixel override, then derive from text_align
            if layout.get('name_x') is not None:
                name_x, value_x = layout['name_x'], layout.get('value_x', layout['name_x'])
                _text_centered  = True
            elif text_align == 'left':
                name_x = value_x = text_area_x + 4
                _text_centered  = False
            elif text_align == 'right':
                name_x = value_x = None  # computed per-text below
                _text_centered  = False
            else:  # center (default)
                name_x = value_x = text_area_x + text_area_w // 2
                _text_centered  = True

            # Build canvas
            canvas = Image.new('RGB', (dw, dh), eff_bg)

            # Draw image (skip if preset is text-only)
            show_image = bool(cd_image) and layout_preset != 'text-only'
            show_text  = layout_preset != 'image-only'

            if show_image:
                cache_key = f"{cd_id}_{layout_preset}_{img_w}_{img_h}"
                if cache_key not in self.cached_images:
                    loaded = self._load_and_scale_image(cd_image, img_w, img_h, eff_bg)
                    if loaded:
                        self.cached_images[cache_key] = loaded
                if cache_key in self.cached_images:
                    canvas.paste(self.cached_images[cache_key], (img_x, img_y))

            # Get countdown text
            cd_data = self.countdown_values.get(cd_id, {'text': '---', 'is_today': False})
            cd_text = cd_data.get('text', '---')
            is_today = cd_data.get('is_today', False)

            if force_clear:
                self.display_manager.clear()

            self.display_manager.image = canvas.copy()
            # Refresh draw context — assigning .image doesn't update .draw automatically.
            self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)

            # Resolve fonts (per-countdown scoped keys enable independent sizing)
            name_font  = self._resolve_font(cd_id, 'name',  eff_name_font_family, eff_name_font_size, eff_name_color  or (200, 200, 200))
            value_font = self._resolve_font(cd_id, 'value', eff_font_family, eff_font_size,       eff_font_color  or (255, 255, 255))

            # For "now/today" events use a bright yellow highlight
            if is_today and value_font:
                today_font = self._resolve_font(cd_id, 'value_today', eff_font_family, eff_font_size, (255, 255, 0))
                if today_font:
                    value_font = today_font

            if show_text:
                if text_align == 'right':
                    # Compute right-edge x per-text using PIL textbbox
                    def _right_x(text, font):
                        try:
                            bbox = self.display_manager.draw.textbbox((0, 0), text, font=font)
                            tw = bbox[2] - bbox[0]
                        except Exception:
                            tw = 0
                        return text_area_x + text_area_w - tw - 4

                    if name_font:
                        self.display_manager.draw_text(cd_name, x=_right_x(cd_name, name_font),  y=name_y,  font=name_font,  centered=False)
                    if value_font:
                        self.display_manager.draw_text(cd_text, x=_right_x(cd_text, value_font), y=value_y, font=value_font, centered=False)
                else:
                    if name_font:
                        self.display_manager.draw_text(cd_name, x=name_x,  y=name_y,  font=name_font,  centered=_text_centered)
                    if value_font:
                        self.display_manager.draw_text(cd_text, x=value_x, y=value_y, font=value_font, centered=_text_centered)

            self.display_manager.update_display()
            self.logger.debug(f"Displayed: {cd_name} — {cd_text} [{layout_preset}/{text_align}]")

        except Exception as e:
            self.logger.error(f"Error displaying countdown: {e}")
            self._display_error()

    def _display_no_countdowns(self) -> None:
        try:
            dw = self.display_manager.matrix.width
            dh = self.display_manager.matrix.height
            img = Image.new('RGB', (dw, dh), self.background_color)
            self.display_manager.image = img.copy()
            self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            font = self._resolve_font('_system', 'name', self.name_font_family or self.font_family,
                                       self.name_font_size,
                                       self.name_font_color or (200, 200, 200))
            if font:
                self.display_manager.draw_text("No Active",  x=dw // 2, y=dh // 3,        font=font, centered=True)
                self.display_manager.draw_text("Countdowns", x=dw // 2, y=(dh * 2) // 3,  font=font, centered=True)
            self.display_manager.update_display()
        except Exception as e:
            self.logger.error(f"Error displaying no-countdowns message: {e}")

    def _display_error(self) -> None:
        try:
            dw = self.display_manager.matrix.width
            dh = self.display_manager.matrix.height
            img = Image.new('RGB', (dw, dh), (0, 0, 0))
            self.display_manager.image = img.copy()
            self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            font = self._resolve_font('_system', 'error', 'press_start', 8, (255, 0, 0))
            if font:
                self.display_manager.draw_text("Countdown", x=dw // 2, y=dh // 3,       font=font, centered=True)
                self.display_manager.draw_text("Error",     x=dw // 2, y=(dh * 2) // 3, font=font, centered=True)
            self.display_manager.update_display()
        except Exception as e:
            self.logger.error(f"Error displaying error message: {e}")

    # ─── Duration / rotation ─────────────────────────────────────────────────

    def get_display_duration(self) -> float:
        return self.config.get('display_duration', 15.0)

    def supports_dynamic_duration(self) -> bool:
        return True

    def is_cycle_complete(self) -> bool:
        elapsed = time.time() - self.last_rotation_time
        if elapsed >= self.get_display_duration():
            self._rotate_to_next_countdown()
            return True
        return False

    def reset_cycle_state(self) -> None:
        self.last_rotation_time = time.time()

    # ─── Config management ────────────────────────────────────────────────────

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        for cd in self.countdowns:
            if not isinstance(cd, dict):
                self.logger.error(f"Countdown entry must be a dict: {cd}")
                return False
            if not cd.get('name'):
                self.logger.error(f"Countdown {cd.get('id')} missing 'name'")
                return False
            if not cd.get('target_date'):
                self.logger.error(f"Countdown {cd.get('id')} missing 'target_date'")
                return False
            try:
                datetime.strptime(cd['target_date'], '%Y-%m-%d')
            except ValueError:
                self.logger.error(f"Invalid date format for {cd.get('id')}: {cd['target_date']}")
                return False
            target_time = cd.get('target_time', '00:00') or '00:00'
            try:
                datetime.strptime(target_time, '%H:%M')
            except ValueError:
                self.logger.error(f"Invalid time format for {cd.get('id')}: {target_time}")
                return False
            if cd.get('mode') not in ('until', 'since'):
                self.logger.error(f"Invalid mode for {cd.get('id')}: {cd.get('mode')}")
                return False
        return True

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)

        old_signature = getattr(self, '_countdown_signature', None)

        self.fit_to_display      = self._parse_bool(self.config.get('fit_to_display', True), True)
        self.preserve_aspect_ratio = self._parse_bool(self.config.get('preserve_aspect_ratio', True), True)
        self.show_expired        = self._parse_bool(self.config.get('show_expired', False), False)
        self.background_color    = self._parse_color(self.config.get('background_color', [0, 0, 0]), (0, 0, 0))

        self.font_family         = self.config.get('font_family', 'press_start')
        self.font_size           = self.config.get('font_size', 8)
        self.font_color          = self._parse_color(self.config.get('font_color', [255, 255, 255]), (255, 255, 255))
        self.name_font_family    = self.config.get('name_font_family', None)
        self.name_font_size      = self.config.get('name_font_size', 8)
        self.name_font_color     = self._parse_color(self.config.get('name_font_color', [200, 200, 200]), (200, 200, 200))

        self.countdowns = self._normalize_countdowns(self.config.get('countdowns', []))
        self._register_fonts()

        self._countdown_signature = self._build_countdown_signature(self.countdowns)
        if self._countdown_signature != old_signature:
            self.cached_images.clear()
            self.current_countdown_index = 0

        self.update()
        self.logger.info(f"Config updated: {len(self.countdowns)} countdowns")

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            'countdown_count': len(self.countdowns),
            'enabled_count': len(self._get_enabled_countdowns()),
            'current_index': self.current_countdown_index,
            'cached_images': len(self.cached_images),
        })
        return info

    def cleanup(self) -> None:
        self.cached_images.clear()
        self.countdown_values.clear()
        self.logger.info("Countdown plugin cleaned up")
