"""ChromaClock Wide: native-width clock for ChuckBuilds LEDMatrix."""
from datetime import datetime
from zoneinfo import ZoneInfo
import colorsys
import math
import time
from PIL import Image, ImageDraw, ImageFont
from src.plugin_system.base_plugin import BasePlugin

STYLES = ("neon", "prism", "starfield", "matrix", "fire", "horizon", "binary", "minimal", "pulse", "wave", "aurora", "rain", "flap", "morph", "outline", "words", "dotgrid", "moon", "dayprogress", "world", "pong", "tetris", "aquarium", "snow", "lava", "pacman", "analog", "bighour")
PALETTES = {"cyan": ((35, 230, 255), (18, 70, 180)),
            "magenta": ((255, 65, 180), (115, 35, 205)),
            "amber": ((255, 185, 45), (170, 65, 25)),
            "green": ((76, 255, 135), (15, 125, 95))}

def scale(c, amount):
    return tuple(max(0, min(255, int(v * amount))) for v in c)

def blend(a, b, amount):
    return tuple(int(x * (1 - amount) + y * amount) for x, y in zip(a, b))

def rainbow(hue):
    return tuple(int(v * 255) for v in colorsys.hsv_to_rgb(hue % 1, .85, 1))

def get_font(size, bold=True):
    paths = (["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
             ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"])
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

class ChromaClockWidePlugin(BasePlugin):
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._load(config)
        self.current_style = "neon"
        self._last_update = 0

    def _load(self, config):
        self.style = config.get("style", "cycle")
        self.preview_mode = bool(config.get("preview_mode", False))
        self.preview_style = config.get("preview_style", "neon")
        self.cycle_seconds = max(5, int(config.get("cycle_seconds", 20)))
        self.palette = config.get("palette", "rainbow")
        self.use_24h = bool(config.get("use_24h", False))
        self.show_date = bool(config.get("show_date", True))
        self.show_seconds = bool(config.get("show_seconds", True))
        self.glow = bool(config.get("glow", True))
        self.timezone = config.get("timezone", "America/New_York")
        self.brightness = max(.15, min(1.0, float(config.get("brightness", .85))))

    def on_config_change(self, new_config):
        super().on_config_change(new_config)
        self._load(self.config)

    def update(self):
        self._last_update = time.time()

    def _now(self):
        try:
            return datetime.now(ZoneInfo(self.timezone))
        except Exception:
            return datetime.now()

    def _decor(self, draw, w, h, style, tick, accent, secondary):
        for x in range(w):
            wave = math.sin(x * .08 + tick)
            if style == "neon":
                draw.point((x, 1), fill=scale(blend(accent, secondary, (wave + 1) / 2), .65))
                draw.point((x, h - 2), fill=scale(accent, .5))
            elif style == "prism":
                color = rainbow(x / max(w, 1) + tick * .025)
                draw.line((x, 0, x, 2), fill=scale(color, .7))
                draw.line((x, h - 3, x, h - 1), fill=scale(color, .7))
            elif style == "starfield":
                if x % 5 == 0:
                    y = (x * 23 + 7) % h
                    draw.point((x, y), fill=scale(accent, .5 + .5 * math.sin(tick * 1.4 + x)))
            elif style == "matrix":
                if x % 7 == 0:
                    y = int((tick * (4 + x % 5) + x * 17) % (h + 12)) - 6
                    draw.line((x, max(0, y), x, min(h - 1, y + 4)), fill=(25, 180, 65))
            elif style == "fire":
                height = max(1, int(5 + 9 * (.5 + .5 * wave)))
                draw.line((x, h - height, x, h - 1), fill=scale(blend((255, 50, 0), (255, 200, 25), x / max(w, 1)), .65))
            elif style == "horizon":
                y = int(h * .75 + 4 * wave)
                draw.line((x, y, x, h - 1), fill=scale(secondary, .42))
            elif style == "binary":
                if x % 8 == 0:
                    for y in range(3, h - 2, 7):
                        if (x * 17 + y * 13 + int(tick * 2)) % 5 < 2:
                            draw.rectangle((x, y, x + 2, y + 2), fill=scale(accent, .55))
            elif style == "minimal":
                if x % 12 == 0:
                    draw.point((x, h - 2), fill=scale(accent, .5))
            elif style == "pulse":
                y = int(h / 2 + 9 * math.sin(x * .10 + tick * 3))
                draw.line((x, h // 2, x, y), fill=scale(accent, .6))
            elif style == "wave":
                for layer in range(3):
                    y = int(h / 2 + (layer + 1) * 3 * math.sin(x * .09 + tick * 2 + layer))
                    draw.point((x, y), fill=scale(blend(accent, secondary, layer / 3), .85))
            elif style == "aurora":
                y = int(h * .35 + 8 * math.sin(x * .04 + tick * .8))
                for layer in range(4):
                    if 0 <= y + layer * 2 < h:
                        draw.point((x, y + layer * 2), fill=scale(blend((40, 250, 175), secondary, layer / 4), .6))
            elif style == "rain":
                if x % 7 == 0:
                    y = int((tick * 12 + x * 17) % (h + 12)) - 6
                    draw.line((x, max(0, y), x, min(h - 1, y + 5)), fill=scale(accent, .65))

    def _original_style(self, draw, w, h, style, tick, now, accent, secondary):
        """Wide-screen interpretations of ChromaClock's remaining scene styles."""
        if style not in ['flap','morph','outline','words','dotgrid','moon','dayprogress','world','pong','tetris','aquarium','snow','lava','pacman','analog','bighour']:
            return
        # One continuous backdrop; the foreground clock is rendered last.
        regions = [(0, w)]
        if style == "aquarium":
            draw.line((0, h - 3, w, h - 3), fill=(40, 95, 130))
            for start, end in regions:
                for i in range(6):
                    fx = start + ((i * 37 + int(tick * (4 + i % 3))) % max(1, end - start))
                    fy = 6 + (i * 7) % max(7, h - 13)
                    direction = 1 if i % 2 else -1
                    col = [(255, 170, 60), (80, 235, 240), (255, 100, 160)][i % 3]
                    draw.ellipse((fx - 4, fy - 2, fx + 4, fy + 2), fill=col)
                    draw.polygon([(fx - 3 * direction, fy), (fx - 7 * direction, fy - 3), (fx - 7 * direction, fy + 3)], fill=col)
                    draw.point((fx + 2 * direction, fy - 1), fill=(0, 0, 0))
                for i in range(4):
                    bx = start + 9 + i * max(1, (end - start - 15) // 4)
                    by = h - 6 - ((int(tick * 5) + i * 13) % max(8, h - 8))
                    draw.ellipse((bx, by, bx + 2, by + 2), outline=(60, 140, 210))
        elif style == "pacman":
            for index, (start, end) in enumerate(regions):
                cy = h // 2
                blue = (26, 68, 250)
                # Arcade-style maze walls with pellet corridors.
                draw.rectangle((start + 1, 1, end - 2, h - 2), outline=blue, width=2)
                draw.rectangle((start + 8, 5, start + 25, 12), outline=blue)
                draw.rectangle((end - 27, h - 12, end - 9, h - 5), outline=blue)
                draw.line((start + 33, 2, start + 33, 10), fill=blue, width=2)
                draw.line((end - 34, h - 10, end - 34, h - 2), fill=blue, width=2)
                span = max(1, end - start - 16)
                px = start + 8 + int(tick * 12 + index * 23) % span
                for x in range(start + 6, end - 3, 8):
                    if abs(x - px) > 7:
                        draw.ellipse((x - 1, cy - 1, x + 1, cy + 1), fill=(245, 198, 140))
                # Mouth animated as a small triangular cut-out.
                opening = 8 + int(abs(math.sin(tick * 7)) * 35)
                draw.pieslice((px - 5, cy - 5, px + 5, cy + 5),
                              start=opening, end=360-opening, fill=(255, 222, 24))
                colors = ((250, 55, 70), (255, 175, 210),
                          (70, 240, 255), (255, 170, 45))
                for i in range(2):
                    gx = start + 10 + int(tick * (5+i) + i*29 + index*17) % max(1,end-start-20)
                    gy = 6 if i == 0 else h - 6
                    gc = colors[index*2+i]
                    # Rounded ghost head and zigzag fringe.
                    draw.ellipse((gx-4,gy-4,gx+4,gy+3), fill=gc)
                    draw.rectangle((gx-4,gy,gx+4,gy+3),fill=gc)
                    for z in range(3):
                        xx=gx-4+z*3
                        draw.polygon(((xx,gy+3),(xx+1,gy+4),(xx+3,gy+3)), fill=gc)
                    draw.rectangle((gx-3,gy-1,gx-1,gy+1),fill=(255,255,255))
                    draw.rectangle((gx+1,gy-1,gx+3,gy+1),fill=(255,255,255))
                    draw.point((gx-2,gy),fill=(15,55,220))
                    draw.point((gx+2,gy),fill=(15,55,220))
        elif style in ("analog", "bighour"):
            for start, end in regions:
                cx = (start + end) // 2
                cy = h // 2
                radius = min(h // 2 - 2, (end - start) // 2 - 3)
                if radius < 3:
                    continue
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=accent)
                if style == "bighour":
                    hour = str(now.hour % 12 or 12)
                    draw.text((cx - 4 * len(hour), cy - 5), hour, fill=accent, font=get_font(9))
                else:
                    ha = 2 * math.pi * ((now.hour % 12 + now.minute / 60) / 12) - math.pi / 2
                    ma = 2 * math.pi * ((now.minute + now.second / 60) / 60) - math.pi / 2
                    draw.line((cx, cy, cx + int(math.cos(ha) * radius * .55), cy + int(math.sin(ha) * radius * .55)), fill=accent, width=2)
                    draw.line((cx, cy, cx + int(math.cos(ma) * radius * .8), cy + int(math.sin(ma) * radius * .8)), fill=secondary)
        elif style == "pong":
            for start, end in regions:
                cy = h // 2
                ballx = start + 4 + int(abs(math.sin(tick * .75)) * max(1, end - start - 10))
                bally = 4 + int(abs(math.sin(tick * .53)) * max(1, h - 10))
                draw.line((start + 2, cy - 5 + int(math.sin(tick) * 7), start + 2, cy + 2 + int(math.sin(tick) * 7)), fill=accent, width=2)
                draw.line((end - 3, cy - 5 + int(math.cos(tick) * 7), end - 3, cy + 2 + int(math.cos(tick) * 7)), fill=secondary, width=2)
                draw.rectangle((ballx, bally, ballx + 2, bally + 2), fill=(255, 255, 255))
        elif style == "tetris":
            blocks = [[(0,0),(1,0),(0,1),(1,1)],[(0,0),(0,1),(0,2),(1,2)],[(0,0),(1,0),(2,0),(1,1)]]
            for start, end in regions:
                for i in range(8):
                    shape = blocks[i % len(blocks)]
                    px = start + 5 + (i * 17) % max(1, end - start - 16)
                    py = int((tick * (3 + i % 3) + i * 7) % (h + 14)) - 10
                    color = [(70, 215, 255),(250, 190, 60),(190, 100, 250)][i % 3]
                    for dx, dy in shape:
                        draw.rectangle((px + dx * 3, py + dy * 3, px + dx * 3 + 2, py + dy * 3 + 2), fill=color)
        elif style == "moon":
            for start, end in regions:
                cx = (start + end)//2
                cy = h//2
                radius = max(4, min(h//2 - 3, (end-start)//3))
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(225,225,185))
                phase = (now.day % 29)/29
                shadow = int(radius * (.4 + phase))
                draw.ellipse((cx-radius+shadow,cy-radius,cx+radius+shadow,cy+radius),fill=(7,12,33))
                for i in range(7):
                    x = start+(i*31+5)%max(1,end-start)
                    y = (i*11+4)%h
                    draw.point((x,y),fill=secondary)
        elif style == "snow":
            for start,end in regions:
                for i in range(34):
                    x=start+(i*37+int(math.sin(tick+i)*3))%max(1,end-start)
                    y=(i*13+int(tick*(2+i%4)))%h
                    draw.point((x,y),fill=(180,215,255))
                draw.line((start,h-2,end,h-2),fill=(90,150,200))
        elif style == "lava":
            for start,end in regions:
                for i in range(9):
                    x=start+((i*27+8)%max(1,end-start))
                    y=3+int((.5+.5*math.sin(tick*.6+i*1.7))*(h-12))
                    r=2+i%3
                    draw.ellipse((x-r,y-r,x+r,y+r),fill=blend(accent,secondary,i/9))
        elif style == "dayprogress":
            pct=(now.hour*3600+now.minute*60+now.second)/86400
            for start,end in regions:
                draw.rectangle((start+4,h//2-3,end-4,h//2+3),outline=secondary)
                fill_end=start+4+int(max(0,end-start-9)*pct)
                draw.rectangle((start+5,h//2-2,fill_end,h//2+2),fill=accent)
        elif style == "world":
            offsets=(-5,0,9,1)
            for idx,(start,end) in enumerate(regions):
                localhour=(now.hour+offsets[idx])%24
                draw.text((start+8,h//2-5),("%02d:%02d"%(localhour,now.minute)),fill=accent,font=get_font(9))
        elif style == "dotgrid":
            for start,end in regions:
                for x in range(start+3,end-2,5):
                    for y in range(3,h-2,5):
                        if (x*7+y*13+now.second)%6<3:
                            draw.point((x,y),fill=accent)
        elif style == "words":
            words=("IT IS", "NOW")
            for idx,(start,end) in enumerate(regions):
                draw.text((start+5,h//2-5),words[idx],fill=accent,font=get_font(9))
        elif style in ("flap","morph","outline"):
            for start,end in regions:
                if style=="flap":
                    for x in range(start+5,end-3,18):
                        draw.rectangle((x,4,x+13,h-5),outline=accent)
                        draw.line((x, h//2,x+13,h//2),fill=secondary)
                elif style=="morph":
                    for x in range(start+5,end-4,14):
                        height=int(3+abs(math.sin(tick*1.6+x))*(h-8))
                        draw.rectangle((x,h-height,x+8,h-4),outline=accent)
                else:
                    draw.rectangle((start+4,4,end-5,h-5),outline=accent)

    def display(self, force_clear=False):
        try:
            w, h = int(self.display_manager.width), int(self.display_manager.height)
            if w < 32 or h < 16:
                return
            tick = time.time()
            now = self._now()
            style = (self.preview_style if self.preview_mode else
                     STYLES[int(tick // self.cycle_seconds) % len(STYLES)]
                     if self.style == "cycle" else self.style)
            self.current_style = style if style in STYLES else "neon"
            if self.palette == "rainbow":
                a, b = rainbow(tick / 75), rainbow(tick / 75 + .3)
            else:
                a, b = PALETTES.get(self.palette, PALETTES["cyan"])
            a, b = scale(a, self.brightness), scale(b, self.brightness)
            if self.current_style == "fire":
                a, b = (255, 195, 45), (255, 75, 15)
            if self.current_style == "matrix":
                a, b = (65, 255, 135), (15, 95, 60)
            img = Image.new("RGB", (w, h))
            draw = ImageDraw.Draw(img)
            self._decor(draw, w, h, self.current_style, tick, a, b)
            self._original_style(draw, w, h, self.current_style, tick, now, a, b)
            text = now.strftime("%H:%M" if self.use_24h else "%I:%M")
            if not self.use_24h:
                text = text.lstrip("0") or "12:00"
            max_height = h - (12 if self.show_date else 6)
            max_width = min(int(w * .50), 205)
            size = max_height + 8
            while size > 7:
                face = get_font(size)
                bounds = draw.textbbox((0, 0), text, font=face)
                if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
                    break
                size -= 1
            x = int((w - (bounds[2] - bounds[0])) / 2 - bounds[0])
            y = int(2 - bounds[1])
            if self.glow:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    draw.text((x + dx, y + dy), text, font=face, fill=scale(b, .30))
            draw.text((x, y), text, font=face, fill=a,
                      stroke_width=1, stroke_fill=(0, 0, 0))
            if self.show_seconds:
                secface = get_font(max(8, min(11, h // 3)))
                sx = min(w - 16, x + bounds[2] - bounds[0] + 6)
                draw.text((sx, 4), now.strftime("%S"), font=secface, fill=b)
                end = int((w - 1) * (now.second + now.microsecond / 1e6) / 60)
                draw.line((0, h - 1, end, h - 1), fill=a)
            if self.show_date:
                date = now.strftime("%a %b %d").upper()
                dateface = get_font(max(7, min(10, h // 4)))
                box = draw.textbbox((0, 0), date, font=dateface)
                draw.text(((w - (box[2] - box[0])) // 2 - box[0],
                           h - 8 - box[1]), date, font=dateface,
                          fill=scale((220, 220, 240), self.brightness))
            self.display_manager.image = img
            self.display_manager.update_display()
        except Exception:
            self.logger.exception("ChromaClock Wide render failed")

    def get_info(self):
        result = super().get_info()
        result["current_style"] = self.current_style
        result["preview_mode"] = self.preview_mode
        return result
