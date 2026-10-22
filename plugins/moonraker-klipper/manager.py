"""Native LEDMatrix Moonraker monitor: one wide-screen printer at a time."""
import io
import math
import posixpath
import time
from urllib.parse import quote, urlparse, urljoin

import requests
from PIL import Image, ImageDraw, ImageFont
from src.plugin_system.base_plugin import BasePlugin

WHITE=(235,241,250)
GREEN=(57,227,137)
BLUE=(90,190,255)
ORANGE=(255,174,55)
YELLOW=(255,218,78)
RED=(255,85,75)
MUTED=(138,154,175)
BAR=(30,44,63)

def _url(url):
    value=str(url or "").strip().rstrip("/")
    if value and "://" not in value:
        value="http://"+value
    parsed=urlparse(value)
    if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an http(s) Moonraker URL without embedded credentials")
    if parsed.port is None and not parsed.path:
        value+=":7125"
    return value

def _seconds(value):
    try:
        return max(0.0,float(value or 0))
    except (TypeError,ValueError):
        return 0.0

def _fmt(seconds):
    seconds=int(max(0,seconds))
    hours, minutes=divmod(seconds//60,60)
    return ("%dh%02dm"%(hours,minutes)) if hours else ("%dm"%minutes)

def _short(name,limit):
    return name if len(name)<=limit else name[:max(1,limit-2)]+".."

class MoonrakerKlipperPlugin(BasePlugin):
    def __init__(self,plugin_id,config,display_manager,cache_manager,plugin_manager):
        super().__init__(plugin_id,config,display_manager,cache_manager,plugin_manager)
        self.session=requests.Session()
        self.records=[]
        self.thumbnails={}
        self._thumb_job={}
        self._load(config)
        self.reset_cycle_state()

    def _load(self,config):
        self.printers=config.get("printers",[])
        self.seconds_per_printer=int(config.get("seconds_per_printer",10))
        self.refresh_seconds=int(config.get("refresh_seconds",10))
        self.show_thumbnail=bool(config.get("show_thumbnail",True))
        self.show_idle=bool(config.get("show_idle",False))
        self.show_offline=bool(config.get("show_offline",False))
        self.show_complete=bool(config.get("show_complete",True))
        self.temperature_unit=config.get("temperature_unit","C")
        self.font_sizes=config.get("font_sizes",{})
        self.colors=config.get("colors",{})
        self.preprint_threshold=float(config.get("preprint_threshold",0.01))

    def validate_config(self):
        if not super().validate_config():
            return False
        try:
            names=set()
            for p in self.config.get("printers",[]):
                name=p["name"].strip()
                if not name or name in names:
                    return False
                names.add(name)
                _url(p["url"])
            for key,size in self.config.get("font_sizes",{}).items():
                if key not in ("printer","filename","status","temperature","progress","eta") or not 6<=int(size)<=20:
                    return False
            for key,color in self.config.get("colors",{}).items():
                if key not in ("printer","filename","status","nozzle","bed","progress","progress_background","eta","preprint"):
                    return False
                if not isinstance(color,str) or len(color)!=7 or color[0]!="#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
                    return False
            return 0<=self.preprint_threshold<=0.1 and 3<=int(self.config.get("seconds_per_printer",10))<=120 and 5<=int(self.config.get("refresh_seconds",10))<=300
        except (ValueError,TypeError,KeyError,AttributeError):
            return False

    def on_config_change(self,new_config):
        super().on_config_change(new_config)
        self._load(self.config)
        self.thumbnails.clear()
        self._thumb_job.clear()
        self.records=[]
        self.reset_cycle_state()

    def get_update_interval(self):
        return self.refresh_seconds

    def supports_dynamic_duration(self):
        return True

    def get_dynamic_duration_cap(self):
        return max(10,len(self._eligible())*self.seconds_per_printer+5)

    def get_display_duration(self):
        return max(3,len(self._eligible())*self.seconds_per_printer)

    def reset_cycle_state(self):
        self._cycle_started=None
        self._cycle_names=[]
        self._cycle_complete=False

    def is_cycle_complete(self):
        return self._cycle_complete or not self._eligible()

    def has_live_content(self):
        return bool(self._eligible())

    def _eligible(self):
        allowed={"printing","paused","heating"}
        if self.show_idle:
            allowed.update(("standby","idle","ready"))
        if self.show_complete:
            allowed.add("complete")
        if self.show_offline:
            allowed.add("offline")
        return [p for p in self.records if p["state"] in allowed]

    def _headers(self,printer):
        headers={"User-Agent":"LEDMatrix-Moonraker-Klipper/1.0"}
        if printer.get("api_key"):
            headers["X-Api-Key"]=printer["api_key"]
        return headers

    def _get(self,base,path,headers,params=None):
        response=self.session.get(base+path,headers=headers,params=params,timeout=(2,5))
        response.raise_for_status()
        return response

    def _thumbnail(self,base,headers,filename):
        metadata=self._get(base,"/server/files/metadata",headers,{"filename":filename}).json().get("result",{})
        options=metadata.get("thumbnails") or []
        if not options:
            return None
        selected=min(options,key=lambda p:abs(int(p.get("width",0))-64))
        rel=selected.get("relative_path","")
        # Relative paths are resolved relative to the G-code's containing directory.
        parent=posixpath.dirname(filename)
        path=posixpath.normpath(posixpath.join(parent,rel))
        if path.startswith("../") or path.startswith("/"):
            return None
        encoded="/".join(quote(segment,safe="") for segment in path.split("/"))
        payload=self._get(base,"/server/files/gcodes/"+encoded,headers).content
        if len(payload)>2000000:
            return None
        with Image.open(io.BytesIO(payload)) as im:
            return im.convert("RGBA").copy()

    def update(self):
        records=[]
        for number,printer in enumerate(self.printers):
            if not isinstance(printer,dict) or not printer.get("enabled",True):
                continue
            name=str(printer.get("name") or ("Printer %d"%(number+1)))
            record={"name":name,"state":"offline","progress":0,"filename":"",
                    "nozzle":0,"bed":0,"target_nozzle":0,"target_bed":0,"remaining":0,"elapsed":0}
            try:
                base=_url(printer.get("url"))
                headers=self._headers(printer)
                response=self._get(base,"/printer/objects/query",headers,
                    {"print_stats":"","display_status":"","extruder":"","heater_bed":"","idle_timeout":""})
                status=response.json().get("result",{}).get("status",{})
                stats=status.get("print_stats") or {}
                extruder=status.get("extruder") or {}
                bed=status.get("heater_bed") or {}
                display_status=status.get("display_status") or {}
                progress=max(0,min(1,_seconds(display_status.get("progress"))))
                message=str(display_status.get("message") or "").strip()
                idle_state=str((status.get("idle_timeout") or {}).get("state") or "").lower()
                elapsed=_seconds(stats.get("print_duration"))
                state=str(stats.get("state") or "standby").lower()
                filename=str(stats.get("filename") or "")
                # Moonraker does not natively identify each startup macro step.
                # M117 messages (display_status.message) provide exact activity labels.
                startup=state=="printing" and progress<=self.preprint_threshold
                if startup:
                    raw=message.lower()
                    if "qgl" in raw or "quad gantry" in raw:
                        activity="QGL"
                    elif "home" in raw or "homing" in raw:
                        activity="HOMING"
                    elif "heat soak" in raw or "heatsoak" in raw or "soaking" in raw:
                        activity="HEAT SOAKING"
                    elif message:
                        activity=message
                    elif idle_state=="printing":
                        activity="PREPARING"
                    else:
                        activity="STARTING"
                else:
                    activity=""
                record.update(state=state,progress=progress,filename=filename,activity=activity,
                    nozzle=_seconds(extruder.get("temperature")),bed=_seconds(bed.get("temperature")),
                    target_nozzle=_seconds(extruder.get("target")),target_bed=_seconds(bed.get("target")),
                    elapsed=elapsed,remaining=max(0,elapsed/progress-elapsed) if progress>0.01 else 0)
                key=name+"|"+base
                if self._thumb_job.get(key)!=filename:
                    self.thumbnails.pop(key,None)
                    self._thumb_job[key]=filename
                if self.show_thumbnail and filename and key not in self.thumbnails:
                    try:
                        self.thumbnails[key]=self._thumbnail(base,headers,filename)
                    except Exception as exc:
                        self.logger.debug("Thumbnail not available for %s: %s",name,exc)
                        self.thumbnails[key]=None
                record["thumb_key"]=key
            except (requests.RequestException,ValueError,KeyError) as exc:
                self.logger.warning("Moonraker %s unavailable: %s",name,exc)
            records.append(record)
        self.records=records

    def _color(self,state):
        return {"printing":GREEN,"complete":BLUE,"paused":YELLOW,"heating":ORANGE,"offline":RED}.get(state,MUTED)

    def _temp(self,value):
        return round(value*9/5+32) if self.temperature_unit=="F" else round(value)

    @staticmethod
    def _temperature_icon(draw,x,y,kind,color):
        """Compact 7px pixel icons for the 32px-high temperature row."""
        if kind=="nozzle":
            draw.rectangle((x+1,y,x+5,y+1),fill=color)
            draw.rectangle((x+2,y+2,x+4,y+3),fill=color)
            draw.polygon([(x+2,y+4),(x+4,y+4),(x+3,y+6)],fill=color)
        else:
            draw.rectangle((x,y+2,x+7,y+3),fill=color)
            draw.point((x+1,y),fill=color)
            draw.point((x+5,y),fill=color)
            draw.line((x+2,y+5,x+2,y+6),fill=color)
            draw.line((x+5,y+5,x+5,y+6),fill=color)

    def _font(self,key,default):
        size=max(6,min(20,int(self.font_sizes.get(key,default))))
        for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(path,size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _user_color(self,key,default):
        value=self.colors.get(key)
        if isinstance(value,str) and len(value)==7 and value.startswith("#"):
            try:
                return tuple(bytes.fromhex(value[1:]))
            except ValueError:
                pass
        return default

    @staticmethod
    def _fit(draw,text,font,max_width):
        text=str(text)
        if max_width<=0:
            return ""
        while text and draw.textlength(text,font=font)>max_width:
            text=text[:-1]
        return text

    def _image(self,record,width,height):
        img=Image.new("RGB",(width,height),(0,0,0))
        d=ImageDraw.Draw(img)
        font=self._font("printer",10)
        filename_font=self._font("filename",9)
        state_font=self._font("status",9)
        progress_font=self._font("progress",9)
        temp_font=self._font("temperature",8)
        eta_font=self._font("eta",8)
        thumb_side=min(height-2,max(0,width//4))
        left=thumb_side+5
        thumb=self.thumbnails.get(record.get("thumb_key"))
        if self.show_thumbnail and thumb is not None and thumb_side:
            thumb=thumb.copy()
            thumb.thumbnail((thumb_side,thumb_side),Image.Resampling.LANCZOS)
            if thumb.mode=="RGBA":
                img.paste(thumb,((thumb_side-thumb.width)//2,(height-thumb.height)//2),thumb)
            else:
                img.paste(thumb,((thumb_side-thumb.width)//2,(height-thumb.height)//2))
        else:
            d.rectangle((2,4,max(3,thumb_side-2),max(5,height-5)),outline=BLUE)
            d.line((4,height-9,thumb_side//2,6,thumb_side-4,height-9),fill=BLUE,width=1)
        right_width=max(75,width//3)
        main_right=max(left+45,width-right_width)
        state=record["state"]
        color=self._color(state)
        d.text((left,0),self._fit(d,record["name"],font,main_right-left-2),
               fill=self._user_color("printer",WHITE),font=font)
        d.text((main_right+2,0),self._fit(d,state.upper(),state_font,width-main_right-3),
               fill=self._user_color("status",color),font=state_font)
        job=posixpath.basename(record["filename"]) or "No active job"
        d.text((left,11),self._fit(d,job,filename_font,main_right-left-3),
               fill=self._user_color("filename",MUTED),font=filename_font)

        activity=record.get("activity","")
        if activity:
            # Replace the progress bar and percentage until extrusion begins.
            preprint_color=self._user_color("preprint",YELLOW)
            d.text((left,22),self._fit(d,activity.upper(),state_font,main_right-left-2),
                   fill=preprint_color,font=state_font)
        else:
            pct=round(record["progress"]*100)
            value="%d%%"%pct
            pct_width=int(d.textlength(value,font=progress_font))+4
            bar_right=max(left+6,main_right-pct_width-2)
            d.rectangle((left,23,bar_right,27),
                        fill=self._user_color("progress_background",BAR))
            d.rectangle((left,23,left+int((bar_right-left)*record["progress"]),27),
                        fill=self._user_color("progress",color))
            d.text((bar_right+3,21),value,fill=self._user_color("progress",color),font=progress_font)

        nozzle_x=main_right+2
        nozzle_color=self._user_color("nozzle",ORANGE)
        bed_color=self._user_color("bed",BLUE)
        self._temperature_icon(d,nozzle_x,12,"nozzle",nozzle_color)
        nozzle_value="%d°"%self._temp(record["nozzle"])
        d.text((nozzle_x+8,11),nozzle_value,fill=nozzle_color,font=temp_font)
        bed_x=nozzle_x+8+int(d.textlength(nozzle_value,font=temp_font))+6
        self._temperature_icon(d,bed_x,12,"bed",bed_color)
        d.text((bed_x+9,11),"%d°"%self._temp(record["bed"]),fill=bed_color,font=temp_font)
        bottom=("ETA "+_fmt(record["remaining"])) if state=="printing" and not activity else ("STARTUP" if activity else state.upper())
        d.text((main_right+2,22),self._fit(d,bottom,eta_font,width-main_right-3),
               fill=self._user_color("eta",WHITE),font=eta_font)
        return img

    def display(self,force_clear=False):
        eligible=self._eligible()
        if not eligible:
            self._cycle_complete=True
            return
        now=time.monotonic()
        if self._cycle_started is None:
            self._cycle_started=now
            self._cycle_names=[p["name"] for p in eligible]
        names={p["name"]:p for p in eligible}
        queue=[name for name in self._cycle_names if name in names]
        if not queue:
            self._cycle_complete=True
            return
        elapsed=max(0,now-self._cycle_started)
        index=int(elapsed//self.seconds_per_printer)
        self._cycle_complete=index>=len(queue)
        record=names[queue[min(index,len(queue)-1)]]
        width,height=self.display_manager.width,self.display_manager.height
        screen=self._image(record,width,height)
        self.display_manager.clear()
        self.display_manager.image.paste(screen,(0,0))
        self.display_manager.update_display()

    def cleanup(self):
        self.session.close()
        super().cleanup()
