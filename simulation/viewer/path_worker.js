// Simple A* pathfinding worker over uint8 cost and walkable grids
// Messages:
// { type: 'init', H, W, walkable: Uint8Array, cost: Uint8Array }
// { type: 'path', id, start: [iy,ix], goal: [iy,ix] }
// Replies:
// { type: 'ready' }
// { type: 'path', id, ok: true, path: [[iy,ix], ...] } or { ok:false }

let H = 0, W = 0;
let walkable = null; // Uint8Array
let cost = null;     // Uint8Array

function idx(y, x){ return y*W + x; }

// Min-heap for A*
class MinHeap {
  constructor(){ this.a = []; }
  push(v){ this.a.push(v); this._siftUp(this.a.length-1); }
  pop(){ if (this.a.length === 0) return null; const r = this.a[0]; const x = this.a.pop(); if (this.a.length){ this.a[0] = x; this._siftDown(0); } return r; }
  _siftUp(i){ const a = this.a; while(i>0){ const p=(i-1)>>1; if (a[p][0] <= a[i][0]) break; [a[p],a[i]] = [a[i],a[p]]; i=p; } }
  _siftDown(i){ const a = this.a; const n=a.length; while(true){ let l=i*2+1, r=l+1, m=i; if (l<n && a[l][0]<a[m][0]) m=l; if (r<n && a[r][0]<a[m][0]) m=r; if (m===i) break; [a[m],a[i]] = [a[i],a[m]]; i=m; }
  }
}

const NEI8 = [
  [-1,-1],[-1,0],[-1,1],
  [0,-1],         [0,1],
  [1,-1],[1,0],[1,1]
];
const DIAG = Math.SQRT2;

function astar(start, goal){
  const [sy,sx] = start, [gy,gx] = goal;
  if (!(0<=sx&&sx<W&&0<=sy&&sy<H&&0<=gx&&gx<W&&0<=gy&&gy<H)) return null;
  if (walkable[idx(sy,sx)]===0 || walkable[idx(gy,gx)]===0) return null;
  const g = new Float32Array(H*W); g.fill(Infinity);
  const py = new Int32Array(H*W); py.fill(-1);
  const px = new Int32Array(H*W); px.fill(-1);
  const heap = new MinHeap();
  const startI = idx(sy,sx);
  g[startI] = 0;
  heap.push([0, sy, sx]);
  function h(y,x){ const dy=Math.abs(y-gy), dx=Math.abs(x-gx); return Math.max(dy,dx) + (DIAG-1)*Math.min(dy,dx); }
  while(true){
    const node = heap.pop(); if (!node) break;
    const [_, y, x] = node;
    if (y===gy && x===gx){
      const path = [];
      let cy=y, cx=x;
      while(!(cy===sy && cx===sx)){
        path.push([cy,cx]);
        const i = idx(cy,cx);
        const pyv = py[i], pxv = px[i];
        if (pyv<0 || pxv<0) break;
        cy=pyv; cx=pxv;
      }
      path.push([sy,sx]);
      path.reverse();
      // Ensure all path elements are valid arrays with numbers
      const cleanPath = path.filter(p => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && typeof p[1] === 'number');
      return cleanPath.length > 0 ? cleanPath : null;
    }
    for (let k=0;k<8;k++){
      const ny = y + NEI8[k][0];
      const nx = x + NEI8[k][1];
      if (!(0<=nx&&nx<W&&0<=ny&&ny<H)) continue;
      const wi = idx(ny,nx);
      if (walkable[wi]===0) continue;
      const step = (k%2===0||k===3||k===4) ? 1.0 : DIAG; // diag for diagonals
      const ng = g[idx(y,x)] + step * Math.max(1, cost[wi]);
      if (ng < g[wi]){
        g[wi] = ng; py[wi]=y; px[wi]=x;
        const f = ng + h(ny,nx);
        heap.push([f, ny, nx]);
      }
    }
  }
  return null;
}

self.onmessage = (ev) => {
  const msg = ev.data;
  if (msg.type === 'init'){
    H = msg.H; W = msg.W; walkable = msg.walkable; cost = msg.cost; self.postMessage({ type:'ready' });
    return;
  }
  if (msg.type === 'path'){
    const path = astar(msg.start, msg.goal);
    if (path) self.postMessage({ type:'path', id:msg.id, ok:true, path });
    else self.postMessage({ type:'path', id:msg.id, ok:false });
    return;
  }
};


