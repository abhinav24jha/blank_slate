(function(){
  const appDiv = document.getElementById('app');
  const hudTiles = document.getElementById('hudTiles');
  const hudZoom = document.getElementById('hudZoom');
  const hudPanel = document.querySelector('.hud');
  // Docked HUD container (below scale bar)
  const agentHudDock = document.getElementById('agentHUDDock');
  const scaleBarEl = document.querySelector('.scalebar');
  let agentHudEl = null;
  // Metrics + feed elements (will be available after DOM loads)
  let elTrips = null;
  let elAvgTime = null;
  let elAvgDist = null;
  let elByCat = null;
  let feedEl = null;
  let thoughtsSelect = null;
  let thoughtsContent = null;
  let feedFilterMode = 'all'; // 'all', 'chats', 'decisions'

  const SEMANTIC_IMG_URL = '../out/society145_1km/semantic_preview.png';
  const BASELINE_DIR = '../out/society145_1km';
  let currentScenario = 'baseline';
  function scenarioAssetsDir(){
    if (currentScenario === 'baseline') return BASELINE_DIR;
    // Viewer experiments: from /simulation/viewer/, go up twice to reach root, then down to experiments
    return `../../simulation/out/experiments/exp_viewer/${currentScenario}/assets`;
  }
  function poisUrl(){ return `${scenarioAssetsDir()}/pois.json`; }
  function labelsUrl(){ return `${scenarioAssetsDir()}/labels.json`; }
  function venuesUrl(){ return `${scenarioAssetsDir()}/venues.json`; }
  const MAIN_POI_LON = -80.5381896;
  const MAIN_POI_LAT = 43.4765757;

  // Brain server config
  const BRAIN_URL = 'http://127.0.0.1:9000';
  let runId = null;
  let orchestrator = null; // will be set after start_run
  const METRICS_FLUSH_MS = 8000;
  let metricsBuffer = [];
  let lastMetricsFlush = performance.now();

  async function httpPostJson(url, body){
    try{
      const r = await fetch(url, { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch(e){ console.warn('httpPostJson failed', url, e); return null; }
  }

  async function brainStartRun(hypothesisId, seed, speed){
    const resp = await httpPostJson(`${BRAIN_URL}/start_run`, { hypothesisId, seed, speed });
    return resp && resp.runId ? resp.runId : null;
  }

  function getCurrentScenarioBiases(){
    const biasMap = {
      'h001': {'grocery': 0.5, 'pharmacy': 0.4, 'cafe': 0.6},
      'h002': {'education': 0.2, 'leisure': 0.5, 'other': 0.5},
      'h003': {'restaurant': 0.5, 'cafe': 0.4, 'other': 0.3},
      'h004': {'restaurant': 0.6, 'cafe': 0.2, 'other': 0.2}
    };
    return biasMap[currentScenario] || {};
  }

  async function brainDecide(agents, context){
    if (!runId) return { decisions: [] };
    const scenarioContext = {
      scenario_id: currentScenario !== 'baseline' ? currentScenario : undefined,
      biases: getCurrentScenarioBiases(),
      ...context
    };
    const payload = { runId, agents, context: scenarioContext };
    const resp = await httpPostJson(`${BRAIN_URL}/decide`, payload);
    return resp || { decisions: [] };
  }

  async function brainSendMetrics(){
    if (!runId || metricsBuffer.length === 0) return;
    const batch = metricsBuffer.slice(); metricsBuffer.length = 0;
    await httpPostJson(`${BRAIN_URL}/metrics`, { runId, samples: batch });
  }

  async function brainEndRun(){
    if (!runId) return;
    await brainSendMetrics();
    await httpPostJson(`${BRAIN_URL}/end_run`, { runId });
  }

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

  // Navgraph arrays
  let walkableGrid = null; // Uint8Array length H*W
  let costGrid = null;     // Uint8Array length H*W

  // Pathfinding worker
  let pathWorker = null;
  let workerReady = false;
  let pathReqId = 0;
  const pendingPaths = new Map();

  function initWorker(H, W){
    if (pathWorker) return;
    pathWorker = new Worker('path_worker.js', { type:'module' });
    pathWorker.onmessage = (ev)=>{
      const msg = ev.data;
      if (msg.type === 'ready'){ workerReady = true; return; }
      if (msg.type === 'path'){
        const resolver = pendingPaths.get(msg.id);
        pendingPaths.delete(msg.id);
        if (resolver) resolver(msg);
      }
    };
    // Send copies to keep local arrays available for spawning/snap
    const wCopy = new Uint8Array(walkableGrid); const cCopy = new Uint8Array(costGrid);
    pathWorker.postMessage({ type:'init', H, W, walkable: wCopy, cost: cCopy });
  }

  function requestPath(start, goal){
    return new Promise((resolve)=>{
      const id = ++pathReqId;
      pendingPaths.set(id, resolve);
      pathWorker.postMessage({ type:'path', id, start, goal });
    });
  }

  // Agents
  const agents = [];
  const idToAgent = new Map();
  let heroSeq = 0;
  const agentLayer = new PIXI.Container();
  world.addChild(agentLayer);
  const intentLayer = new PIXI.Container(); // overlay labels above agents
  world.addChild(intentLayer);
  const speedMultipliers = [1,2,4,100];
  let speedIdx = 0; // 1x by default
  let selectedAgent = null;
  let followMode = false;
  // Intent chips are only shown for the selected agent when enabled
  let showIntents = true;

  // Needs system
  const NEEDS = ['hunger', 'caffeine', 'groceries', 'health', 'education', 'leisure', 'social'];
  const NEED_DECAY_RATES = { hunger: 0.3, caffeine: 0.5, groceries: 0.1, health: 0.05, education: 0.08, leisure: 0.2, social: 0.15 };
  const POI_SATISFIES = {
    grocery: ['hunger', 'groceries'], pharmacy: ['health'], cafe: ['caffeine', 'social'], 
    restaurant: ['hunger', 'social'], transit: [], education: ['education'], 
    health: ['health'], retail: ['leisure'], other: ['leisure']
  };

  // Agent roles (Waterloo university area demographics)
  const AGENT_ROLES = {
    student: { weight: 0.65, needWeights: { hunger: 1.2, caffeine: 1.5, education: 1.8, social: 1.3, groceries: 0.8, health: 0.9, leisure: 1.1 } },
    resident: { weight: 0.20, needWeights: { hunger: 1.0, caffeine: 1.0, groceries: 1.5, health: 1.2, education: 0.3, social: 1.0, leisure: 1.0 } },
    worker: { weight: 0.10, needWeights: { hunger: 1.1, caffeine: 1.8, groceries: 1.2, health: 1.0, education: 0.5, social: 0.8, leisure: 0.7 } },
    visitor: { weight: 0.05, needWeights: { hunger: 1.3, caffeine: 1.2, groceries: 0.3, health: 0.8, education: 0.8, social: 1.4, leisure: 1.6 } }
  };

  function sampleRole(){
    const r = Math.random();
    let acc = 0;
    for (const [role, data] of Object.entries(AGENT_ROLES)){
      acc += data.weight;
      if (r <= acc) return role;
    }
    return 'student';
  }

  function initNeeds(role){
    const needs = {};
    const weights = AGENT_ROLES[role].needWeights;
    for (const need of NEEDS){
      needs[need] = Math.random() * 0.6 * (weights[need] || 1.0);
    }
    return needs;
  }

  // Optional pixel-art people sprites (loaded as 4 separate PNG files)
  let peopleSprites = null; // {characterType: {dir: [textures...]}}
  async function loadPeopleSprites(){
    // Try multiple character types
    const characterTypes = [
      'male_civillian',
      'female_civillian', 
      'female_uni_student'
    ];
    
    peopleSprites = {};
    
    for (const charType of characterTypes) {
      const base = `sprites/${charType}/`;
      const variants = {
        down:  [`${charType}_forward.png`, `${charType.replace('_uni_', '_')}_forward.png`],
        up:    [`${charType}_backward.png`, `${charType.replace('_uni_', '_')}_backward.png`],
        left:  [`${charType}_left.png`, `${charType.replace('_uni_', '_')}_left.png`],
        right: [`${charType}_right.png`, `${charType.replace('_uni_', '_')}_right.png`]
      };
      async function loadFirst(urls){
        for (const u of urls){
          try { const res = await fetch(base + u, { method:'HEAD' }); if (res.ok) return base + u; } catch(_) {}
        }
        return null;
      }
      async function loadSingleSprite(url){
        console.log(`Loading single sprite: ${url}`);
        const tex = await PIXI.Assets.load(url);
        console.log(`Single texture loaded: ${tex.width}x${tex.height}`);
        
        // Create a processed version with background removal
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = tex.width;
        canvas.height = tex.height;
        
        // Draw original image
        const img = tex.baseTexture.resource.source;
        ctx.drawImage(img, 0, 0);
        
        // Get image data and remove white/light backgrounds
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const data = imageData.data;
        
        for (let i = 0; i < data.length; i += 4) {
          const r = data[i];
          const g = data[i + 1];
          const b = data[i + 2];
          
          // Remove white and very light colors (typical AI background)
          if (r > 240 && g > 240 && b > 240) {
            data[i + 3] = 0; // Make transparent
          }
          // Also remove light gray backgrounds
          else if (r > 220 && g > 220 && b > 220 && Math.abs(r-g) < 10 && Math.abs(g-b) < 10) {
            data[i + 3] = 0;
          }
        }
        
        ctx.putImageData(imageData, 0, 0);
        
        // Create new texture from processed canvas
        const processedTex = PIXI.Texture.from(canvas);
        console.log(`Processed texture: ${processedTex.width}x${processedTex.height}`);
        
        // For single pose images, just duplicate the texture 4 times for animation
        return [processedTex, processedTex, processedTex, processedTex];
      }
      
      try {
        const downUrl = await loadFirst(variants.down);
        const upUrl   = await loadFirst(variants.up);
        const leftUrl = await loadFirst(variants.left);
        const rightUrl= await loadFirst(variants.right);
        console.log(`Found sprite URLs for ${charType}:`, {downUrl, upUrl, leftUrl, rightUrl});
        if (downUrl && upUrl && leftUrl && rightUrl) {
          const [down, up, left, right] = await Promise.all([
            loadSingleSprite(downUrl),
            loadSingleSprite(upUrl),
            loadSingleSprite(leftUrl),
            loadSingleSprite(rightUrl)
          ]);
          peopleSprites[charType] = { down, up, left, right };
          console.log(`Sprites loaded for ${charType}`);
        } else {
          console.warn(`Missing sprite files for ${charType}`);
        }
      } catch(e){ console.warn(`Sprite load failed for ${charType}:`, e); }
    }
    
    const loadedTypes = Object.keys(peopleSprites);
    if (loadedTypes.length > 0) {
      console.log('All sprites loaded successfully:', loadedTypes);
      return true;
    } else {
      console.warn('No sprite types loaded, falling back to vector graphics');
      return false;
    }
  }

  // ---- Walkable helpers ----
  function inBounds(ix, iy){ return 0<=ix && ix<gridW && 0<=iy && iy<gridH; }
  function isWalkable(ix, iy){ if (!walkableGrid) return true; if (!inBounds(ix,iy)) return false; return walkableGrid[iy*gridW + ix] === 1; }
  function sampleWalkableNear(cx, cy, maxR=40){
    for (let r=0;r<=maxR;r++){
      const y0 = Math.max(0, cy-r), y1 = Math.min(gridH-1, cy+r);
      const x0 = Math.max(0, cx-r), x1 = Math.min(gridW-1, cx+r);
      for (let y=y0;y<=y1;y+=2){ for (let x=x0;x<=x1;x+=2){ if (isWalkable(x,y)) return { ix:x, iy:y }; }}
    }
    return { ix: Math.max(0, Math.min(gridW-1, cx)), iy: Math.max(0, Math.min(gridH-1, cy)) };
  }
  function snapToWalkable(ix, iy, maxR=30){ const res = sampleWalkableNear(ix, iy, maxR); return [res.iy, res.ix]; }

  function createAgent(ix, iy, color=0xffffff, isFullAgent=true){
    const role = sampleRole();
    const needs = initNeeds(role);
    const sprite = new PIXI.Container();
    let footL = null, footR = null, anim = null, charType = null;
    
    // Trail for full agents
    const trail = isFullAgent ? new PIXI.Graphics() : null;
    if (trail) {
      trail.alpha = 0.6;
      agentLayer.addChildAt(trail, 0); // behind agent
    }
    
    if (peopleSprites && Object.keys(peopleSprites).length > 0){
      // Randomly pick a character type
      const availableTypes = Object.keys(peopleSprites);
      charType = availableTypes[Math.floor(Math.random() * availableTypes.length)];
      const charSprites = peopleSprites[charType];
      const textures = charSprites.down || Object.values(charSprites)[0];
      anim = new PIXI.AnimatedSprite(textures); anim.animationSpeed = 0.18; anim.play();
      const targetSize = 6; // world cells
      const scale = targetSize / Math.max(anim.texture.width, anim.texture.height);
      anim.scale.set(scale, scale);
      anim.anchor.set(0.5, 0.82);
      sprite.addChild(anim);
    } else {
      // Vector fallback
      const body = new PIXI.Graphics();
      body.lineStyle(1.2, 0x111111, 0.95);
      body.beginFill(color, 0.96);
      body.drawRoundedRect(-2.2, -3.0, 4.4, 6.0, 1.2);
      body.endFill();
      footL = new PIXI.Graphics(); footL.beginFill(0x111111, 0.95); footL.drawCircle(-1.2, 3.2, 0.8); footL.endFill();
      footR = new PIXI.Graphics(); footR.beginFill(0x111111, 0.95); footR.drawCircle( 1.2, 3.2, 0.8); footR.endFill();
      sprite.addChild(body); sprite.addChild(footL); sprite.addChild(footR);
    }
    
    sprite.x = ix + 0.5; sprite.y = iy + 0.5;
    // Make ALL agents clickable (heroes and background). Improves UX when they look identical.
    sprite.eventMode = 'static';
    sprite.cursor = 'pointer';
    // Generous hit area for tiny sprites
    sprite.hitArea = new PIXI.Circle(0, 0, 4.5);
    sprite.on('pointertap', () => selectAgent(sprite.__agent));
    agentLayer.addChild(sprite);

    // Intent chip (overlay)
    const chip = new PIXI.Container();
    const bg = new PIXI.Graphics();
    const txt = new PIXI.Text('—', new PIXI.TextStyle({ fontFamily:'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial', fontSize: 10, fill: 0xffffff, stroke: 0x000000, strokeThickness: 2 }));
    txt.anchor.set(0.5, 1.4);
    chip.addChild(bg); chip.addChild(txt);
    chip.visible = showIntents && isFullAgent;
    intentLayer.addChild(chip);
    
    const agent = { 
      sprite, ix, iy, tx: ix, ty: iy, path: [], progress: 0, speed: 1.4, 
      phase: Math.random()*Math.PI*2, footL, footR, anim, charType, idle:0,
      role, needs, isFullAgent, trail, trailPoints: [], lastNeedCheck: 0, currentGoal: null,
      id: isFullAgent ? `F${heroSeq++}` : `S${Math.floor(Math.random()*1e6)}`,
      lastThought: null, lastIntent: null, _trip: null,
      _chip: { wrap: chip, bg, txt }
    };
    sprite.__agent = agent;
    idToAgent.set(agent.id, agent);
    return agent;
  }

  function setAgentPath(agent, path){
    agent.path = path || []; agent.progress = 0;
    // Start trip metrics
    if (agent.path && agent.path.length > 1){
      const [sy,sx] = agent.path[0];
      agent._trip = { 
        startTime: performance.now(), 
        start: [sy,sx], 
        last: [sy,sx], 
        dist: 0, 
        category: (agent.currentGoal && agent.currentGoal.poi && agent.currentGoal.poi.type) || agent.lastIntent || 'unknown' 
      };
      console.log(`TRIP START: ${agent.id} -> ${agent._trip.category}, path length: ${agent.path.length}`);
      // Update intent chip text immediately
      if (agent._chip && agent._chip.txt){ agent._chip.txt.text = agent._trip.category; }
    }
  }

  function headingToDir(dx, dy){
    if (!peopleSprites) return 'right';
    const ang = Math.atan2(dy, dx);
    const a = ((ang + Math.PI*2) % (Math.PI*2));
    if (a > Math.PI*7/4 || a <= Math.PI/4) return 'right';
    if (a <= Math.PI*3/4) return 'up';
    if (a <= Math.PI*5/4) return 'left';
    return 'down';
  }

  function selectAgent(agent){
    selectedAgent = agent;
    followMode = true;
    // Highlight selected agent
    for (const a of agents) {
      if (a.sprite) a.sprite.alpha = (a === agent) ? 1.0 : 0.7;
      // Only show intent chip for selected agent
      if (a._chip && a._chip.wrap) a._chip.wrap.visible = showIntents && (a === agent);
    }
    console.log(`Selected ${agent.role}: needs=`, agent.needs);
    updateSelectionHUD();
  }

  function topNeeds(needs, k=3){
    const arr = Object.entries(needs||{}).sort((a,b)=> b[1]-a[1]);
    return arr.slice(0,k).map(([n,v])=> `${n}:${v.toFixed(2)}`).join('  ');
  }

  function updateSelectionHUD(){
    // Use floating HUD near the selected agent; remove if no selection
    if (!selectedAgent){ if (agentHudEl && agentHudEl.remove) agentHudEl.remove(); agentHudEl = null; return; }
    const a = selectedAgent;
    const goalTxt = a.currentGoal && a.currentGoal.loc ? ((a.currentGoal.poi && (a.currentGoal.poi.name || a.currentGoal.poi.type)) || a.lastIntent || '—') : (a.lastIntent || '—');
    const thought = a.lastThought ? `"${a.lastThought}"` : '—';
    console.log(`HUD UPDATE for ${a.id}: goal="${goalTxt}", intent="${a.lastIntent}", thought="${a.lastThought}"`);

    // Build top-3 needs with bars
    const sorted = Object.entries(a.needs||{}).sort((x,y)=>y[1]-x[1]).slice(0,3);
    const needRows = sorted.map(([k,v])=>{
      const pct = Math.max(0, Math.min(1, v)) * 100;
      return `<div class="row"><div class="badge">${k}</div><div class="bar"><div class="fill" style="width:${pct.toFixed(0)}%"></div></div><div class="muted" style="width:30px; text-align:right;">${v.toFixed(2)}</div></div>`;
    }).join('');

    // Create element if needed
    if (!agentHudEl){ agentHudEl = document.createElement('div'); agentHudEl.className = 'agentHUD panel'; (document.body).appendChild(agentHudEl); }
    agentHudEl.innerHTML = `
      <div class="row" style="margin-bottom:8px; pointer-events:none;">
        <div class="title">${a.id}</div>
        <div class="badge">${a.role}</div>
        <div class="badge" style="background:${a.isFullAgent?'#0b1220':'#191b1e'}; border-color:rgba(96,165,250,0.35); color:#93c5fd;">${a.isFullAgent?'full':'sim'}</div>
      </div>
      ${needRows}
      <div class="row"><div class="muted">Goal</div><div class="mono" style="flex:1; text-align:right;">${goalTxt}</div></div>
      <div class="row"><div class="muted">Intent</div><div class="mono" style="flex:1; text-align:right;">${a.lastIntent || '—'}</div></div>
      <div class="row" style="align-items:flex-start;"><div class="muted">Thought</div><div style="flex:1; text-align:right; opacity:0.9;">${thought}</div></div>
    `;

    // If dock exists, let CSS place it; otherwise fall back to floating next to the agent
    // Dock the HUD near the scale bar with smart placement (prefer ABOVE, else BELOW)
    const vw = window.innerWidth; const vh = window.innerHeight;
    const cardW = agentHudEl.offsetWidth || 320; const cardH = agentHudEl.offsetHeight || 170;
    let left = 16, top = vh - cardH - 16;
    if (scaleBarEl){
      const r = scaleBarEl.getBoundingClientRect();
      // Try above scale bar first
      if (r.top - 12 - cardH >= 12){
        top = r.top - 12 - cardH;
      } else {
        top = Math.min(vh - cardH - 16, r.bottom + 12);
      }
      left = Math.max(12, Math.min(vw - cardW - 12, r.left));
    }
    agentHudEl.style.position = 'fixed';
    agentHudEl.style.left = `${left}px`;
    agentHudEl.style.top  = `${top}px`;
    agentHudEl.style.zIndex = 6;
    agentHudEl.style.backdropFilter = 'blur(4px)';
    agentHudEl.style.background = 'rgba(18,19,20,0.6)';
    agentHudEl.style.border = '1px solid rgba(255,255,255,0.08)';
    agentHudEl.style.borderRadius = '10px';
    agentHudEl.style.boxShadow = '0 6px 18px rgba(0,0,0,0.35)';
  }

  // Aggressive meeting detection for demo (heroes within 6m for >0.5s)
  const MEET_DIST = 6.0; // in grid cells (~meters) - very permissive for demo
  const MEET_TIME = 0.5; // seconds - very fast to trigger chats
  const meetClock = new Map(); // key: 'i-j' -> seconds together
  function detectMeetings(dt){
    const fullAgents = agents.filter(a => a.isFullAgent);
    for (let i=0;i<fullAgents.length;i++){
      for (let j=i+1;j<fullAgents.length;j++){
        const a = fullAgents[i], b = fullAgents[j];
        const dx = a.sprite.x - b.sprite.x; const dy = a.sprite.y - b.sprite.y;
        const d2 = dx*dx + dy*dy;
        const key = `${i}-${j}`;
        if (d2 <= MEET_DIST*MEET_DIST){
          meetClock.set(key, (meetClock.get(key)||0) + dt);
        } else {
          meetClock.delete(key);
        }
      }
    }
    const events = [];
    for (const [key, t] of meetClock){ if (t >= MEET_TIME){ events.push(key); meetClock.set(key, 0); } }
    return events; // array of pairs 'i-j'
  }

  function findBestPOI(agent){
    // Find POI that best satisfies current highest need
    let maxNeed = 0; let bestNeedType = null;
    for (const [need, value] of Object.entries(agent.needs)){
      if (value > maxNeed){ maxNeed = value; bestNeedType = need; }
    }
    if (!bestNeedType || maxNeed < 0.3) return null;
    
    // Find POIs that satisfy this need
    const candidates = [];
    for (const poi of pois){
      const satisfies = POI_SATISFIES[poi.type] || [];
      if (satisfies.includes(bestNeedType)){
        const loc = poi.snapped || poi;
        if (loc && typeof loc.ix === 'number' && typeof loc.iy === 'number'){
          const dist = Math.abs(loc.ix - agent.sprite.x) + Math.abs(loc.iy - agent.sprite.y);
          candidates.push({ poi, loc, dist, need: bestNeedType });
        }
      }
    }
    if (candidates.length === 0) return null;
    
    // Pick closest
    candidates.sort((a,b) => a.dist - b.dist);
    return candidates[0];
  }

  // --- Metrics UI aggregation ---
  const metricsAgg = { trips:0, sumMs:0, sumDist:0, byCat:{} };
  function fmtMs(ms){ if (!ms && ms!==0) return '—'; const s = ms/1000; return s>=60? `${(s/60).toFixed(1)} min` : `${s.toFixed(1)} s`; }
  function fmtDistCells(c){ const m = c*cellM; return m>=1000? `${(m/1000).toFixed(2)} km` : `${Math.round(m)} m`; }
  function updateMetricsUI(evt){
    if (evt && evt.add){
      metricsAgg.trips++;
      metricsAgg.sumMs += evt.add.ms;
      metricsAgg.sumDist += evt.add.dist;
      const k = evt.add.cat || 'unknown'; metricsAgg.byCat[k] = (metricsAgg.byCat[k]||0)+1;
    }
    if (elTrips) elTrips.textContent = String(metricsAgg.trips);
    if (elAvgTime) elAvgTime.textContent = metricsAgg.trips? fmtMs(metricsAgg.sumMs/metricsAgg.trips) : '—';
    if (elAvgDist) elAvgDist.textContent = metricsAgg.trips? fmtDistCells(metricsAgg.sumDist/metricsAgg.trips) : '—';
    if (elByCat) {
      const parts = Object.entries(metricsAgg.byCat).sort((a,b)=>b[1]-a[1]).slice(0,4).map(([k,v])=>`${k}:${v}`);
      elByCat.textContent = parts.join('  ');
    }
  }

  function stepAgents(dt){
    if (!agents || !Array.isArray(agents)) return;
    const s = speedMultipliers[speedIdx];
    for (const a of agents){
      // Update needs over time
      a.lastNeedCheck += dt;
      if (a.lastNeedCheck > 2.0){ // check every 2 seconds
        for (const need of NEEDS){
          a.needs[need] = Math.min(1.0, a.needs[need] + (NEED_DECAY_RATES[need] || 0.1) * dt * 2.0);
        }
        a.lastNeedCheck = 0;
      }
      
      if (!a.path || a.path.length<2){ 
        a.idle += dt; 
        // Update trail
        if (a.trail && a.isFullAgent){
          a.trailPoints.push({ x: a.sprite.x, y: a.sprite.y, time: performance.now() });
          if (a.trailPoints.length > 20) a.trailPoints.shift();
          a.trail.clear();
          if (a.trailPoints.length > 1){
            a.trail.lineStyle(2, 0x3b82f6, 0.4);
            a.trail.moveTo(a.trailPoints[0].x, a.trailPoints[0].y);
            for (let i=1; i<a.trailPoints.length; i++){
              a.trail.lineTo(a.trailPoints[i].x, a.trailPoints[i].y);
            }
          }
        }
        // If idle full agents have a strong need, nudge them to move so metrics accumulate
        if (a.isFullAgent && a.idle > 2.0 && workerReady){
          const bestPOI = findBestPOI(a);
          if (bestPOI){
            const cur = [Math.round(a.sprite.y-0.5), Math.round(a.sprite.x-0.5)];
            const goal = [bestPOI.loc.iy, bestPOI.loc.ix];
            requestPath(cur, goal).then(res=>{ if (res && res.ok) { setAgentPath(a, res.path); a.currentGoal = bestPOI; a.lastIntent = bestPOI.poi?.type || a.lastIntent; if (a._chip && a._chip.txt && a.lastIntent) a._chip.txt.text = a.lastIntent; a.idle = 0; if (selectedAgent===a) updateSelectionHUD(); } });
          }
        }
        continue; 
      }
      
      const stepSpeed = a.speed * s;
      // Move along polyline in grid space
      let i0 = Math.floor(a.progress);
      let i1 = i0 + 1;
      if (i1 >= a.path.length){ a.path = []; continue; }
      const p0 = a.path[i0]; const p1 = a.path[i1];
      if (!p0 || !p1 || !Array.isArray(p0) || !Array.isArray(p1)) { a.path = []; continue; }
      const [y0,x0] = p0; const [y1,x1] = p1;
      const t = a.progress - i0;
      const gx = x0 + (x1 - x0) * t;
      const gy = y0 + (y1 - y0) * t;
      a.sprite.x = gx + 0.5; a.sprite.y = gy + 0.5;
      
      // Update trail
      if (a.trail && a.isFullAgent){
        a.trailPoints.push({ x: a.sprite.x, y: a.sprite.y, time: performance.now() });
        if (a.trailPoints.length > 20) a.trailPoints.shift();
        a.trail.clear();
        if (a.trailPoints.length > 1){
          a.trail.lineStyle(2, 0x3b82f6, 0.4);
          a.trail.moveTo(a.trailPoints[0].x, a.trailPoints[0].y);
          for (let i=1; i<a.trailPoints.length; i++){
            a.trail.lineTo(a.trailPoints[i].x, a.trailPoints[i].y);
          }
        }
      }
      
      // Heading
      const ang = Math.atan2((y1 - y0), (x1 - x0));
      a.sprite.rotation = peopleSprites ? 0 : ang;
      if (a.anim && peopleSprites && a.charType){
        const dir = headingToDir((x1-x0), (y1-y0));
        const charSprites = peopleSprites[a.charType];
        if (charSprites) {
          const tex = charSprites[dir]; 
          if (tex && a.anim.textures !== tex){ a.anim.textures = tex; a.anim.play(); }
        }
      }
      // Feet bobbing
      if (a.footL && a.footR){
        a.phase += dt * stepSpeed * 6.0;
        const off = Math.sin(a.phase) * 0.35;
        a.footL.position.y = 3.2 + off;
        a.footR.position.y = 3.2 - off;
      }
      // Advance
      a.progress += stepSpeed * dt;
      // Position intent chip above agent
      if (a._chip && a._chip.wrap){ a._chip.wrap.x = a.sprite.x; a._chip.wrap.y = a.sprite.y - 6.5; a._chip.wrap.visible = showIntents && (selectedAgent === a); }
      // Track distance while moving
      if (a._trip && a.path && a.path.length > 1){
        const i0b = Math.max(0, Math.floor(a.progress)-1);
        const pA = a.path[i0b]; const pB = a.path[i0b+1] || pA;
        if (Array.isArray(pA) && Array.isArray(pB)){
          const dy = pB[0]-pA[0], dx = pB[1]-pA[1];
          a._trip.dist += Math.hypot(dx, dy);
          a._trip.last = pB;
        }
      }
      if (a.progress >= a.path.length-1){ 
        // Reached destination - satisfy needs if at POI
        if (a.currentGoal && a.currentGoal.need){
          a.needs[a.currentGoal.need] = Math.max(0, a.needs[a.currentGoal.need] - 0.4);
        }
        // Close trip metrics
        if (a._trip){
          const dt_ms = performance.now() - a._trip.startTime;
          const meters = a._trip.dist * cellM;
          console.log(`TRIP COMPLETE: ${a.id} -> ${a._trip.category} in ${(dt_ms/1000).toFixed(1)}s, ${meters.toFixed(0)}m`);
          metricsBuffer.push({ kind:'trip', agent:a.id, role:a.role, cat:a._trip.category, ms: Math.round(dt_ms), dist_m: Math.round(meters) });
          updateMetricsUI({ add: { ms: dt_ms, dist: a._trip.dist, cat: a._trip.category } });
          // Immediately flush small batches so the UI updates live
          if (metricsBuffer.length >= 1) brainSendMetrics();
          a._trip = null;
        }
        a.path = []; a.currentGoal = null;
      }
      a.idle = 0;
    }
    
    // Follow mode camera
    if (followMode && selectedAgent && selectedAgent.sprite){
      const padding = 0.3;
      const targetX = selectedAgent.sprite.x - app.renderer.width/(2*zoom);
      const targetY = selectedAgent.sprite.y - app.renderer.height/(2*zoom);
      cameraX += (targetX - cameraX) * padding;
      cameraY += (targetY - cameraY) * padding;
      applyCamera();
    }

    // Meetings detection and chat requests (via orchestrator)
    const meetPairs = detectMeetings(dt);
    if (meetPairs.length && orchestrator){
      console.log(`MEETING DETECTED: ${meetPairs.length} pairs`);
      const fullAgents = agents.filter(x=>x.isFullAgent);
      const chatPairs = meetPairs.map(k => { const [i,j] = k.split('-').map(n=>parseInt(n,10)); return { aId: fullAgents[i].id, bId: fullAgents[j].id }; });
      // Schedule meeting participants for immediate decisions and request chats
      const idxSet = new Set(meetPairs.flatMap(k => k.split('-').map(n => parseInt(n,10))));
      for (const idx of idxSet){ orchestrator.schedule(fullAgents[idx].id, 'event'); }
      orchestrator.chat(chatPairs);
    }
  }

  // UI speed buttons
  function wireSpeedButtons(){
    const speedButtons = [
      { id: 'speed1', idx: 0 },   // 1x
      { id: 'speed2', idx: 1 },   // 2x  
      { id: 'speed4', idx: 2 },   // 4x
      { id: 'speed100', idx: 3 }  // 100x
    ];
    
    speedButtons.forEach(({id, idx}) => {
      const el = document.getElementById(id);
      if (el) {
        el.onclick = () => {
          speedIdx = idx;
          // Update visual state
          speedButtons.forEach(({id: btnId}) => {
            const btn = document.getElementById(btnId);
            if (btn) btn.classList.remove('active');
          });
          el.classList.add('active');
        };
      }
    });
    
    // Set initial active state
    const initialBtn = document.getElementById('speed1');
    if (initialBtn) initialBtn.classList.add('active');
  }

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

  let showBaselinePOIs = true;

  function createPoiMarker(poi, idx){
    const p = poi.snapped || poi; if (!p || typeof p.ix !== 'number' || typeof p.iy !== 'number') return null;
    
    // Check if this is an added POI (exact name match)
    const isAddedPOI = poi._isAdded === true || (poi.name && ['Society 145 Convenience','Front RX','Lot Cafe','Market Bites 1','Market Bites 2','Plaza Cafe','Food Hall Vendor A','Food Hall Vendor B','Food Hall Vendor C'].includes(poi.name));
    
    // In scenario mode, hide baseline POIs unless explicitly shown
    if (currentScenario !== 'baseline' && !isAddedPOI && !showBaselinePOIs) {
      return null; // Don't render baseline POIs in scenario mode
    }
    
    const color = poiColors[poi.type] || 0xDDDDDD;
    const c = new PIXI.Container();
    
    if (isAddedPOI && currentScenario !== 'baseline') {
      // NEW POI: Large, prominent, clearly labeled
      const bg = new PIXI.Graphics();
      bg.beginFill(0x22c55e, 0.2);
      bg.lineStyle(3, 0x22c55e, 1.0);
      bg.drawRoundedRect(-15, -15, 30, 30, 8);
      bg.endFill();
      c.addChild(bg);
      
      // Large icon
      const icon = createPoiIcon(poi.type, color);
      icon.scale.set(1.5);
      c.addChild(icon);
      
      // Clear label above
      const labelText = poi.name || poi.type;
      const label = new PIXI.Text(labelText, new PIXI.TextStyle({
        fontSize: 12,
        fill: 0xffffff,
        stroke: 0x000000,
        strokeThickness: 3,
        fontWeight: 'bold'
      }));
      label.anchor.set(0.5, 1.2);
      label.y = -20;
      c.addChild(label);
      
      // NEW badge
      const newBadge = new PIXI.Text('NEW', new PIXI.TextStyle({
        fontSize: 8,
        fill: 0xffffff,
        backgroundColor: 0x22c55e,
        padding: 2
      }));
      newBadge.anchor.set(0.5, 0.5);
      newBadge.x = 12;
      newBadge.y = -12;
      c.addChild(newBadge);
      
    } else {
      // BASELINE POI: Normal size, dimmed if in scenario mode
      const icon = createPoiIcon(poi.type, color);
      c.addChild(icon);
      if (currentScenario !== 'baseline') {
        c.alpha = 0.3; // Dim baseline POIs in scenario mode
      }
    }
    
    c.x = p.ix + 0.5; c.y = p.iy + 0.5; c.interactive = true; c.cursor = 'pointer';
    c.hitArea = new PIXI.Circle(0,0,isAddedPOI ? 20 : 6);
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
    try { bg.filters = [new PIXI.filters.DropShadowFilter({ alpha:0.4, blur:2, distance:2, color:0x000000 })]; } catch(_) {}

    hoverLabel = new PIXI.Container(); hoverLabel.alpha = 0; hoverLabel.addChild(bg); hoverLabel.addChild(t); labelContainer.addChild(hoverLabel);
    // Fade in
    const fade = () => { hoverLabel.alpha += 0.12; if (hoverLabel && hoverLabel.alpha < 1) requestAnimationFrame(fade); }; fade();
  }
  function hideHoverLabel(){ if (hoverLabel && hoverLabel.parent) { hoverLabel.parent.removeChild(hoverLabel); } hoverLabel = null; currentHoverId = null; }

  // Speech bubble (for hero chats)
  function showSpeechBubble(wx, wy, text){
    const style = new PIXI.TextStyle({ fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial', fontSize: 12, fill: 0xffffff, stroke: 0x131518, strokeThickness: 2, wordWrap: true, wordWrapWidth: 220 });
    const t = new PIXI.Text(text, style); t.anchor.set(0.5, 1.2); t.x = wx; t.y = wy;
    const w = Math.ceil(t.width) + 16, h = Math.ceil(t.height) + 12; const arrow = 8;
    const bg = new PIXI.Graphics();
    bg.beginFill(0x17191d, 0.96); bg.lineStyle(1, 0x2a2d32, 0.9);
    bg.drawRoundedRect(-w/2, -h - arrow, w, h, 8);
    bg.moveTo(0, -arrow); bg.lineTo(-arrow, 0); bg.lineTo(arrow, 0); bg.closePath(); bg.endFill();
    bg.x = t.x; bg.y = t.y - t.height/2 - 2; try { bg.filters = [new PIXI.filters.DropShadowFilter({ alpha:0.4, blur:2, distance:2, color:0x000000 })]; } catch(_){ }
    const wrap = new PIXI.Container(); wrap.addChild(bg); wrap.addChild(t); labelContainer.addChild(wrap); wrap.alpha = 0;
    // fade then auto-remove
    const start = performance.now();
    function anim(ts){ const k = Math.min(1, (ts-start)/200); wrap.alpha = k; if (k<1) requestAnimationFrame(anim); else setTimeout(()=>{ labelContainer.removeChild(wrap); }, 2800); }
    requestAnimationFrame(anim);
  }

  function appendFeed(entry){
    if (!feedEl) return;
    const div = document.createElement('div');
    div.className = 'item';
    div.dataset.type = entry.type || 'chat'; // 'chat' or 'decision'
    const who = document.createElement('div'); who.className = 'who'; who.textContent = entry.who;
    const content = document.createElement('div'); content.className = entry.type === 'decision' ? 'decision' : 'chat'; content.textContent = entry.text;
    div.appendChild(who); div.appendChild(content); 
    
    // Apply filter
    const shouldShow = feedFilterMode === 'all' || 
                      (feedFilterMode === 'chats' && entry.type === 'chat') ||
                      (feedFilterMode === 'decisions' && entry.type === 'decision');
    div.style.display = shouldShow ? 'block' : 'none';
    
    feedEl.prepend(div);
    // Trim
    while (feedEl.children.length > 60) feedEl.removeChild(feedEl.lastChild);
  }

  function updateFeedFilter(){
    if (!feedEl) return;
    for (const item of feedEl.children){
      const type = item.dataset.type || 'chat';
      const shouldShow = feedFilterMode === 'all' || 
                        (feedFilterMode === 'chats' && type === 'chat') ||
                        (feedFilterMode === 'decisions' && type === 'decision');
      item.style.display = shouldShow ? 'block' : 'none';
    }
  }

  // Store agent thought history for the thoughts panel
  const agentThoughtHistory = new Map(); // agentId -> [{time, thought, intent}, ...]

  function addAgentThought(agentId, thought, intent){
    if (!agentThoughtHistory.has(agentId)) agentThoughtHistory.set(agentId, []);
    const history = agentThoughtHistory.get(agentId);
    history.push({ time: Date.now(), thought, intent });
    if (history.length > 10) history.shift(); // Keep last 10
  }

  function updateThoughtsPanel(){
    if (!thoughtsContent || !thoughtsSelect) return;
    const selectedId = thoughtsSelect.value;
    if (!selectedId){
      thoughtsContent.innerHTML = '<div style="opacity:0.6; font-style:italic;">Select an agent to view their thoughts</div>';
      return;
    }
    const agent = idToAgent.get(selectedId);
    if (!agent){
      thoughtsContent.innerHTML = '<div style="opacity:0.6; color:#f88;">Agent not found</div>';
      return;
    }
    
    const history = agentThoughtHistory.get(selectedId) || [];
    if (history.length === 0){
      thoughtsContent.innerHTML = '<div style="opacity:0.6; font-style:italic;">No thoughts yet... waiting for LLM decisions</div>';
      return;
    }
    
    // Show recent thoughts in reverse chronological order
    const entries = history.slice(-5).reverse().map(entry => {
      const timeStr = new Date(entry.time).toLocaleTimeString();
      return `<div style="margin:4px 0; padding:6px 8px; background:#17191d; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
        <div style="font-size:10px; opacity:0.6; margin-bottom:3px;">${timeStr}</div>
        <div style="font-style:italic;">💭 "${entry.thought}"</div>
        ${entry.intent ? `<div style="margin-top:3px; opacity:0.8;">🎯 ${entry.intent}</div>` : ''}
      </div>`;
    }).join('');
    
    thoughtsContent.innerHTML = entries;
  }

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
      try { const resp = await fetch(poisUrl()); if (resp.ok) { pois = await resp.json(); } else { const r2 = await fetch(`${BASELINE_DIR}/pois.json`); if (r2.ok) pois = await r2.json(); } } catch (e) { console.warn('POIs load failed', e); }
      try { const respL = await fetch(labelsUrl()); if (respL.ok) { const raw = await respL.json(); labels = raw.map((L, i) => ({ id:i, ...L })); buildLabelIndex(); } else { const r2 = await fetch(`${BASELINE_DIR}/labels.json`); if (r2.ok) { const raw = await r2.json(); labels = raw.map((L, i) => ({ id:i, ...L })); buildLabelIndex(); } } } catch (e) { console.warn('labels load failed', e); }
      try { const respV = await fetch(venuesUrl()); if (respV.ok) { venues = await respV.json(); } else { const r2 = await fetch(`${BASELINE_DIR}/venues.json`); if (r2.ok) venues = await r2.json(); } } catch (e) { console.warn('venues load failed', e); }
      // Load navgraph for physics
      try {
        const resp = await fetch('../out/society145_1km/navgraph.npz');
        if (resp.ok){
          // npz is zipped; we do not parse zip here. Instead, also allow raw arrays exported by step3
          // Fallback to separate .npy-equivalent JSON if present (not required for initial demo)
          console.warn('navgraph.npz fetch ok but parsing not implemented; using walkable/cost from labels/pois context if available');
        }
      } catch(e){ console.warn('navgraph load failed', e); }

      // Minimal arrays: request walkable/cost via separate endpoints if provided; else synthesize walkable from semantic colors (roads/sidewalks/plaza)
      // For now, fetch direct dumps if available
      try {
        const w = await fetch('../out/society145_1km/walkable.npy');
        const c = await fetch('../out/society145_1km/cost.npy');
        if (w.ok && c.ok){
          const wb = new Uint8Array(await w.arrayBuffer());
          const cb = new Uint8Array(await c.arrayBuffer());
          walkableGrid = wb; costGrid = cb;
        }
      } catch(e){ console.warn('grid fetch failed', e); }
      if (!walkableGrid || !costGrid){
        // Graceful fallback: create permissive small-cost grid based on image size
        const N = gridW*gridH; walkableGrid = new Uint8Array(N); costGrid = new Uint8Array(N);
        walkableGrid.fill(1); costGrid.fill(12);
      }

      initWorker(gridH, gridW);
      try {
        await loadPeopleSprites();
      } catch(e) {
        console.warn('Sprite loading failed, using fallback graphics:', e);
        peopleSprites = null;
      }
      // Helper: build goal POIs list with snapped walkable locs so we can preserve category/name
      const goalPOIs = [];
      for (const p of pois){
        const loc = p.snapped || p;
        if (loc && typeof loc.ix==='number' && typeof loc.iy==='number'){
          const [iy, ix] = snapToWalkable(loc.ix, loc.iy, 20);
          goalPOIs.push({ poi: p, loc: { iy, ix } });
        }
      }
      // Spawn agents with configurable percentage of full-LLM agents
      const center = lonlatToGrid(MAIN_POI_LON, MAIN_POI_LAT);
      const baseStart = sampleWalkableNear(Math.round(center.x), Math.round(center.y), 40);
      const totalAgents = 50; // Reduced for performance
      const fullAgentPercentage = 0.3; // 30% get full LLM treatment
      const fullAgentCount = Math.floor(totalAgents * fullAgentPercentage);
      console.log('Spawning hero agents, workerReady:', workerReady, 'goalPOIs:', goalPOIs.length);
      
      // Wait for worker to be ready
      while (!workerReady) {
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      
      const regList = [];
      // Force some convergence: pick 3-4 popular destinations for clustering
      const popularDests = goalPOIs.filter(gp => ['cafe','restaurant','grocery','transit'].includes(gp.poi.type)).slice(0, 4);
      
      for (let i=0;i<totalAgents;i++){
        const isFullAgent = i < fullAgentCount; // First N agents get full LLM treatment
        const jitter = sampleWalkableNear(baseStart.ix + Math.round((Math.random()-0.5)*60), baseStart.iy + Math.round((Math.random()-0.5)*60), 30);
        const a = createAgent(jitter.ix, jitter.iy, 0xffffff, isFullAgent);
        a.speed = 0.9 + Math.random()*0.6;
        agents.push(a);
        
        // Only register full agents with the brain server (to reduce load)
        if (isFullAgent) regList.push({ id: a.id, role: a.role });
        
        // 70% chance to pick a popular destination (force convergence), 30% random
        const gp = (Math.random() < 0.7 && popularDests.length) ? 
          popularDests[Math.floor(Math.random() * popularDests.length)] :
          goalPOIs[(Math.random()*goalPOIs.length)|0];
        const target = gp ? gp.loc : { iy: jitter.iy, ix: jitter.ix };
        const start = [jitter.iy, jitter.ix];
        const res = await requestPath(start, [target.iy, target.ix]);
        if (res && res.ok) {
          a.currentGoal = gp ? { poi: gp.poi, loc: gp.loc } : null;
          if (gp && gp.poi && gp.poi.type){ a.lastIntent = gp.poi.type; if (a._chip && a._chip.txt) a._chip.txt.text = a.lastIntent; }
          setAgentPath(a, res.path);
        }
      }
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
      wireSpeedButtons();
      const btnIntents = qi('btnIntents'); if (btnIntents) btnIntents.onclick = ()=>{ showIntents = !showIntents; if (!showIntents){ intentLayer.children.forEach(c=>c.visible=false); } else if (selectedAgent && selectedAgent._chip) { selectedAgent._chip.wrap.visible = true; } };

      // Initialize DOM elements BEFORE orchestrator setup
      elTrips = document.getElementById('mTrips');
      elAvgTime = document.getElementById('mAvgTime');
      elAvgDist = document.getElementById('mAvgDist');
      elByCat = document.getElementById('mByCat');
      feedEl = document.getElementById('societyFeed');
      thoughtsSelect = document.getElementById('thoughtsAgentSelect');
      thoughtsContent = document.getElementById('thoughtsContent');

      // Start brain run (fire-and-forget). Use the actual scenario id so analytics can attribute correctly.
      const hypId = (currentScenario === 'baseline') ? 'baseline' : currentScenario;
      try { runId = await brainStartRun(hypId, 12345, speedMultipliers[speedIdx]); } catch(_) { runId = null; }
      if (runId && window.AgentOrchestrator){
        orchestrator = new window.AgentOrchestrator({
          brainUrl: BRAIN_URL,
          runId,
          getSnapshot: (id)=>{ const a = idToAgent.get(id); if (!a) return null; return { id:a.id, role:a.role, pos:[a.sprite.x, a.sprite.y], needs:a.needs, time_of_day:null }; },
          applyDecision: (d)=>{
            const a = idToAgent.get(d.id); if (!a) return;
            console.log(`APPLY DECISION for ${d.id}: thought="${d.thought}", intent="${d.next_intent?.category}"`);
            a.lastThought = d.thought || a.lastThought;
            a.lastIntent = (d.next_intent && d.next_intent.category) || a.lastIntent;
            if (a._chip && a._chip.txt && a.lastIntent) a._chip.txt.text = a.lastIntent;
            
            // MOVEMENT: Find nearest POI of the decided category and move there
            if (a.lastIntent && pois && pois.length > 0) {
              const targetPOIs = pois.filter(p => p.type === a.lastIntent);
              if (targetPOIs.length > 0) {
                // Find closest POI
                let closest = targetPOIs[0];
                let minDist = Math.hypot(a.sprite.x - closest.ix, a.sprite.y - closest.iy);
                for (const poi of targetPOIs) {
                  const dist = Math.hypot(a.sprite.x - poi.ix, a.sprite.y - poi.iy);
                  if (dist < minDist) {
                    closest = poi;
                    minDist = dist;
                  }
                }
                // Start pathfinding to closest POI
                console.log(`${d.id} moving to ${closest.name || closest.type} at (${closest.ix}, ${closest.iy})`);
                requestPath(
                  { x: Math.round(a.sprite.x), y: Math.round(a.sprite.y) },
                  { x: closest.ix, y: closest.iy },
                  (path) => {
                    if (path && path.length > 1) {
                      a.path = path.slice(1); // Remove first point (current position)
                      a.pathIndex = 0;
                      console.log(`${d.id} got path with ${a.path.length} steps`);
                    }
                  }
                );
              }
            }
            if (selectedAgent === a) updateSelectionHUD();
            // Store thought in history
            if (d.thought) addAgentThought(a.id, d.thought, a.lastIntent);
            // Log decision to feed
            if (d.thought) appendFeed({ who: a.id, text: d.thought, type: 'decision' });
            // Update thoughts panel if this agent is selected
            if (thoughtsSelect && thoughtsSelect.value === a.id) updateThoughtsPanel();
            // choose nearest POI by category and replan
            const cat = d.next_intent && d.next_intent.category; if (!cat) return;
            let best = null; let bestDist = 1e9;
            for (const p of pois){ if (p.type !== cat) continue; const loc = p.snapped||p; if (!loc) continue; const dx = (loc.ix+0.5) - a.sprite.x; const dy = (loc.iy+0.5) - a.sprite.y; const d2 = dx*dx+dy*dy; if (d2 < bestDist){ bestDist = d2; best = loc; } }
            if (best){ const cur = [Math.round(a.sprite.y-0.5), Math.round(a.sprite.x-0.5)]; const goal = [best.iy, best.ix]; requestPath(cur, goal).then(res=>{ if (res && res.ok){ setAgentPath(a, res.path); a.currentGoal = { poi:{ type: cat }, loc:{ iy: best.iy, ix: best.ix } }; }}); }
          },
          onChats: (pairLines)=>{ for (const p of pairLines){ const a = idToAgent.get(p.aId); const b = idToAgent.get(p.bId); if (a) { showSpeechBubble(a.sprite.x, a.sprite.y, p.a_line); appendFeed({ who: a.id, text: p.a_line, type: 'chat' }); } if (b) { showSpeechBubble(b.sprite.x, b.sprite.y, p.b_line); appendFeed({ who: b.id, text: p.b_line, type: 'chat' }); } }
          },
          onError: (e)=> console.warn('orchestrator error', e)
        });
        // Register all agents with brain
        await fetch(`${BRAIN_URL}/register_agents`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ runId, agents: regList }) });

        // PRIME: immediately request one decision for all full agents so UI has thoughts/feed right away
        try {
          const fulls = agents.filter(x => x.isFullAgent);
          const snaps = fulls.map(a => ({ id:a.id, role:a.role, pos:[a.sprite.x, a.sprite.y], needs:a.needs, time_of_day:null }));
          const prime = await brainDecide(snaps, {});
          if (prime && Array.isArray(prime.decisions)){
            prime.decisions.forEach(d => {
              const a = idToAgent.get(d.id); if (!a) return;
              a.lastThought = d.thought || a.lastThought;
              a.lastIntent = (d.next_intent && d.next_intent.category) || a.lastIntent;
              if (a._chip && a._chip.txt && a.lastIntent) a._chip.txt.text = a.lastIntent;
              if (d.thought) { addAgentThought(a.id, d.thought, a.lastIntent); appendFeed({ who: a.id, text: d.thought, type: 'decision' }); }
            });
            // Refresh panel if needed
            if (thoughtsSelect && thoughtsSelect.value) updateThoughtsPanel();
          }
        } catch(e){ console.warn('prime decide failed', e); }

        // Initial schedule for full agents only (to reduce server load)
        for (const a of agents.filter(x => x.isFullAgent)){ orchestrator.schedule(a.id, 'event'); }
      }

      // Ticker for agents
      let last = performance.now();
      const tick = (now)=>{
        const dt = Math.min(0.05, (now - last)/1000); last = now;
        stepAgents(dt);
        if (orchestrator) orchestrator.tick();
        // Flush metrics periodically
        if (performance.now() - lastMetricsFlush > METRICS_FLUSH_MS){ lastMetricsFlush = performance.now(); brainSendMetrics(); }
        // Replan idle agents based on needs
        if (agents && Array.isArray(agents)) {
          for (const a of agents){
            if (a.idle > 1.2 && workerReady){
              const cur = [Math.round(a.sprite.y-0.5), Math.round(a.sprite.x-0.5)];
              let goal = null;
              
              if (a.isFullAgent) {
                // Full agents use needs-driven goals
                const bestPOI = findBestPOI(a);
                if (bestPOI) {
                  goal = [bestPOI.loc.iy, bestPOI.loc.ix];
                  a.currentGoal = bestPOI;
                }
              }
              
              if (!goal) {
                // Fallback to random goal from POIs so HUD/intent have category
                const gp = goalPOIs[(Math.random()*goalPOIs.length)|0];
                if (gp) { goal = [gp.loc.iy, gp.loc.ix]; a.currentGoal = { poi: gp.poi, loc: gp.loc }; }
                else { goal = cur; }
              }
              
              requestPath(cur, goal).then(res=>{ if (res && res.ok) setAgentPath(a, res.path); });
              a.idle = 0;
            }
          }
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
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
      
      // Populate agent dropdown with ALL agents (since they all have brains now)
      if (thoughtsSelect){
        thoughtsSelect.innerHTML = '<option value="">Select agent...</option>';
        for (const a of agents.filter(x => x.isFullAgent)){
          const opt = document.createElement('option');
          opt.value = a.id;
          opt.textContent = `${a.id} (${a.role})`;
          thoughtsSelect.appendChild(opt);
        }
        thoughtsSelect.onchange = updateThoughtsPanel;
      }
      
      // Wire feed filters
      const btnFilterAll = document.getElementById('feedFilterAll');
      const btnFilterChats = document.getElementById('feedFilterChats');
      const btnFilterDecisions = document.getElementById('feedFilterDecisions');
      if (btnFilterAll) btnFilterAll.onclick = () => { feedFilterMode = 'all'; updateFeedFilter(); setActiveFilter(btnFilterAll); };
      if (btnFilterChats) btnFilterChats.onclick = () => { feedFilterMode = 'chats'; updateFeedFilter(); setActiveFilter(btnFilterChats); };
      if (btnFilterDecisions) btnFilterDecisions.onclick = () => { feedFilterMode = 'decisions'; updateFeedFilter(); setActiveFilter(btnFilterDecisions); };
      
      function setActiveFilter(activeBtn){
        [btnFilterAll, btnFilterChats, btnFilterDecisions].forEach(btn => {
          if (btn) btn.style.background = btn === activeBtn ? '#2563eb' : '#1a1c1f';
        });
      }
      setActiveFilter(btnFilterAll); // Default to "All"
      
      // Initialize metrics display
      updateMetricsUI();
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

  // Scenario selector wiring (UI controls exist in index.html)
  window.addEventListener('DOMContentLoaded', ()=>{
    console.log('🔧 Setting up scenario controls...');
    
    const sel = document.getElementById('scenarioSelect');
    const btn = document.getElementById('btnLoadScenario');
    const btnToggle = document.getElementById('btnToggleBaseline');
    const status = document.getElementById('scenarioStatus');
    
    console.log('Scenario elements found:', { 
      select: !!sel, 
      button: !!btn, 
      status: !!status 
    });
    
    if (sel && btn){
      console.log('✅ Wiring scenario controls');
      
      // Add immediate visual feedback
      btn.onclick = async ()=>{
        const chosen = sel.value || 'baseline';
        console.log(`🔄 Loading scenario: ${chosen}`);
        
        if (status) status.textContent = 'Loading...';
        btn.textContent = '⏳';
        btn.disabled = true;
        
        const oldScenario = currentScenario;
        currentScenario = chosen;
        
        console.log(`📂 Checking assets at: ${poisUrl()}`);
        
        // Try HEAD to confirm; if not present, stay on baseline
        try {
          const r = await fetch(poisUrl(), { method:'HEAD' });
          if (!r.ok) {
            console.warn(`❌ Scenario assets not found for ${chosen}, falling back to baseline`);
            currentScenario = 'baseline';
            if (status) status.textContent = 'Fallback to baseline';
          } else {
            console.log(`✅ Scenario assets found for ${chosen}`);
            if (status) status.textContent = 'Assets found';
          }
        } catch(e) { 
          console.warn(`❌ Asset check failed for ${chosen}:`, e);
          currentScenario = 'baseline';
          if (status) status.textContent = 'Error - using baseline';
        }
        
        const oldPoiCount = pois.length;
        
        // Reload POIs/labels/venues and re-render
        try { 
          const rp = await fetch(poisUrl()); 
          if (rp.ok) { 
            pois = await rp.json(); 
            console.log(`📍 Loaded ${pois.length} POIs (was ${oldPoiCount})`);
            if (status) status.textContent = `${pois.length} POIs loaded`;
          } 
        } catch(e){ console.warn('POI reload failed:', e); }
        
        try { 
          const rl = await fetch(labelsUrl()); 
          if (rl.ok) { 
            const raw = await rl.json(); 
            labels = raw.map((L,i)=>({id:i, ...L})); 
            buildLabelIndex(); 
            console.log(`🏷️  Loaded ${labels.length} labels`);
          } 
        } catch(e){ console.warn('Labels reload failed:', e); }
        
        try { 
          const rv = await fetch(venuesUrl()); 
          if (rv.ok) { 
            venues = await rv.json(); 
            console.log(`🏢 Loaded ${venues.length} venues`);
          } 
        } catch(e){ console.warn('Venues reload failed:', e); }
        
        // Force re-render everything
        console.log(`🎨 Re-rendering POIs and map...`);
        renderPOIs(); 
        updatePOIMarkerStyles(); 
        updateMinimap();

        // Mark likely added POIs for this scenario to enable consistent highlighting
        if (currentScenario !== 'baseline'){
          const addedNames = currentScenario === 'h001' ? ['Society 145 Convenience','Front RX','Lot Cafe'] : (currentScenario==='h003' ? ['Market','Plaza','Food'] : []);
          for (const p of pois){ if (p.name && addedNames.some(n => p.name.includes(n.split(' ')[0]))){ p._isAdded = true; } }
        }

        // Build scenario changes panel
        try {
          const panelBody = document.getElementById('scenarioPanelBody');
          const summary = document.getElementById('scenarioSummary');
          if (panelBody && summary){
            panelBody.innerHTML = '';
            const added = (pois || []).filter(p => p && p.name && ['Society 145 Convenience','Front RX','Lot Cafe','Market Bites 1','Market Bites 2','Plaza Cafe','Food Hall Vendor A','Food Hall Vendor B','Food Hall Vendor C'].includes(p.name));
            summary.textContent = currentScenario === 'baseline' ? 'Baseline environment' : `Active: ${currentScenario} • Added POIs: ${added.length}`;
            if (added.length){
              const ul = document.createElement('ul'); ul.style.margin='6px 0 0 16px'; ul.style.padding='0';
              for (const p of added){ const li = document.createElement('li'); li.textContent = `${p.name} (${p.type})`; ul.appendChild(li); }
              panelBody.appendChild(ul);
            } else {
              panelBody.textContent = 'No detected new POIs (this scenario may add non-labeled changes).';
            }
          }
          const btnZoom = document.getElementById('btnZoomScenario');
          if (btnZoom){
            btnZoom.onclick = ()=>{
              // Zoom to the centroid of added POIs, or do nothing if none
              const added = (pois || []).filter(p => p && p.name && ['Society 145 Convenience','Front RX','Lot Cafe','Market Bites 1','Market Bites 2','Plaza Cafe','Food Hall Vendor A','Food Hall Vendor B','Food Hall Vendor C'].includes(p.name));
              if (!added.length) return;
              let sx=0, sy=0, k=0; for (const p of added){ const loc=p.snapped||p; if (loc){ sx+=loc.ix; sy+=loc.iy; k++; } }
              if (k>0){ const cx = (sx/k)|0, cy = (sy/k)|0; centerOnGrid(cx, cy); setZoomToRadiusMeters(60); updateMinimap(); updateScaleBar(); }
            };
          }
        } catch(e){ console.warn('Scenario side panel update failed', e); }
        
        console.log(`✅ Scenario switch complete: ${oldScenario} → ${currentScenario}`);
        
        // Show user feedback
        btn.textContent = '🔄 LOAD';
        btn.disabled = false;
        if (status) status.textContent = `Active: ${currentScenario}`;
        
        // Flash the button to show it worked
        btn.style.background = '#22c55e';
        setTimeout(() => { btn.style.background = '#3b82f6'; }, 1000);
      };

      // Baseline POI visibility toggle
      if (btnToggle){
        btnToggle.onclick = ()=>{
          showBaselinePOIs = !showBaselinePOIs;
          btnToggle.textContent = showBaselinePOIs ? '👁️ Show All' : '🎯 Changes Only';
          btnToggle.style.background = showBaselinePOIs ? '#6b7280' : '#f59e0b';
          renderPOIs(); 
          updatePOIMarkerStyles();
        };
      }
      
      // Add debugging button click
      btn.addEventListener('click', () => {
        console.log('🖱️ Load button clicked!');
      });
      
    } else {
      console.error('❌ Scenario selector elements not found!', {
        select: sel,
        button: btn
      });
    }
  });

  main().catch(err => console.error(err));
})();
