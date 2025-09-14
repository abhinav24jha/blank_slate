(function(){
  async function postJson(url, body){
    try{ const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) }); if (!r.ok) throw new Error('HTTP '+r.status); return await r.json(); } catch(e){ console.warn('postJson fail', url, e); return null; }
  }

  class Orchestrator{
    constructor(opts){
      this.brainUrl = opts.brainUrl; this.runId = opts.runId;
      this.getSnapshot = opts.getSnapshot; this.applyDecision = opts.applyDecision; this.onChats = opts.onChats;
      this.onError = opts.onError || (()=>{});
      this.cooldowns = new Map();
      this.batchSize = 32; this.maxQps = 4; this._lastSend = 0; this._inflight = 0;
    }
    async registerAgents(list){
      return await postJson(`${this.brainUrl}/register_agents`, { runId:this.runId, agents:list });
    }
    schedule(agentId, reason){
      const now = performance.now();
      const jitterMs = (reason === 'event') ? 0 : (3000 + Math.random()*4000); // 3-7s for regular, immediate for events
      const when = now + jitterMs;
      this.cooldowns.set(agentId, when);
      console.log(`SCHEDULED ${agentId} for ${reason} in ${jitterMs.toFixed(0)}ms`);
    }
    async tick(){
      const now = performance.now();
      const ready = [];
      for (const [id, t] of this.cooldowns){ if (t <= now){ ready.push(id); this.cooldowns.delete(id); } }
      while (ready.length){
        const batchIds = ready.splice(0, this.batchSize);
        const snaps = batchIds.map(id => this.getSnapshot(id)).filter(Boolean);
        if (!snaps.length) continue;
        const since = now - this._lastSend; const minInterval = 1000/this.maxQps;
        if (since < minInterval) await new Promise(r=>setTimeout(r, minInterval - since));
        this._inflight++;
        postJson(`${this.brainUrl}/decide`, { runId:this.runId, agents:snaps, context:{} })
          .then(js=>{ 
            console.log(`ORCHESTRATOR BATCH: ${snaps.length} agents -> ${(js && js.decisions || []).length} decisions`);
            if (js && js.decisions) {
              js.decisions.forEach(d => {
                console.log(`ORCHESTRATOR DECISION: ${d.id} -> "${d.thought}" (${d.next_intent?.category})`);
                this.applyDecision && this.applyDecision(d);
                // Reschedule this agent for next decision cycle
                this.schedule(d.id, 'regular');
              });
            }
          })
          .catch(e=>this.onError(e)).finally(()=>{ this._inflight--; this._lastSend = performance.now(); });
      }
    }
    async chat(pairs){
      const js = await postJson(`${this.brainUrl}/chat`, { runId:this.runId, pairs, context:{} });
      if (js && js.pairs && this.onChats) this.onChats(js.pairs);
    }
  }

  // UMD-lite export
  if (typeof window !== 'undefined') window.AgentOrchestrator = Orchestrator;
})();


