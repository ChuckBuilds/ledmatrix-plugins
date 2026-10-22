(function () {
  'use strict';
  const STYLES = ['neon','prism','starfield','matrix','fire','horizon','binary','minimal','pulse','wave','aurora','rain','flap','morph','outline','words','dotgrid','moon','dayprogress','world','pong','tetris','aquarium','snow','lava','pacman','analog','bighour'];
  const COLORS = {cyan:'#23e6ff',magenta:'#ff41b4',amber:'#ffba38',green:'#4cff87'};
  const esc = s => String(s).replace(/[^a-zA-Z0-9_-]/g,'_');
  function run(container, config, value, options) {
    const id = esc(options.fieldId || container.id);
    const holder = document.createElement('div');
    holder.className = 'space-y-2';
    const heading = document.createElement('div');
    heading.textContent = 'Live Clock Preview · 5 × P5 (320 × 32)';
    heading.style.fontWeight = '600';
    const canvas = document.createElement('canvas');
    canvas.width = 320; canvas.height = 32;
    canvas.style.cssText = 'width:100%;max-width:960px;display:block;background:#000;border:1px solid #4b5563;border-radius:6px;image-rendering:pixelated';
    canvas.setAttribute('aria-label','Live ChromaClock Wide preview');
    const note = document.createElement('p');
    note.style.cssText = 'font-size:12px;opacity:.75;margin-top:5px';
    note.textContent = 'With Preview Mode enabled, Preview Style controls this canvas and the physical clock after Save. Otherwise Style controls this canvas. Changes here render before saving. Preview uses browser canvas and approximates the Pillow renderer.';
    const status = document.createElement('p');
    status.style.cssText = 'font-size:12px;opacity:.85;margin-top:4px';
    holder.append(heading,canvas,status,note);
    container.replaceChildren(holder);
    const context=canvas.getContext('2d');
    if (!context) {status.textContent='Canvas unavailable';return;}
    const form=container.closest('form') || container.parentElement;
    const controlsRoot=form || document;
    const find = name => {
      const fields = controlsRoot.querySelectorAll('input[name],select[name]');
      for(const el of fields) if(el.name === name || el.name.endsWith('.'+name) || el.id === name || el.id.endsWith('_'+name)) return el;
      return null;
    };
    function read(name, fallback){
      const el=find(name);
      if(!el) return fallback;
      return el.type==='checkbox' ? el.checked : el.value;
    }
    function color(h){return 'hsl('+((h%360+360)%360)+' 95% 62%)';}
    function draw(){
      if(!container.isConnected)return;
      const t=Date.now()/1000,w=320,h=32;
      let style=read('style','cycle');
      const interval=Math.max(5,Number(read('cycle_seconds',20))||20);
      if(style==='cycle')style=STYLES[Math.floor(t/interval)%STYLES.length];
      // Preview Mode deliberately pins Preview Style, matching Python display().
      // Otherwise the browser follows Style, including automatic cycling.
      if(read('preview_mode',false)) style=read('preview_style','neon');
      if(!STYLES.includes(style))style='neon';
      const palette=read('palette','rainbow');
      const a=COLORS[palette]||color(t*4.8),b=color(t*4.8+100);
      const brightness=Math.max(.15,Math.min(1,Number(read('brightness',.85))||.85));
      const ctx=context;ctx.clearRect(0,0,w,h);ctx.fillStyle='#000';ctx.fillRect(0,0,w,h);
      for(let x=0;x<w;x++){
        const wave=Math.sin(x*.08+t);
        ctx.fillStyle=style==='matrix'?'#23ba60':style==='fire'?'#ff7721':style==='aurora'?'#42efa7':style==='prism'?color(x*1.1+t*9):a;
        ctx.globalAlpha=.55*brightness;
        let y=Math.floor(16+wave*7);
        if(['neon','prism'].includes(style)){ctx.fillRect(x,1,1,2);ctx.fillRect(x,29,1,2);}
        else if(style==='starfield'){if(x%5===0)ctx.fillRect(x,(x*23+7)%h,1,1);}
        else if(style==='matrix'||style==='rain'){if(x%7===0)ctx.fillRect(x,Math.floor((t*10+x*13)%38)-5,1,5);}
        else if(style==='fire'||style==='horizon'){ctx.fillRect(x,y,1,h-y);}
        else if(style==='binary'){if(x%8===0)for(let j=0;j<4;j++)if((x+j+Math.floor(t))%3===0)ctx.fillRect(x,3+j*7,3,3);}
        else if(style==='pulse')ctx.fillRect(x,Math.min(y,16),1,Math.abs(y-16)+1);
        else if(style==='wave'||style==='aurora')ctx.fillRect(x,y,1,2);
        else if(x%12===0)ctx.fillRect(x,h-2,1,1);
      }
      ctx.globalAlpha=1;
      // Dedicated scene renderer: each animation is drawn once per frame, not
      // repeated in the per-pixel background loop.
      function line(x,y,x2,y2,color,width=1){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x2,y2);ctx.stroke();}
      function circle(x,y,r,color){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
      // Full-canvas animation: clock glyphs are painted after the backdrop.
      const sides=[[0,w]];
      if(style==='pacman'){
        // Mini arcade maze in both side bays; cyan double walls, lit pellets,
        // animated Pac-Man, four recognizable ghost colors and white eyes.
        for(let sideIndex=0;sideIndex<sides.length;sideIndex++){
          const [lo,hi]=sides[sideIndex], width=hi-lo, mid=16;
          ctx.strokeStyle='#164efb';ctx.lineWidth=2;
          ctx.strokeRect(lo+1,1,width-3,30);
          ctx.strokeRect(lo+8,5,18,7);
          ctx.strokeRect(hi-27,20,18,7);
          line(lo+33,2,lo+33,10,'#164efb',2);
          line(hi-34,22,hi-34,30,'#164efb',2);
          const px=lo+8+((t*12+sideIndex*23)%(width-16));
          const mouth=.09+.62*Math.abs(Math.sin(t*7));
          for(let x=lo+6;x<hi-3;x+=8)
            if(Math.abs(x-px)>7)circle(x,mid,1.15,'#f7c994');
          ctx.fillStyle='#ffe21c';ctx.beginPath();ctx.moveTo(px,mid);
          ctx.arc(px,mid,5,mouth,Math.PI*2-mouth,false);ctx.closePath();ctx.fill();
          for(let i=0;i<2;i++){
            const gx=lo+10+((t*(5+i)+i*29+sideIndex*17)%(width-20));
            const gy=i===0?6:26;
            const gc=['#fa404d','#ffabd5','#4afaff','#ffaf35'][(sideIndex*2+i)%4];
            ctx.fillStyle=gc;
            ctx.beginPath();ctx.moveTo(gx-5,gy+5);ctx.lineTo(gx-5,gy);
            ctx.arc(gx,gy,4,Math.PI,0,false);
            ctx.lineTo(gx+4,gy+3);
            for(let z=4;z>=0;z--)ctx.lineTo(gx-4+z*2,gy+3+(z%2?0:-1));
            ctx.closePath();ctx.fill();
            ctx.fillStyle='#fff';ctx.fillRect(gx-3,gy-1,3,3);ctx.fillRect(gx+1,gy-1,3,3);
            ctx.fillStyle='#153ddf';ctx.fillRect(gx-2,gy,1,2);ctx.fillRect(gx+2,gy,1,2);
          }
        }
      }else if(style==='aquarium'){
        line(0,29,320,29,'#257b96');
        for(const [lo,hi] of sides){
          for(let i=0;i<4;i++){
            const x=lo+7+((i*19+t*(3+i%3))%(hi-lo-14));
            const y=7+i*5+Math.sin(t+i)*2;
            ctx.fillStyle=['#ffac44','#69e2ee','#fa6ca1'][i%3];
            ctx.beginPath();ctx.ellipse(x,y,5,3,0,0,2*Math.PI);ctx.fill();
            ctx.beginPath();ctx.moveTo(x-4,y);ctx.lineTo(x-9,y-4);ctx.lineTo(x-9,y+4);ctx.fill();
            circle(x+2,y-1,.8,'#101323');
          }
          for(let i=0;i<4;i++){
            const x=lo+8+i*16,y=27-((t*5+i*7)%23);
            ctx.strokeStyle='#52a8d6';ctx.strokeRect(x,y,2,2);
          }
        }
      }else if(style==='pong'){
        for(const [lo,hi] of sides){
          const x=lo+6+Math.abs(Math.sin(t*.9))*(hi-lo-12),y=4+Math.abs(Math.cos(t*.68))*23;
          line(lo+3,8+Math.sin(t)*6,lo+3,17+Math.sin(t)*6,a,2);
          line(hi-4,8+Math.cos(t)*6,hi-4,17+Math.cos(t)*6,b,2);
          ctx.fillStyle='#fff';ctx.fillRect(x,y,3,3);
        }
      }else if(style==='tetris'){
        for(const [lo,hi] of sides)for(let i=0;i<8;i++){
          const x=lo+5+(i*13)%(hi-lo-15), y=((t*(3+i%3)+i*9)%42)-10;
          ctx.fillStyle=['#28cfee','#ffaf44','#ab68ff'][i%3];
          for(const [dx,dy] of [[0,0],[1,0],[1,1],[2,1]])ctx.fillRect(x+dx*3,y+dy*3,3,3);
        }
      }else if(style==='moon'||style==='analog'||style==='bighour'){
        for(const [lo,hi] of sides){
          const x=(lo+hi)/2,y=16;
          if(style==='moon'){circle(x,y,12,'#e6dfac');circle(x+7,y,12,'#050815');}
          else{
            ctx.strokeStyle=a;ctx.beginPath();ctx.arc(x,y,12,0,Math.PI*2);ctx.stroke();
            if(style==='analog'){line(x,y,x+8*Math.sin(t*.08),y-8*Math.cos(t*.08),a,2);line(x,y,x+10*Math.sin(t*.025),y-10*Math.cos(t*.025),b);}
            else{ctx.font='bold 11px monospace';ctx.textAlign='center';ctx.fillStyle=a;ctx.fillText(String(new Date().getHours()%12||12),x,19);}
          }
        }
      }else if(style==='snow'||style==='lava'){
        for(const [lo,hi] of sides)for(let i=0;i<22;i++){
          const x=lo+((i*23+Math.sin(t+i)*3)%(hi-lo)),y=style==='snow'?(i*11+t*(2+i%4))%32:16+Math.sin(t*.5+i)*11;
          if(style==='snow')circle(x,y,.8,'#c5e2ff');else circle(x,y,2+i%3,i%2?a:b);
        }
      }else if(style==='dayprogress'){
        const now=new Date(),fraction=(now.getHours()*3600+now.getMinutes()*60+now.getSeconds())/86400;
        for(const [lo,hi] of sides){ctx.strokeStyle=b;ctx.strokeRect(lo+4,13,hi-lo-8,6);ctx.fillStyle=a;ctx.fillRect(lo+5,14,(hi-lo-10)*fraction,4);}
      }else if(style==='dotgrid'||style==='binary'){
        for(const [lo,hi] of sides)for(let x=lo+3;x<hi-3;x+=5)for(let y=3;y<29;y+=5)
          if((x*7+y*13+Math.floor(t))%6<3)circle(x,y,.9,a);
      }else if(style==='world'||style==='words'){
        for(let i=0;i<sides.length;i++){const [lo,hi]=sides[i];ctx.fillStyle=a;ctx.font='bold 9px monospace';ctx.textAlign='center';ctx.fillText(style==='words'?(i?'NOW':'IT IS'):new Date(Date.now()+[0,9][i]*3600000).toISOString().slice(11,16),(lo+hi)/2,18);}
      }else if(['flap','morph','outline'].includes(style)){
        for(const [lo,hi] of sides)for(let x=lo+4;x<hi-8;x+=17){ctx.strokeStyle=a;ctx.strokeRect(x,5,12,22);if(style==='flap')line(x,16,x+12,16,b);if(style==='morph')line(x,6,x+12,24,b);}
      }
      const timezone=read('timezone','America/New_York');
      let n=new Date(),hour=n.getHours(),minute=n.getMinutes(),sec=n.getSeconds(),dateLabel='';
      try{
        const parts=new Intl.DateTimeFormat('en-US',{timeZone:timezone,hour:'numeric',minute:'numeric',second:'numeric',hour12:false}).formatToParts(n);
        const part=k=>Number(parts.find(p=>p.type===k)?.value||0);
        hour=part('hour')%24;minute=part('minute');sec=part('second');
        dateLabel=new Intl.DateTimeFormat('en-US',{timeZone:timezone,weekday:'short',month:'short',day:'numeric'}).format(n).toUpperCase();
      }catch(e){dateLabel=n.toDateString().toUpperCase();}
      const h24=read('use_24h',false), hstr=String(h24?hour:(hour%12||12));
      const text=hstr+':'+String(minute).padStart(2,'0');
      const dateOn=read('show_date',true),secOn=read('show_seconds',true);
      const maxW=160;
      let size=dateOn?23:27;
      ctx.font='bold '+size+'px monospace';
      while(ctx.measureText(text).width>maxW&&size>8){size--;ctx.font='bold '+size+'px monospace';}
      ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle=a;
      if(read('glow',true)){ctx.globalAlpha=.25;ctx.fillText(text,161,dateOn?12:16);ctx.fillText(text,159,dateOn?12:16);ctx.globalAlpha=1;}
      // Crisp dark glyph stroke improves readability without boxing out the scene.
      ctx.strokeStyle='#000';ctx.lineWidth=2;ctx.strokeText(text,160,dateOn?12:16);
      ctx.fillText(text,160,dateOn?12:16);
      if(secOn){ctx.font='bold 8px monospace';ctx.fillStyle=b;ctx.fillText(String(sec).padStart(2,'0'),230,8);ctx.fillStyle=a;ctx.fillRect(0,31,Math.floor(w*sec/60),1);}
      if(dateOn){ctx.font='bold 7px monospace';ctx.fillStyle='#cdd5e6';ctx.fillText(dateLabel,160,27);}
      status.textContent='Full-width background · Previewing: '+style+' · '+w+'×'+h+' · '+(h24?'24h':'12h')+' · '+timezone;
      ctx.globalAlpha=1;
    }
    let timer=setInterval(()=>{if(!container.isConnected){clearInterval(timer);return;} draw();},250);
    form.addEventListener('input',draw);
    form.addEventListener('change',draw);
    draw();
  }
  if(window.LEDMatrixWidgets){
    window.LEDMatrixWidgets.register('chromaclock-live-preview',{
      name:'Live ChromaClock Preview',
      version:'1.4.0',
      render:run,
      getValue:function(){return 'live';},
      setValue:function(){},
      handlers:{}
    });
  }
})();