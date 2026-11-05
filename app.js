/* Dataloka.id — Monitor Gempa Indonesia. Website mandiri, tanpa kode embed. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const palette = { low: '#21a8d4', medium: '#f2a04f', high: '#ed6479' };
const state = { data: null, events: [], filtered: [], selected: null, filter: 'all', query: '', limit: 8, geo: null, zoom: 1, panX: 0, panY: 0, signature: '' };
const int = n => new Intl.NumberFormat('id-ID').format(n);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const date = value => new Intl.DateTimeFormat('id-ID', { timeZone:'Asia/Jakarta', day:'numeric', month:'short', year:'numeric' }).format(new Date(value));
const time = value => new Intl.DateTimeFormat('id-ID', { timeZone:'Asia/Jakarta', hour:'2-digit', minute:'2-digit', hourCycle:'h23' }).format(new Date(value)) + ' WIB';
const svgElement = (name, attrs={}) => {const element=document.createElementNS(NS,name);Object.entries(attrs).forEach(([key,value])=>element.setAttribute(key,String(value)));return element;};
const project = (longitude,latitude) => [(longitude-92)/52*1050+25, (8-latitude)/20*426+17];
const magColor = m => m >= 6 ? palette.high : m >= 5 ? palette.medium : palette.low;
const valid = e => e && typeof e.id === 'string' && typeof e.region === 'string' &&
  Number.isFinite(Number(e.magnitude)) && Number(e.magnitude)>0 && Number(e.magnitude)<11 &&
  Number.isFinite(Number(e.lat)) && Number(e.lat)>=-90 && Number(e.lat)<=90 &&
  Number.isFinite(Number(e.lon)) && Number(e.lon)>=-180 && Number(e.lon)<=180 &&
  Number.isFinite(Number(e.depth_km)) && Number(e.depth_km)>=0 && !Number.isNaN(Date.parse(e.datetime));
function filteredEvents(){
  return state.events.filter(e=>(state.filter==='all'||(state.filter==='m5'&&e.magnitude>=5)||(state.filter==='felt'&&e.felt)) && e.region.toLocaleLowerCase('id').includes(state.query));
}
function renderStatus(error=false){
 const payload=state.data||{};
 const check=payload.checked_at?Date.parse(payload.checked_at):NaN;
 const stale=payload.status==='live'&&(!Number.isFinite(check)||Date.now()-check>90*60*1000);
 const dot=$('statusDot');dot.className='status-indicator';
 if(error){dot.classList.add('error');$('statusLabel').textContent='Pembaruan gagal';}
 else if(stale){dot.classList.add('error');$('statusLabel').textContent='Sinkronisasi terlambat';}
 else if(payload.status==='live'){dot.classList.add('live');$('statusLabel').textContent='Sinkronisasi aktif';}
 else{$('statusLabel').textContent='Mode pratinjau';}
 $('syncTime').textContent=payload.status==='live'&&payload.checked_at ? `Pemeriksaan terakhir ${date(payload.checked_at)}, ${time(payload.checked_at)}` : 'Data contoh — bukan pantauan real-time';
 let message='';
 if(error)message='Tidak bisa memeriksa pembaruan. Data terakhir yang tersedia tetap ditampilkan.';
 else if(stale)message='Pembaruan data sudah lebih dari 90 menit. Periksa sinkronisasi sebelum menganggapnya informasi terbaru.';
 else if(payload.status!=='live')message='MODE PRATINJAU — Data belum disinkronkan dengan BMKG.';
 else if(Array.isArray(payload.errors)&&payload.errors.length)message='Data real-time utama tersedia, tetapi sebagian feed pelengkap mengalami gangguan. Periksa sumber sebelum menggunakan informasi dirasakan atau potensi tsunami.';
 $('notice').hidden=!message;
 $('noticeText').textContent=message;
}
function renderMetrics(){
 $('totalEvents').textContent=int(state.events.length);
 $('countM5').textContent=int(state.events.filter(e=>e.magnitude>=5).length);
 $('countFelt').textContent=int(state.events.filter(e=>e.felt).length);
 $('maxMagnitude').textContent=state.events.length ? 'M '+Math.max(...state.events.map(e=>e.magnitude)).toFixed(1) : '—';
 const first=state.events[0];
 $('latestMagnitude').textContent=first?first.magnitude.toFixed(1):'—';
 $('latestLocation').textContent=first?first.region:'Data belum tersedia';
 $('latestTime').textContent=first?`${date(first.datetime)} · ${time(first.datetime)}`:'—';
 $('latestOpen').disabled=!first;
}
function coordinatesPath(rings){
 return (rings||[]).map(ring=>ring.map(([lon,lat],index)=>{const [x,y]=project(lon,lat);return `${index?'L':'M'}${x.toFixed(2)},${y.toFixed(2)}`;}).join(' ')+' Z').join(' ');
}
function drawLand(){
 const land=$('mapLand'),labels=$('mapLabels'),grid=$('mapGraticule');
 if(!land || !labels || !state.geo?.features?.length)return;
 // Prepare a complete replacement before touching the static map fallback.
 const fragment=document.createDocumentFragment();
 for(const feature of state.geo.features){
  const geom=feature.geometry;
  if(!geom)continue;
  const coordinates=geom.type==='Polygon'?[geom.coordinates]:geom.type==='MultiPolygon'?geom.coordinates:[];
  for(const polygon of coordinates){
   const path=svgElement('path',{d:coordinatesPath(polygon),'fill-rule':'evenodd'});
   fragment.appendChild(path);
  }
 }
 if(!fragment.childNodes.length)return;
 land.replaceChildren(fragment);
 labels.replaceChildren();
 if(grid){
  grid.replaceChildren();
  for(const lon of [100,110,120,130,140]){
   const [x]=project(lon,0);
   grid.appendChild(svgElement('line',{x1:x,y1:0,x2:x,y2:464}));
   const label=svgElement('text',{x:x+5,y:448});label.textContent=lon+'°E';grid.appendChild(label);
  }
  for(const lat of [-10,-5,0,5]){
   const [,y]=project(110,lat);
   grid.appendChild(svgElement('line',{x1:0,y1:y,x2:1100,y2:y}));
   const label=svgElement('text',{x:8,y:y-7});label.textContent=lat===0?'EQ':Math.abs(lat)+'°'+(lat<0?'S':'N');grid.appendChild(label);
  }
 }
 const names=[['SUMATERA',101.4,-.5],['KALIMANTAN',113.2,-.5],['JAWA',110.5,-6.8],['SULAWESI',121.7,-1.7],['PAPUA',137,-4.6]];
 for(const [name,lon,lat] of names){const [x,y]=project(lon,lat);const label=svgElement('text',{x,y,'text-anchor':'middle'});label.textContent=name;labels.appendChild(label);}
}
async function loadMap(){
 try{const response=await fetch('assets/indonesia.geojson');if(!response.ok)throw Error('HTTP '+response.status);state.geo=await response.json();drawLand();}
 catch(error){console.warn('GeoJSON belum dapat dimuat; peta cadangan tetap ditampilkan:',error);}
}
function renderMapPoints(){
 const layer=$('mapPoints');layer.replaceChildren();
 let plotted=0;
 for(const e of [...state.filtered].sort((a,b)=>a.magnitude-b.magnitude)){
  const [x,y]=project(e.lon,e.lat);
  if(x<-10||x>1110||y<-10||y>474)continue;
  plotted+=1;
  const r=e.magnitude>=6?9.5:e.magnitude>=5?7.7:6;
  const group=svgElement('g',{class:'quake-point'+(state.selected===e.id?' selected':''),tabindex:'0',role:'button','aria-label':`Gempa magnitudo ${e.magnitude.toFixed(1)}, ${e.region}`});
  group.appendChild(svgElement('circle',{cx:x,cy:y,r:r*2.7,class:'halo',fill:magColor(e.magnitude)}));
  if(state.selected===e.id)group.appendChild(svgElement('circle',{cx:x,cy:y,r:r*1.7,class:'focus-ring'}));
  group.appendChild(svgElement('circle',{cx:x,cy:y,r,class:'core',fill:magColor(e.magnitude)}));
  const label=svgElement('title');label.textContent=`M ${e.magnitude.toFixed(1)} — ${e.region} (${date(e.datetime)} ${time(e.datetime)})`;group.appendChild(label);
  group.addEventListener('click',evt=>{evt.stopPropagation();hideMapTooltip();select(e.id);});
  group.addEventListener('pointerenter',evt=>showMapTooltip(evt,e));
  group.addEventListener('pointermove',evt=>positionMapTooltip(evt));
  group.addEventListener('pointerleave',hideMapTooltip);
  group.addEventListener('keydown',evt=>{if(evt.key==='Enter'||evt.key===' '){evt.preventDefault();hideMapTooltip();select(e.id);}});
  layer.appendChild(group);
 }
 $('mapCount').textContent=int(plotted)+' dari '+int(state.filtered.length)+' titik di area peta';
}
function hideMapTooltip(){
 const tooltip=$('mapTooltip');if(tooltip)tooltip.hidden=true;
}
function positionMapTooltip(evt){
 const tooltip=$('mapTooltip');
 if(!tooltip||tooltip.hidden||evt.pointerType==='touch')return;
 const rect=$('mapSvg').getBoundingClientRect();
 const frame=$('mapSvg').parentElement.getBoundingClientRect();
 const x=evt.clientX-frame.left+16,y=evt.clientY-frame.top+14;
 const width=tooltip.offsetWidth||190,height=tooltip.offsetHeight||80;
 tooltip.style.left=Math.max(8,Math.min(x,frame.width-width-10))+'px';
 tooltip.style.top=Math.max(8,Math.min(y,frame.height-height-10))+'px';
}
function showMapTooltip(evt,event){
 if(evt.pointerType==='touch')return;
 const tooltip=$('mapTooltip');if(!tooltip)return;
 tooltip.innerHTML='<strong>M '+event.magnitude.toFixed(1)+' · '+escapeHTML(event.region)+'</strong><small>'+date(event.datetime)+' · '+time(event.datetime)+' · '+int(event.depth_km)+' km</small>';
 tooltip.hidden=false;
 positionMapTooltip(evt);
}
function sourceLink(e){
 return (e.source_urls||[]).find(v=>typeof v==='string'&&v==='https://www.bmkg.go.id/gempabumi/gempabumi-realtime') || (e.source_urls||[]).find(v=>typeof v==='string'&&/^https:\/\/data\.bmkg\.go\.id\/DataMKG\/TEWS\/(?:autogempa|gempaterkini|gempadirasakan)\.json$/.test(v)) || 'https://www.bmkg.go.id/gempabumi/gempabumi-realtime';
}
function renderSelected(){
 const e=state.events.find(event=>event.id===state.selected);
 const panel=$('selectedContent');
 if(!e){panel.innerHTML='<p class="loading">Tidak ada data gempa yang sesuai.</p>';return;}
 const chips=[`<span class="info-chip">Kedalaman <strong>${int(e.depth_km)} km</strong></span>`,
 `<span class="info-chip">Koordinat <strong>${e.lat.toFixed(2)}, ${e.lon.toFixed(2)}</strong></span>`];
 if(e.felt)chips.push('<span class="info-chip"><strong>Gempa dirasakan</strong></span>');
 if(e.tsunami)chips.push('<span class="info-chip"><strong>Informasi potensi tsunami</strong></span>');
 const details=[];
 if(e.felt && e.felt_info)details.push(`<div><b>Intensitas dirasakan:</b> ${escapeHTML(e.felt_info)}</div>`);
 if(e.potential_text)details.push(`<div><b>Informasi BMKG:</b> ${escapeHTML(e.potential_text)}</div>`);
 panel.innerHTML=`<div class="selected-main"><div class="selected-mag"><small>M</small>${e.magnitude.toFixed(1)}</div><div class="selected-info"><div class="selected-region">${escapeHTML(e.region)}</div><div class="selected-time">${date(e.datetime)} · ${time(e.datetime)}</div><div class="selected-more">${chips.join('')}</div></div><a class="detail-source" href="${sourceLink(e)}" target="_blank" rel="noopener noreferrer">Lihat sumber ↗</a></div>${details.length?`<div class="detail-extra">${details.join('')}</div>`:''}`;
}
function renderFeed(){
 const list=$('feedBody');list.replaceChildren();
 $('resultCount').textContent=int(state.filtered.length)+' data';
 $('showingInfo').textContent=state.filtered.length ? `Menampilkan ${int(Math.min(state.filtered.length,state.limit))} dari ${int(state.filtered.length)} kejadian` : 'Tidak ditemukan kejadian';
 $('showMoreBtn').hidden=state.filtered.length<=state.limit;
 if(!state.filtered.length){const empty=document.createElement('p');empty.className='loading';empty.textContent='Tidak ada gempa yang cocok dengan pencarian ini.';list.appendChild(empty);return;}
 for(const e of state.filtered.slice(0,state.limit)){
  const row=document.createElement('button');row.type='button';row.className='event-row'+(e.id===state.selected?' selected':'');row.setAttribute('role','listitem');
  row.style.setProperty('--mag-color',magColor(e.magnitude));row.style.setProperty('--mag-bg',e.magnitude>=6?'rgba(237,100,121,.12)':e.magnitude>=5?'rgba(242,160,79,.13)':'rgba(33,168,212,.12)');
  const pills=e.felt?'<span class="tiny-pill">DIRASAKAN</span>':'';
  row.innerHTML=`<span class="event-mag">${e.magnitude.toFixed(1)}</span><span class="event-body"><span class="event-place">${escapeHTML(e.region)}</span><span class="event-meta">${date(e.datetime)} · ${time(e.datetime)} · ${int(e.depth_km)} km</span>${pills?`<span class="event-labels">${pills}</span>`:''}</span><span class="event-chevron" aria-hidden="true">›</span>`;
  row.addEventListener('click',()=>select(e.id));list.appendChild(row);
 }
}
function select(id){
 if(!state.events.some(e=>e.id===id))return;
 state.selected=id;renderMapPoints();renderSelected();renderFeed();
}
function renderAll(){
 renderStatus();renderMetrics();state.filtered=filteredEvents();
 if(!state.filtered.some(e=>e.id===state.selected))state.selected=state.filtered[0]?.id||null;
 renderMapPoints();renderFeed();renderSelected();
}
async function updateData(initial=false){
 try{
  const response=await fetch('data/gempa.json?cache='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const payload=await response.json();
  if(!Array.isArray(payload.events)||!['live','preview','fixture'].includes(payload.status))throw Error('Format data gempa tidak dikenal');
  const signature=JSON.stringify(payload);
  if(!initial&&signature===state.signature){renderStatus();return;}
  state.signature=signature;state.data=payload;
  state.events=payload.events.filter(valid).map(e=>({...e,magnitude:Number(e.magnitude),depth_km:Number(e.depth_km),lat:Number(e.lat),lon:Number(e.lon)})).sort((a,b)=>Date.parse(b.datetime)-Date.parse(a.datetime));
  renderAll();
 }catch(error){console.warn('Gagal memuat data:',error);renderStatus(true);if(initial){$('feedBody').innerHTML='<p class="loading">Data belum tersedia. Jalankan proyek melalui server lokal atau GitHub Pages.</p>'; $('latestLocation').textContent='Data tidak tersedia';}}
}
function updateZoom(){
 const z=state.zoom;if(z===1){state.panX=0;state.panY=0;}
 state.panX=Math.max(-550*(z-1),Math.min(550*(z-1),state.panX));
 state.panY=Math.max(-232*(z-1),Math.min(232*(z-1),state.panY));
 $('mapTransform').setAttribute('transform',`translate(${(1-z)*550+state.panX} ${(1-z)*232+state.panY}) scale(${z})`);
}
function setup(){
 $('themeToggle').addEventListener('click',()=>{
  const next=document.body.dataset.theme==='dark'?'light':'dark';document.body.dataset.theme=next;
  try{localStorage.setItem('dataloka-monitor-theme',next);}catch(_error){}
 });
 try{const saved=localStorage.getItem('dataloka-monitor-theme');if(saved==='light'||saved==='dark')document.body.dataset.theme=saved;}catch(_error){}
 document.querySelectorAll('#mapFilters button').forEach(button=>button.addEventListener('click',()=>{
  state.filter=button.dataset.type;state.limit=8;
  document.querySelectorAll('#mapFilters button').forEach(other=>{other.classList.toggle('active',other===button);other.setAttribute('aria-pressed',other===button?'true':'false');});
  renderAll();
 }));
 $('searchField').addEventListener('input',event=>{state.query=event.target.value.trim().toLocaleLowerCase('id');state.limit=8;renderAll();});
 $('showMoreBtn').addEventListener('click',()=>{state.limit+=8;renderFeed();});
 $('refreshButton').addEventListener('click',()=>updateData());
 $('latestOpen').addEventListener('click',()=>{
  const first=state.events[0];if(!first)return;
  state.query='';$('searchField').value='';state.filter='all';
  document.querySelectorAll('#mapFilters button').forEach(button=>{const active=button.dataset.type==='all';button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
  state.selected=first.id;renderAll();document.querySelector('.map-card').scrollIntoView({behavior:'smooth',block:'start'});
 });
 $('zoomIn').addEventListener('click',()=>{state.zoom=Math.min(4,state.zoom*1.4);updateZoom();});
 $('zoomOut').addEventListener('click',()=>{state.zoom=Math.max(1,state.zoom/1.4);updateZoom();});
 $('zoomReset').addEventListener('click',()=>{state.zoom=1;updateZoom();});
 const svg=$('mapSvg');let dragging=null;
 svg.addEventListener('pointerdown',event=>{
  if(state.zoom===1||event.target.closest?.('.quake-point'))return;
  dragging={x:event.clientX,y:event.clientY,px:state.panX,py:state.panY};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');
 });
 svg.addEventListener('pointermove',event=>{
  if(!dragging)return;const rect=svg.getBoundingClientRect();state.panX=dragging.px+(event.clientX-dragging.x)*1100/rect.width;state.panY=dragging.py+(event.clientY-dragging.y)*464/rect.height;updateZoom();
 });
 const end=()=>{dragging=null;svg.classList.remove('dragging');};svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
}
setup();loadMap();updateData(true);setInterval(()=>updateData(),60000);
})();
