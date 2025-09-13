(function(){
  const appDiv = document.getElementById('app');
  const hudTiles = document.getElementById('hudTiles');
  const hudZoom = document.getElementById('hudZoom');

  const SEMANTIC_IMG_URL = '../out/society145_1km/semantic_preview.png';
  const POIS_URL = '../out/society145_1km/pois.json';
  const LABELS_URL = '../out/society145_1km/labels.json';
  const VENUES_URL = '../out/society145_1km/venues.json';
  const MAIN_POI_LON = -80.5381896;
  const MAIN_POI_LAT = 43.4765757;

  const app = new PIXI.Application({
    resizeTo: appDiv,
    antialias: false,
    backgroundColor: 0x0e0f10,
    clearBeforeRender: true,
    powerPreference: 'high-performance',
  });
  appDiv.appendChild(app.view);
  app.view.style.cursor = 'grab';

  // Camera state
  let zoom = 2.0;
  let cameraX = 0;
  let cameraY = 0;
  let isDragging = false;
  let dragStartX = 0, dragStartY = 0, cameraStartX = 0, cameraStartY = 0;

  const world = new PIXI.Container();
  app.stage.addChild(world);

  let baseSprite = null;
  let gridW = 0, gridH = 0;
  let originX = 0, originY = 0, cellM = 1.5;

  // POIs
  let pois = [];
  const poiContainer = new PIXI.Container();
  world.addChild(poiContainer);
  let poiMarkers = [];

  // Small vector icons per POI category (keeps things crisp at all zooms)
  function createPoiIcon(kind, color){
    const c = new PIXI.Container();
    const g = new PIXI.Graphics();
    const stroke = 0x111111;
    const s = 1.15; // overall scale factor for consistency

    function bag(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawRoundedRect(-3.5*s, -3.0*s, 7*s, 6*s, 1.6*s);
      g.endFill();
      g.lineStyle(1.1, stroke, 0.95);
      g.moveTo(-2.0*s, -3.0*s); g.lineTo(-2.0*s, -4.8*s);
      g.moveTo( 2.0*s, -3.0*s); g.lineTo( 2.0*s, -4.8*s);
      g.moveTo(-2.0*s, -4.8*s); g.lineTo( 2.0*s, -4.8*s);
    }
    function cross(){
      g.lineStyle(1.0, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawRect(-1.6*s, -4*s, 3.2*s, 8*s);
      g.drawRect(-4*s, -1.6*s, 8*s, 3.2*s);
      g.endFill();
    }
    function cup(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawRoundedRect(-3.2*s, -2.0*s, 6.4*s, 4.2*s, 0.9*s);
      g.endFill();
      // handle
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawPolygon([3.2*s, -1.5*s, 5.0*s, -0.3*s, 3.2*s, 0.9*s]);
      g.endFill();
    }
    function forkKnife(){
      g.lineStyle(1.0, stroke, 0.95);
      g.beginFill(color, 0.95);
      // fork
      g.drawRect(-3.2*s, -3.8*s, 1.2*s, 7.6*s);
      g.drawRect(-3.8*s, -3.8*s, 2.4*s, 1.0*s);
      // knife
      g.drawRoundedRect(1.6*s, -3.8*s, 1.0*s, 7.6*s, 0.6*s);
      g.endFill();
    }
    function bus(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawRoundedRect(-3.8*s, -3.0*s, 7.6*s, 5.4*s, 1.2*s);
      g.endFill();
      g.beginFill(stroke, 0.95);
      g.drawCircle(-2.0*s, 2.0*s, 0.9*s);
      g.drawCircle( 2.0*s, 2.0*s, 0.9*s);
      g.endFill();
    }
    function cap(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawPolygon([0, -4.5*s, 5*s, -2*s, 0, 0.5*s, -5*s, -2*s]);
      g.endFill();
      g.lineStyle(1.0, stroke, 0.95);
      g.moveTo(0, 0.5*s); g.lineTo(0, 2.5*s);
    }
    function tag(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawPolygon([-3.5*s, -2.2*s, 1.0*s, -2.2*s, 3.5*s, 0, 1.0*s, 2.2*s, -3.5*s, 2.2*s]);
      g.endFill();
      // hole
      g.beginFill(0xffffff, 0.9);
      g.drawCircle(0.0*s, -1.0*s, 0.7*s);
      g.endFill();
    }
    function diamond(){
      g.lineStyle(1.2, stroke, 0.95);
      g.beginFill(color, 0.95);
      g.drawPolygon([0, -3.6*s, 3.6*s, 0, 0, 3.6*s, -3.6*s, 0]);
      g.endFill();
    }

    switch(kind){
      case 'grocery': bag(); break;
      case 'pharmacy': cross(); break;
      case 'cafe': cup(); break;
      case 'restaurant': forkKnife(); break;
      case 'transit': bus(); break;
      case 'education': cap(); break;
      case 'health': cross(); break;
      case 'retail': tag(); break;
      default: diamond(); break;
    }
    c.addChild(g);
    return c;
  }

  // Labels (hover only)
  let labels = [];
  const labelContainer = new PIXI.Container();
  world.addChild(labelContainer);
  let hoverLabel = null;
  let currentHoverId = null; // prevent re-renders

  // Venues
  let venues = [];
  const venueContainer = new PIXI.Container();
  world.addChildAt(venueContainer, 1);
  let venueGfx = [];

  function styleVenueGraphic(g, visible){
    g.clear();
    // Subtle fill only; no stroke
    const fillColor = 0x3B82F6; // blue-500
    const alpha = visible ? 0.14 : 0.0;
    g.beginFill(fillColor, alpha);
    const pts = g.__pts || [];
    if (pts.length){ g.moveTo(pts[0].x, pts[0].y); for (let i=1;i<pts.length;i++){ g.lineTo(pts[i].x, pts[i].y); } g.closePath(); }
    g.endFill();
    // Soft glow when visible
    if (visible){
      g.filters = [new PIXI.filters.DropShadowFilter({ alpha:0.35, blur:4, distance:2, color:0x3B82F6 })];
    } else {
      g.filters = [];
    }
    g.alpha = 1; // control via fill alpha
  }

  // Focus highlight (pulsing ring)
  const focusContainer = new PIXI.Container();
  world.addChild(focusContainer);
  let focusTimeout = null;
  let focusAnimStop = false;
  function clearFocus(){
    focusAnimStop = true;
    if (focusTimeout) { clearTimeout(focusTimeout); focusTimeout = null; }
    focusContainer.removeChildren();
    focusContainer.alpha = 1;
  }
  function fadeOutAndClear(ms=350){
    focusAnimStop = true; // Stop any ongoing animations
    const start = performance.now();
    const startAlpha = focusContainer.alpha || 1;
    function step(t){
      const k = Math.min(1, (t - start) / ms);
      focusContainer.alpha = (1 - k) * startAlpha;
      if (k >= 1 || focusContainer.children.length === 0){ 
        clearFocus(); 
      } else { 
        requestAnimationFrame(step); 
      }
    }
    requestAnimationFrame(step);
  }
  function showFocus(ix, iy, text){
    clearFocus();
    focusAnimStop = false;
    focusContainer.alpha = 1;

    const base = new PIXI.Graphics();
    base.beginFill(0xE74C3C, 0.22); base.lineStyle(2, 0xE74C3C, 0.9); base.drawCircle(0, 0, 14); base.endFill();
    base.x = ix + 0.5; base.y = iy + 0.5; focusContainer.addChild(base);

    const ring = new PIXI.Graphics(); ring.x = base.x; ring.y = base.y; focusContainer.addChild(ring);
    let r = 16; let alpha = 0.95; let pulses = 0;
    function animate(){
      if (focusAnimStop) return;
      ring.clear(); ring.lineStyle(2, 0xE74C3C, alpha); ring.drawCircle(0, 0, r);
      r += 1.6; alpha *= 0.96;
      if (alpha > 0.05 && r < 80){ requestAnimationFrame(animate); }
      else if (++pulses < 3){ r = 16; alpha = 0.95; requestAnimationFrame(animate); }
    }
    requestAnimationFrame(animate);

    if (text) showHoverLabel({ id: `focus_${Date.now()}`, text }, ix + 0.5, iy + 0.5);

    focusTimeout = setTimeout(()=>{ fadeOutAndClear(420); hideHoverLabel(); }, 2800);
  }

  // Simple spatial index for labels (grid buckets in world units)
  let labelBuckets = new Map();
  const LABEL_BUCKET_SIZE = 64; // world cells per bucket
  function bucketKey(ix, iy){
    const bx = Math.floor(ix / LABEL_BUCKET_SIZE);
    const by = Math.floor(iy / LABEL_BUCKET_SIZE);
    return `${bx},${by}`;
  }
  function addToBucket(entry){
    const key = bucketKey(entry.ix, entry.iy);
    if (!labelBuckets.has(key)) labelBuckets.set(key, []);
    labelBuckets.get(key).push(entry);
  }
  function buildLabelIndex(){
    labelBuckets = new Map();
    for (const L of labels){ addToBucket(L); }
  }

  // UI: loading overlay
  const loadingContainer = document.createElement('div');
  Object.assign(loadingContainer.style, { position:'absolute', inset:'0', display:'grid', placeItems:'center', color:'#fff', fontFamily:'system-ui, sans-serif', background:'rgba(0,0,0,0.25)' });
  const loadingTextEl = document.createElement('div');
  loadingTextEl.textContent = 'Rendering Local Area…';
  loadingTextEl.style.fontSize = '18px';
  loadingContainer.appendChild(loadingTextEl);
  document.body.appendChild(loadingContainer);
  function hideLoading(){ loadingContainer.remove(); }

  function updateHUD(){
    if (hudTiles) hudTiles.textContent = gridW && gridH ? `${gridW}×${gridH}` : '—';
    if (hudZoom)  hudZoom.textContent  = zoom.toFixed(2);
  }

  function lonlatToGrid(lon, lat) {
    const bbox = [43.4761396, -80.5389084, 43.4773694, -80.5377408];
    const [south, west, north, east] = bbox;
    const x = ((lon - west) / (east - west)) * gridW;
    const y = ((lat - south) / (north - south)) * gridH;
    return { x: Math.max(0, Math.min(gridW-1, x)), y: Math.max(0, Math.min(gridH-1, y)) };
  }

  function centerOnPOI(){
    if (!gridW || !gridH) return;
    const poi = lonlatToGrid(MAIN_POI_LON, MAIN_POI_LAT);
    const screenW = app.renderer.width, screenH = app.renderer.height;
    cameraX = poi.x - screenW / (2 * zoom);
    cameraY = poi.y - screenH / (2 * zoom);
    applyCamera(); updateHUD();
  }

  function centerOnGrid(ix, iy){
    const screenW = app.renderer.width, screenH = app.renderer.height;
    cameraX = ix - screenW/(2*zoom);
    cameraY = iy - screenH/(2*zoom);
    applyCamera(); updateHUD();
  }

  function setZoomToRadiusMeters(radiusM){
    const targetScreenRadius = Math.min(app.renderer.width, app.renderer.height) * 0.35;
    const radiusPx = radiusM / cellM;
    zoom = Math.max(0.2, Math.min(6.0, targetScreenRadius / radiusPx));
    applyCamera();
  }

  function toScreen(x, y){ return { x: (x - cameraX) * zoom, y: (y - cameraY) * zoom }; }
  function toWorld(sx, sy){ return { x: cameraX + sx/zoom, y: cameraY + sy/zoom }; }
  function applyCamera(){ const p = toScreen(0, 0); world.position.set(p.x, p.y); world.scale.set(zoom, zoom); }

  // Minimap
  const minimapCanvas = document.getElementById('minimapCanvas');
  const mmCtx = minimapCanvas ? minimapCanvas.getContext('2d') : null;
  let baseImageBitmap = null;
  async function initMinimap(){
    if (!mmCtx) return;
    try { const blob = await (await fetch(SEMANTIC_IMG_URL)).blob(); baseImageBitmap = await createImageBitmap(blob); updateMinimap(); }
    catch(e){ console.warn('minimap init failed', e); }
  }
  function updateMinimap(){
    if (!mmCtx || !baseImageBitmap || !gridW || !gridH) return;
    const w = minimapCanvas.width, h = minimapCanvas.height;
    mmCtx.clearRect(0,0,w,h);
    mmCtx.drawImage(baseImageBitmap, 0,0, w,h);
    // viewport rect
    mmCtx.strokeStyle = 'rgba(255,255,255,0.9)'; mmCtx.lineWidth = 2;
    const vx = (cameraX / gridW) * w;
    const vy = (cameraY / gridH) * h;
    const vw = (app.renderer.width / (gridW*zoom)) * w;
    const vh = (app.renderer.height / (gridH*zoom)) * h;
    mmCtx.strokeRect(vx, vy, vw, vh);
  }
  if (minimapCanvas){
    minimapCanvas.addEventListener('click', (e)=>{
      const rect = minimapCanvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      centerOnGrid(x * gridW, y * gridH);
      updateMinimap();
    });
  }

  // Scale bar
  const scaleTrack = document.getElementById('scaleTrack');
  const scaleLabel = document.getElementById('scaleLabel');
  function updateScaleBar(){
    if (!scaleTrack || !scaleLabel) return;
    const metersPerPixel = cellM / zoom;
    const targetPx = 140;
    const targetMeters = metersPerPixel * targetPx;
    const nice = [1,2,5];
    let pow = Math.pow(10, Math.floor(Math.log10(targetMeters)));
    let best = pow; for (const n of nice){ if (n*pow <= targetMeters) best = n*pow; }
    const widthPx = Math.round(best / metersPerPixel);
    scaleTrack.style.width = `${widthPx}px`;
    scaleLabel.textContent = `${best >= 1000 ? (best/1000).toFixed(1)+' km' : Math.round(best)+' m'}`;
  }

  // Interactions
  function onResize(){ applyCamera(); updateHUD(); updateMinimap(); updateScaleBar(); }
  function onWheel(ev){
    ev.preventDefault();
    const factor = Math.pow(1.002, -ev.deltaY); // slightly sensitive
    const prevZoom = zoom; const newZoom = Math.max(0.2, Math.min(6.0, zoom * factor));
    const rect = app.view.getBoundingClientRect();
    const mx = ev.clientX - rect.left; const my = ev.clientY - rect.top;
    const worldXBefore = cameraX + (mx / prevZoom); const worldYBefore = cameraY + (my / prevZoom);
    const worldXAfter  = cameraX + (mx / newZoom);  const worldYAfter  = cameraY + (my / newZoom);
    cameraX += (worldXBefore - worldXAfter); cameraY += (worldYBefore - worldYAfter);
    zoom = newZoom; applyCamera(); updateHUD(); updateMinimap(); updateScaleBar(); renderHoverAt(mx, my);
  }
  function onPointerDown(ev){ isDragging = true; clearFocus(); hideHoverLabel(); app.view.style.cursor='grabbing'; dragStartX = ev.clientX; dragStartY = ev.clientY; cameraStartX = cameraX; cameraStartY = cameraY; }
  function onPointerMove(ev){ if (!isDragging) { const rect = app.view.getBoundingClientRect(); renderHoverAt(ev.clientX - rect.left, ev.clientY - rect.top); return; } const dx = ev.clientX - dragStartX; const dy = ev.clientY - dragStartY; cameraX = cameraStartX - dx / zoom; cameraY = cameraStartY - dy / zoom; applyCamera(); updateMinimap(); }
  function onPointerUp(){ isDragging = false; app.view.style.cursor='grab'; }
  function onDblClick(ev){ onWheel({ preventDefault(){}, deltaY:-240, clientX:ev.clientX, clientY:ev.clientY }); }

  // POIs rendering with filters (dim instead of hide)
  let poiFilters = { grocery:true, pharmacy:true, cafe:true, restaurant:true, transit:true, education:true, health:true, retail:true, other:true };
  const poiColors = {
    grocery:   0x32c720, // green
    pharmacy:  0xec13a7, // pink
    cafe:      0xf57e0a, // amber
    restaurant:0x9100ff, // violet
    transit:   0x976876, // wtvr tf this is lmao
    education: 0xf4120b, // red
    health:    0x7c8083, // gray
    retail:    0x1d21e2, // blue
    other:     0x0c150a  // black
  };

  // Reflect poiColors in the legend UI (swatches + checkbox accent colors)
  function colorIntToHex(c){ const h = (c >>> 0).toString(16).padStart(6,'0'); return `#${h.slice(-6)}`; }
  function syncLegendColors(){
    const idMap = { grocery:'fltGrocery', pharmacy:'fltPharmacy', cafe:'fltCafe', restaurant:'fltRestaurant', transit:'fltTransit', education:'fltEducation', health:'fltHealth', retail:'fltRetail', other:'fltOther' };
    for (const k in idMap){
      const id = idMap[k]; const cb = document.getElementById(id); if (!cb) continue;
      const hex = colorIntToHex(poiColors[k] || 0x999999);
      try { cb.style.accentColor = hex; } catch(e){}
      const swatch = cb.parentElement && cb.parentElement.previousElementSibling;
      if (swatch && swatch.classList && swatch.classList.contains('swatch')){ swatch.style.background = hex; }
    }
  }

  function createPoiMarker(poi, idx){
    const p = poi.snapped || poi; if (!p || typeof p.ix !== 'number' || typeof p.iy !== 'number') return null;
    const color = poiColors[poi.type] || 0xDDDDDD;
    const icon = createPoiIcon(poi.type, color);
    const c = new PIXI.Container();
    c.addChild(icon);
    c.x = p.ix + 0.5; c.y = p.iy + 0.5; c.interactive = true; c.cursor = 'pointer';
    c.hitArea = new PIXI.Circle(0,0,6);
    const title = poi.name || poi.tags?.name || poi.type;
    c.on('pointerover', (e)=>{ const r = app.view.getBoundingClientRect(); showTooltip(title, e.data.global.x + r.left, e.data.global.y + r.top); c.scale.set(1.2); });
    c.on('pointerout', ()=> { hideTooltip(); c.scale.set(1.0); });
    c.on('pointertap', ()=>{ centerOnGrid(c.x, c.y); showFocus(c.x, c.y, title); hideTooltip(); });
    return c;
  }

  // Web tooltip DOM for POIs
  const tooltip = document.createElement('div');
  Object.assign(tooltip.style, { position:'absolute', padding:'6px 8px', borderRadius:'6px', background:'rgba(20,22,25,0.9)', color:'#e6e7e8', font:'12px system-ui, -apple-system, Segoe UI, Roboto, Arial', pointerEvents:'none', transform:'translate(-50%, -130%)', border:'1px solid rgba(255,255,255,0.08)', display:'none', zIndex:10 });
  document.body.appendChild(tooltip);
  function showTooltip(text, x, y){ tooltip.textContent = text; tooltip.style.left = `${x}px`; tooltip.style.top = `${y}px`; tooltip.style.display = 'block'; }
  function hideTooltip(){ tooltip.style.display = 'none'; }

  function renderPOIs(){
    poiContainer.removeChildren(); poiMarkers = []; if (!pois || !pois.length) return;
    for (let i=0;i<pois.length;i++){
      const marker = createPoiMarker(pois[i], i);
      if (marker){ poiContainer.addChild(marker); poiMarkers.push({ marker, poi: pois[i] }); }
    }
    updatePOIMarkerStyles();
  }
  function updatePOIMarkerStyles(){ for (const entry of poiMarkers){ const { marker, poi } = entry; const enabled = !!poiFilters[poi.type]; marker.alpha = enabled ? 1.0 : 0.28; } }

  // Venues rendering
  function renderVenues(){
    venueContainer.removeChildren();
    venueGfx = [];
    if (!venues || !venues.length) return;
    for (const v of venues){
      const g = new PIXI.Graphics();
      const pts = v.polygon.map(([iy, ix]) => ({ x: ix + 0.5, y: iy + 0.5 }));
      g.__pts = pts;
      styleVenueGraphic(g, false); // hidden by default
      g.interactive = true; g.cursor = 'pointer';
      g.on('pointerover', ()=> { styleVenueGraphic(g, true); if (pts.length){ showHoverLabel({ id:`venue_${v.name}`, text: v.name || 'Venue' }, pts[0].x, pts[0].y); }});
      g.on('pointerout', ()=> { styleVenueGraphic(g, false); hideHoverLabel(); });
      g.on('pointertap', ()=> {
        const cx = pts.reduce((a,p)=>a+p.x,0)/pts.length; const cy = pts.reduce((a,p)=>a+p.y,0)/pts.length; 
        flyTo(cx, cy, v.name || 'Venue');
        styleVenueGraphic(g, true);
        setTimeout(()=> styleVenueGraphic(g, false), 2400);
      });
      venueContainer.addChild(g);
      venueGfx.push({ g, v });
    }
  }

  function focusVenueByName(name){
    const entry = venueGfx.find(x => (x.v.name||'Venue') === name);
    if (!entry) return;
    styleVenueGraphic(entry.g, true);
    setTimeout(()=> styleVenueGraphic(entry.g, false), 2600);
  }

  // Hover label rendering
  function showHoverLabel(labelData, x, y){
    // Avoid redundant re-render
    if (currentHoverId === labelData.id) return;
    currentHoverId = labelData.id;
    hideHoverLabel();
    const baseFontSize = Math.max(10, Math.min(18, 12 + zoom * 1.5));
    const style = new PIXI.TextStyle({ fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial', fontSize: baseFontSize, fill: 0xffffff, stroke: 0x131518, strokeThickness: Math.max(2, baseFontSize * 0.15), align: 'center', wordWrap: true, wordWrapWidth: 240, letterSpacing: 0.2 });
    const t = new PIXI.Text(labelData.text, style); t.anchor.set(0.5, 1.4); t.x = x; t.y = y;

    // Bubble with arrow + shadow
    const padX = 10, padY = 8, radius = 6, arrow = 8;
    const w = Math.ceil(t.width) + padX*2, h = Math.ceil(t.height) + padY*2;
    const bg = new PIXI.Graphics();
    bg.beginFill(0x17191d, 0.96);
    bg.lineStyle(1, 0x2a2d32, 0.9);
    bg.drawRoundedRect(-w/2, -h - arrow, w, h, radius);
    // arrow
    bg.moveTo(0, -arrow); bg.lineTo(-arrow, 0); bg.lineTo(arrow, 0); bg.closePath(); bg.endFill();
    bg.x = t.x; bg.y = t.y - t.height/2 - 2;
    bg.filters = [new PIXI.filters.DropShadowFilter({ alpha:0.4, blur:2, distance:2, color:0x000000 })];

    hoverLabel = new PIXI.Container(); hoverLabel.alpha = 0; hoverLabel.addChild(bg); hoverLabel.addChild(t); labelContainer.addChild(hoverLabel);
    // Fade in
    const fade = () => { hoverLabel.alpha += 0.12; if (hoverLabel && hoverLabel.alpha < 1) requestAnimationFrame(fade); }; fade();
  }
  function hideHoverLabel(){ if (hoverLabel && hoverLabel.parent) { hoverLabel.parent.removeChild(hoverLabel); } hoverLabel = null; currentHoverId = null; }

  function labelsNear(ix, iy){
    const bx = Math.floor(ix / LABEL_BUCKET_SIZE); const by = Math.floor(iy / LABEL_BUCKET_SIZE);
    const out = [];
    // Search a 5x5 neighborhood to be safe at low zoom
    for (let dy=-2; dy<=2; dy++) for (let dx=-2; dx<=2; dx++){
      const key = `${bx+dx},${by+dy}`; const arr = labelBuckets.get(key); if (arr) out.push(...arr);
    }
    return out;
  }

  let lastHoverRAF = null;
  function renderHoverAt(sx, sy){
    if (lastHoverRAF) cancelAnimationFrame(lastHoverRAF);
    lastHoverRAF = requestAnimationFrame(()=>{
      const w = toWorld(sx, sy);
      const candidates = labelsNear(w.x, w.y);
      // Adaptive pixel threshold: easier to hit at low zoom
      const THRESHOLD_PX = Math.min(60, Math.max(18, 30 / Math.min(1.0, zoom) ));
      let best = null; let bestD = 1e9;
      for (const L of candidates){
        const dx = (L.ix - w.x); const dy = (L.iy - w.y);
        const dpx = Math.sqrt(dx*dx + dy*dy) * zoom;
        if (dpx < THRESHOLD_PX && dpx < bestD){ best = L; bestD = dpx; }
      }
      if (best){ showHoverLabel(best, best.ix + 0.5, best.iy + 0.5); app.view.style.cursor = 'pointer'; }
      else { hideHoverLabel(); app.view.style.cursor = isDragging ? 'grabbing' : 'grab'; }
    });
  }

  // Search UI elements
  const searchBox = document.getElementById('searchBox');
  const searchResults = document.getElementById('searchResults');

  function normalize(s){ return (s||'').toString().toLowerCase().trim(); }
  function labelToEntry(L){ return { kind:'label', id:`L${L.id}`, name:L.text, ix:L.ix, iy:L.iy, subtype:L.class||L.type }; }
  function poiToEntry(p,i){ const t = p.name || p.tags?.name || p.type; const loc = p.snapped || p; return { kind:'poi', id:`P${i}`, name:t||p.type, ix:loc.ix, iy:loc.iy, subtype:p.type }; }
  function venueToEntry(v,i){
    // Use centroid as fly-to
    const pts = v.polygon || []; if (!pts.length) return null;
    const cx = pts.reduce((a,p)=>a+p[1],0)/pts.length; const cy = pts.reduce((a,p)=>a+p[0],0)/pts.length;
    return { kind:'venue', id:`V${i}`, name: v.name || 'Venue', ix: cx, iy: cy, subtype: 'venue' };
  }

  function allSearchEntries(){
    const entries = [];
    for (const L of labels){ entries.push(labelToEntry(L)); }
    for (let i=0;i<pois.length;i++){ entries.push(poiToEntry(pois[i], i)); }
    for (let i=0;i<venues.length;i++){ const e = venueToEntry(venues[i], i); if (e) entries.push(e); }
    return entries;
  }

  function fuzzyScore(q, name){
    q = normalize(q); name = normalize(name);
    if (!q) return 0; if (name.includes(q)) return q.length / name.length + 0.5;
    // simple token contains score
    let score = 0; for (const tok of q.split(/\s+/)){ if (name.includes(tok)) score += tok.length / name.length; }
    return score;
  }

  function renderResults(items){
    if (!searchResults) return;
    searchResults.innerHTML = '';
    if (!items.length){ searchResults.style.display = 'none'; return; }
    for (let i=0;i<Math.min(20, items.length); i++){
      const it = items[i];
      const div = document.createElement('div'); div.className = 'item';
      const pill = document.createElement('span'); pill.className = 'pill'; pill.textContent = it.subtype || it.kind; div.appendChild(pill);
      const name = document.createElement('span'); name.textContent = it.name; div.appendChild(name);
      div.onclick = () => { flyTo(it.ix, it.iy, it.name); searchResults.style.display='none'; };
      searchResults.appendChild(div);
    }
    searchResults.style.display = 'block';
  }

  function search(q){
    const entries = allSearchEntries();
    const scored = entries.map(e => ({ e, s: fuzzyScore(q, e.name) })).filter(x => x.s > 0.1);
    scored.sort((a,b)=> b.s - a.s);
    return scored.map(x=>x.e);
  }

  function flyTo(ix, iy, name){ centerOnGrid(ix, iy); updateMinimap(); renderHoverAt(app.view.width/2, app.view.height/2); if (name) { showFocus(ix, iy, name); focusVenueByName(name); } }

  if (searchBox){
    let last = 0; searchBox.addEventListener('input', (e)=>{
      const v = searchBox.value; const now = Date.now(); if (now-last < 80) return; last = now;
      renderResults(search(v));
    });
    searchBox.addEventListener('keydown', (e)=>{ if (e.key === 'Enter'){ const items = search(searchBox.value); if (items.length){ const it = items[0]; flyTo(it.ix, it.iy, it.name); searchResults.style.display='none'; } } });
    document.addEventListener('click', (e)=>{ if (!searchResults.contains(e.target) && e.target !== searchBox) searchResults.style.display='none'; });
  }

  async function main(){
    try{
      const tex = await PIXI.Assets.load(SEMANTIC_IMG_URL);
      baseSprite = new PIXI.Sprite(tex); baseSprite.x = 0; baseSprite.y = 0; baseSprite.scale.set(1, 1); world.addChildAt(baseSprite, 0);
      gridW = tex.width; gridH = tex.height;
      await initMinimap();
      try { const resp = await fetch(POIS_URL); if (resp.ok) { pois = await resp.json(); } } catch (e) { console.warn('POIs load failed', e); }
      try { const respL = await fetch(LABELS_URL); if (respL.ok) { const raw = await respL.json(); labels = raw.map((L, i) => ({ id:i, ...L })); buildLabelIndex(); } } catch (e) { console.warn('labels load failed', e); }
      try { const respV = await fetch(VENUES_URL); if (respV.ok) { venues = await respV.json(); } } catch (e) { console.warn('venues load failed', e); }
      renderPOIs();
      renderVenues();
      hideLoading();
      setZoomToRadiusMeters(100); centerOnPOI();
      world.alpha = 0; const fadeIn = () => { world.alpha += 0.08; if (world.alpha < 1) requestAnimationFrame(fadeIn); }; fadeIn();
      updateHUD(); updateMinimap(); updateScaleBar();
      // Events
      app.view.addEventListener('wheel', onWheel, { passive: false });
      app.view.addEventListener('pointerdown', onPointerDown);
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);
      app.view.addEventListener('dblclick', onDblClick);
      app.view.addEventListener('mouseleave', ()=>{ hideHoverLabel(); app.view.style.cursor='grab'; });
      window.addEventListener('resize', onResize);
      // Toolbar
      const qi = id => document.getElementById(id);
      const btnIn = qi('btnZoomIn'), btnOut = qi('btnZoomOut'), btnCenter = qi('btnCenter'), btnFit = qi('btnFit');
      if (btnIn) btnIn.onclick = () => onWheel({ preventDefault(){}, deltaY:-240, clientX: app.view.width/2, clientY: app.view.height/2 });
      if (btnOut) btnOut.onclick = () => onWheel({ preventDefault(){}, deltaY: 240, clientX: app.view.width/2, clientY: app.view.height/2 });
      if (btnCenter) btnCenter.onclick = () => { centerOnPOI(); };
      if (btnFit) btnFit.onclick = () => { const padding=40; const zx=(app.renderer.width-padding*2)/gridW; const zy=(app.renderer.height-padding*2)/gridH; zoom=Math.min(1.0,Math.max(0.2,Math.min(zx,zy))); cameraX=gridW/2-(app.renderer.width/(2*zoom)); cameraY=gridH/2-(app.renderer.height/(2*zoom)); applyCamera(); updateHUD(); updateMinimap(); updateScaleBar(); };
      // Legend filters
      const set = (k, v) => { poiFilters[k] = v; updatePOIMarkerStyles(); };
      const cb = (id, key) => { const el = document.getElementById(id); if (el) el.onchange = e => set(key, e.target.checked); };
      cb('fltGrocery','grocery'); cb('fltPharmacy','pharmacy'); cb('fltCafe','cafe'); cb('fltRestaurant','restaurant'); cb('fltTransit','transit');
      cb('fltEducation','education'); cb('fltHealth','health'); cb('fltRetail','retail'); cb('fltOther','other');
      // All/None actions
      const btnAll = document.getElementById('fltAll');
      const btnNone = document.getElementById('fltNone');
      function syncLegendCheckboxes(){
        const map = { grocery:'fltGrocery', pharmacy:'fltPharmacy', cafe:'fltCafe', restaurant:'fltRestaurant', transit:'fltTransit', education:'fltEducation', health:'fltHealth', retail:'fltRetail', other:'fltOther' };
        for (const k in map){ const el = document.getElementById(map[k]); if (el) el.checked = !!poiFilters[k]; }
      }
      if (btnAll) btnAll.onclick = () => { for (const k in poiFilters) poiFilters[k] = true; syncLegendCheckboxes(); updatePOIMarkerStyles(); };
      if (btnNone) btnNone.onclick = () => { for (const k in poiFilters) poiFilters[k] = false; syncLegendCheckboxes(); updatePOIMarkerStyles(); };
      // Apply colors to legend from poiColors
      syncLegendColors();
      // Keyboard shortcuts
      window.addEventListener('keydown', (e)=>{
        if (e.repeat) return;
        if (e.key === '+' || e.key === '=') onWheel({ preventDefault(){}, deltaY:-240, clientX: app.view.width/2, clientY: app.view.height/2 });
        if (e.key === '-' || e.key === '_') onWheel({ preventDefault(){}, deltaY: 240, clientX: app.view.width/2, clientY: app.view.height/2 });
        const pan = (dx,dy)=>{ cameraX += dx/(zoom); cameraY += dy/(zoom); applyCamera(); updateMinimap(); };
        if (e.key === 'ArrowLeft' || e.key==='a') pan(-60,0);
        if (e.key === 'ArrowRight'|| e.key==='d') pan(60,0);
        if (e.key === 'ArrowUp'   || e.key==='w') pan(0,-60);
        if (e.key === 'ArrowDown' || e.key==='s') pan(0,60);
        if (e.key === '0') { setZoomToRadiusMeters(100); centerOnPOI(); updateMinimap(); updateScaleBar(); }
        if (e.key === 'Escape') { clearFocus(); hideHoverLabel(); }
      });
    } catch (e){
      console.error(e);
      const err = document.createElement('div'); err.style.position = 'absolute'; err.style.bottom = '8px'; err.style.left = '8px'; err.style.color = '#f88'; err.style.fontFamily = 'monospace'; err.textContent = `Error: ${e}`; document.body.appendChild(err);
    }
  }

  main().catch(err => console.error(err));
})();
