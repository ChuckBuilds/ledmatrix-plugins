(function () {
 'use strict';
 if (!window.LEDMatrixWidgets) return;
 const defaults={printer:'#EBF1FA',filename:'#8A9AAF',status:'#39E389',nozzle:'#FFAE37',bed:'#5ABEFF',progress:'#39E389',progress_background:'#1E2C3F',eta:'#EBF1FA',preprint:'#FFDA4E'};
 const sizes={printer:10,filename:9,status:9,temperature:8,progress:9,eta:8};
 const pickers=new Set();
 const colorValues=new Map();
 const widgetById=new Map();
 const listeners=new Set();
 const notify=()=>{for(const listener of listeners)listener();};
 const keyOf=(el)=>String(el?.getAttribute('name')||el?.id||el?.closest('[data-field]')?.getAttribute('data-field')||'');
 const matches=(id,key)=>id===key||id.endsWith('.'+key)||id.endsWith('['+key+']')||id.endsWith('_'+key);
 function widgetColor(container,config,value,options){
   const id=String(options?.fieldId||container.id||'');
   const fullKey=String(options?.fullKey||id);
   const key=Object.keys(defaults).sort((a,b)=>b.length-a.length).find(k=>matches(fullKey,k)||matches(id,k)||fullKey.replace(/-/g,'_').endsWith(k))||'printer';
   const input=document.createElement('input');input.type='color';
   input.value=/^#[0-9a-f]{6}$/i.test(value||'')?value:defaults[key];
   input.style.cssText='height:34px;width:72px;cursor:pointer;padding:2px;border:1px solid #64748b;border-radius:6px;background:transparent';
   input.setAttribute('aria-label','Choose '+key.replaceAll('_',' ')+' color');
   container.replaceChildren(input);
   container.__moonColorInput=input;container.__moonColorKey=key;
   pickers.add(container);
   colorValues.set(key,input.value);
   widgetById.set(id,{input,key,container});
   const changed=()=>{colorValues.set(key,input.value);notify();document.dispatchEvent(new CustomEvent('widget-change',{detail:{fieldId:id,value:input.value},bubbles:true}));container.dispatchEvent(new Event('moonraker-setting-change',{bubbles:true}));};
   input.addEventListener('input',changed);
   input.addEventListener('change',changed);
 }
 function preview(container,config,value,options){
   let currentConfig=config||{};
   const root=document.createElement('div');root.style.cssText='display:grid;gap:10px;max-width:980px';
   const heading=document.createElement('strong');heading.textContent='Moonraker-Klipper · Live Settings Preview (320 × 32)';
   const top=document.createElement('div');top.style.cssText='display:flex;flex-wrap:wrap;align-items:center;gap:10px';
   const printerSelect=document.createElement('select'),stateSelect=document.createElement('select'),stageSelect=document.createElement('select');
   for(const v of ['printing','startup','paused','complete','standby','offline']){const o=document.createElement('option');o.value=v;o.textContent=v.toUpperCase();stateSelect.append(o);}
   for(const v of ['HOMING','QGL','HEAT SOAKING','PREPARING']){const o=document.createElement('option');o.value=v;o.textContent=v;stageSelect.append(o);}
   const button=document.createElement('button');button.type='button';button.textContent='Next printer';
   const auto=document.createElement('input');auto.type='checkbox';
   const canvas=document.createElement('canvas');canvas.width=320;canvas.height=32;canvas.style.cssText='width:100%;max-width:960px;image-rendering:pixelated;background:#000;border:1px solid #475569;border-radius:6px';
   const message=document.createElement('small');message.style.cssText='opacity:.8';
   const label=(text,control)=>{const l=document.createElement('label');l.textContent=text+' ';l.append(control);return l;};
   top.append(label('Printer',printerSelect),label('Example state',stateSelect),label('Startup stage',stageSelect),button,label('Auto-cycle',auto));
   root.append(heading,top,canvas,message);container.replaceChildren(root);
   const ctx=canvas.getContext('2d');if(!ctx)return;
   const form=container.closest('form')||document;
   let geometry={width:320,height:32,source:'fallback'};
   const geometryLabel=document.createElement('small');root.insertBefore(geometryLabel,canvas);
   async function loadGeometry(){
     try {
       const response=await fetch('/api/v3/config/main',{credentials:'same-origin'});
       if(!response.ok)return;
       const payload=await response.json();
       const display=(payload.data||{}).display||{};
       const hw=display.hardware||display;
       const rows=Math.max(1,Number(hw.rows||32));
       const cols=Math.max(1,Number(hw.cols||64));
       const chain=Math.max(1,Number(hw.chain_length||1));
       const parallel=Math.max(1,Number(hw.parallel||1));
       let width=cols*chain,height=rows*parallel;
       if([90,270].includes(Number(hw.rotation||hw.rotate||0))){const t=width;width=height;height=t;}
       if(width<=2048&&height<=1024)geometry={width,height,source:'LEDMatrix configuration'};
       draw();
     }catch(error){console.warn('[Moonraker Preview] Could not read geometry',error);}
   }
   void loadGeometry();
   const fields=()=>Array.from(form.querySelectorAll('input,select,textarea'));
   function lookup(path){
     for(const section of form.querySelectorAll('[data-setting-key]')){
       if(section.getAttribute('data-setting-key')===path){
         const input=section.querySelector('input[name],select[name],textarea[name]');
         if(input)return input;
       }
     }
     const flat=path.replace(/[._]/g,'-');
     return fields().find(el=>[path,flat].includes(keyOf(el))||keyOf(el).endsWith('-'+flat)||el.name===path)||null;
   }
   function setting(path,fallback){
     const el=lookup(path);
     if(el)return el.type==='checkbox'?el.checked:el.value;
     const parts=path.split('.');let obj=currentConfig;
     for(const part of parts){if(!obj||typeof obj!=='object')return fallback;obj=obj[part];}
     return obj===undefined?fallback:obj;
   }
   function color(key){
     for(const section of form.querySelectorAll('[data-setting-key]')){
       if(section.getAttribute('data-setting-key')!=='colors.'+key)continue;
       const input=section.querySelector('input[type=color]');
       if(input&&/^#[0-9a-f]{6}$/i.test(input.value))return input.value;
       const named=section.querySelector('input[name]');
       if(named&&/^#[0-9a-f]{6}$/i.test(named.value))return named.value;
     }
     return colorValues.get(key)||setting('colors.'+key,defaults[key]);
   }
   function size(key){return Math.min(20,Math.max(6,Number(setting('font_sizes.'+key,sizes[key]))||sizes[key]));}
   function text(value,x,y,k,colorKey,limit){
     const fontSize=size(k);ctx.font=fontSize+'px monospace';ctx.textBaseline='top';
     let s=String(value);while(s&&ctx.measureText(s).width>limit)s=s.slice(0,-1);
     ctx.fillStyle=color(colorKey);ctx.fillText(s,x,y);
   }
   function readPrinters(){
     const fromConfig=setting('printers',[]);
     // Some LEDMatrix forms serialize the printers as JSON in a textarea.
     if(typeof fromConfig==='string'){try{const parsed=JSON.parse(fromConfig);if(Array.isArray(parsed))return parsed;}catch(e){}}
     if(Array.isArray(fromConfig))return fromConfig;
     return [];
   }
   let index=0,previousTime=Date.now();
   function draw(){
     if(!container.isConnected){clearInterval(timer);listeners.delete(draw);return;}
     const printers=readPrinters().filter(p=>p&&p.enabled!==false);
     const list=printers.length?printers:[{name:'VORON 2.4',enabled:true}];
     if(index>=list.length)index=0;
     const p=list[index],mode=stateSelect.value;
     printerSelect.replaceChildren();
     list.forEach((it,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=it.name||('Printer '+(i+1));printerSelect.append(o);});
     printerSelect.value=String(index);
     const interval=Math.max(3,Number(setting('seconds_per_printer',10))||10);
     const refresh=Math.max(5,Number(setting('refresh_seconds',10))||10);
     const thumbnail=setting('show_thumbnail',true);
     const W=geometry.width,H=geometry.height;
     if(canvas.width!==W||canvas.height!==H){canvas.width=W;canvas.height=H;}
     geometryLabel.textContent='Display preview '+W+' × '+H+' px · '+geometry.source;
     const c=ctx;c.fillStyle='#000';c.fillRect(0,0,W,H);
     c.save();c.scale(W/320,H/32);
     const left=thumbnail?36:5,right=215;
     if(thumbnail){
       c.fillStyle='#132331';c.fillRect(1,1,30,30);
       c.fillStyle='#60b9ed';c.fillRect(10,6,12,3);c.fillRect(12,9,8,15);
       c.fillStyle='#8addf1';c.fillRect(8,24,16,3);
     }
     text(p.name||'Printer',left,0,'printer','printer',right-left-3);
     text(mode==='startup'?'PRINTING':mode.toUpperCase(),right+2,0,'status','status',102);
     text(mode==='standby'||mode==='offline'?'No active job':'Dragon_Print.gcode',left,11,'filename','filename',right-left-4);
     const progress=mode==='complete'?100:mode==='paused'?42:68;
     if(mode==='startup'){
       text(stageSelect.value,left,22,'status','preprint',right-left-3);
     }else{
       const barWidth=Math.max(10,right-left-48);
       c.fillStyle=color('progress_background');c.fillRect(left,23,barWidth,5);
       c.fillStyle=color('progress');c.fillRect(left,23,Math.round(barWidth*progress/100),5);
       text(progress+'%',left+barWidth+4,21,'progress','progress',41);
     }
     const unit=setting('temperature_unit','C');
     const temp=n=>unit==='F'?Math.round(n*9/5+32):n;
     c.fillStyle=color('nozzle');c.fillRect(217,12,5,2);c.fillRect(219,14,2,4);
     text(temp(235)+'°',224,10,'temperature','nozzle',35);
     c.fillStyle=color('bed');c.fillRect(260,14,8,2);c.fillRect(262,17,1,2);
     text(temp(65)+'°',271,10,'temperature','bed',46);
     text(mode==='startup'?'STARTUP':mode==='printing'?'ETA 1h24m':mode.toUpperCase(),217,22,'eta','eta',102);
     const enabled=setting('enabled',true);
     const showMode=mode==='standby'?setting('show_idle',false):mode==='offline'?setting('show_offline',false):mode==='complete'?setting('show_complete',true):true;
     c.restore();
     message.textContent=(enabled&&showMode?'':'Skipped by display filters · ')+(printers.length?list.length+' configured enabled printer(s)':'Sample printer · no printers configured')+
       ' · '+interval+'s per printer · '+refresh+'s polling · '+unit+
       ' · thumbnail '+(thumbnail?'on':'off')+
       ' · startup threshold '+Number(setting('preprint_threshold',.01))*100+'%'+
       ' · dynamic rotation '+(setting('dynamic_duration.enabled',true)?'on':'off')+
       ' · display duration '+setting('display_duration',30)+'s · preview uses sample telemetry; unsaved styling shown';
   }
   const change=()=>{index=Math.max(0,Number(printerSelect.value)||0);draw();};
   printerSelect.addEventListener('change',change);
   stateSelect.addEventListener('change',draw);stageSelect.addEventListener('change',draw);
   button.addEventListener('click',()=>{index++;draw();});
   auto.addEventListener('change',()=>{previousTime=Date.now();draw();});
   form.addEventListener('input',draw);form.addEventListener('change',draw);
   form.addEventListener('moonraker-setting-change',draw);
   document.addEventListener('widget-change',draw);
   document.addEventListener('widget-change',draw);
   listeners.add(draw);
   // MutationObserver responds when settings editors replace dynamically added printer rows.
   const observer=new MutationObserver(changes=>{if(!container.isConnected){observer.disconnect();return;}if(changes.some(change=>!container.contains(change.target)))draw();});
   if(form!==document)observer.observe(form,{childList:true,subtree:true});
   const timer=setInterval(()=>{if(!container.isConnected){clearInterval(timer);observer.disconnect();listeners.delete(draw);return;}const now=Date.now();
     if(auto.checked&&now-previousTime>=Math.max(3000,Number(setting('seconds_per_printer',10))*1000)){index++;previousTime=now;}draw();},1000);
   draw();
 }
 window.LEDMatrixWidgets.register('moonraker-color-picker',{
   name:'Moonraker Color Picker',version:'1.6.0',render:widgetColor,
   getValue:function(fieldId){return widgetById.get(String(fieldId))?.input.value||'#ffffff';},
   setValue:function(fieldId,value){const widget=widgetById.get(String(fieldId));if(widget&&/^#[0-9a-f]{6}$/i.test(value)){widget.input.value=value;colorValues.set(widget.key,value);notify();}},
   handlers:{}
 });
 window.LEDMatrixWidgets.register('moonraker-live-preview',{
   name:'Moonraker Live Settings Preview',version:'1.5.1',render:preview,
   getValue:function(){return 'live';},setValue:function(){},handlers:{}
 });
})();
