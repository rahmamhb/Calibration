#!/usr/bin/env python3
"""
app.py  —  Flask UI, runs on the CRAN server
Place at: ~/cooja-sim/app.py
Run:      python3 app.py
Access:   ssh -L 6001:localhost:6001 <user>@<server-ip>
          then open http://localhost:6001 in your local browser
"""
import json, queue, threading, os, sys, csv, subprocess, time
from pathlib import Path
from flask import Flask, render_template_string, request, Response, jsonify

app = Flask(__name__)
pipeline_running = False
output_queue     = queue.Queue()

BASE_DIR = Path(__file__).parent

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Adaptive Calibration Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0f14;--bg2:#13161e;--bg3:#1a1e28;--bd:#252a38;--bd2:#2f364a;--tx:#c8cdd8;--tx2:#6b7285;--tx3:#3e4559;--teal:#1de9b6;--teal2:#0a7a5e;--amber:#ffb300;--amber2:#7a5200;--purple:#9b8afb;--purple2:#3d3270;--red:#ff5252;--green:#69db7c;--mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:var(--sans);font-size:13px;min-height:100vh}
header{border-bottom:1px solid var(--bd);padding:14px 24px;display:flex;align-items:center;gap:12px}
header h1{font-size:13px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:var(--teal);font-family:var(--mono)}
.pill{font-family:var(--mono);font-size:10px;padding:3px 10px;border-radius:20px;border:1px solid}
.idle{border-color:var(--bd2);color:var(--tx2)}
.running{border-color:var(--teal2);color:var(--teal);animation:pulse 2s infinite}
.done{border-color:#2a5c3a;color:var(--green)}
.stopped{border-color:#5c2a2a;color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.layout{display:grid;grid-template-columns:270px 1fr;height:calc(100vh - 49px)}
.sidebar{border-right:1px solid var(--bd);padding:20px;display:flex;flex-direction:column;gap:16px;overflow-y:auto}
.sidebar h2{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--tx3);font-family:var(--mono);margin-bottom:4px}
.field{display:flex;flex-direction:column;gap:5px}
.field label{font-size:11px;color:var(--tx2);font-family:var(--mono)}
.field input[type=text],.field input[type=number]{background:var(--bg3);border:1px solid var(--bd2);border-radius:4px;color:var(--tx);font-family:var(--mono);font-size:12px;padding:6px 10px;outline:none;width:100%}
.field input:focus{border-color:var(--teal2)}
.rrow{display:flex;align-items:center;gap:8px}
.rrow input[type=range]{flex:1;accent-color:var(--teal)}
.rval{font-family:var(--mono);font-size:12px;color:var(--teal);min-width:40px;text-align:right}
.rnote{font-size:10px;color:var(--tx3);font-family:var(--mono);margin-top:2px}
.sep{border:none;border-top:1px solid var(--bd)}
.steps{display:flex;flex-direction:column;gap:8px}
.step{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--tx2)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bg3);border:1px solid var(--bd2);flex-shrink:0;transition:all .3s}
.dot.active{background:var(--teal);border-color:var(--teal);box-shadow:0 0 8px var(--teal2)}
.dot.done{background:var(--green);border-color:var(--green)}
.dot.warn{background:var(--amber);border-color:var(--amber)}
.btn{width:100%;padding:9px;font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;border-radius:4px;cursor:pointer;border:1px solid;transition:all .15s}
.btn-run{background:transparent;border-color:var(--teal2);color:var(--teal)}
.btn-run:hover{background:var(--teal2)}
.btn-stop{background:transparent;border-color:#5c2a2a;color:var(--red)}
.btn-stop:hover{background:#2a1010}
.main{display:grid;grid-template-rows:auto auto 1fr auto;overflow:hidden}
.chart-panel{border-bottom:1px solid var(--bd);padding:12px 18px 10px;background:var(--bg2)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bd)}
.mc{padding:14px 18px;border-right:1px solid var(--bd)}
.mc:last-child{border-right:none}
.mc .ml{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx3);font-family:var(--mono)}
.mc .mv{font-size:22px;font-weight:300;color:var(--tx);margin-top:4px;font-family:var(--mono)}
.mc .mv span{font-size:11px;color:var(--tx2)}
.feed{overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:4px}
.chdr{display:grid;grid-template-columns:100px 110px 1fr 160px 120px;gap:8px;padding:0 10px 8px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx3);font-family:var(--mono);border-bottom:1px solid var(--bd);margin-bottom:4px}
.wrow{display:grid;grid-template-columns:100px 110px 1fr 160px 120px;gap:8px;padding:7px 10px;border-radius:4px;border:1px solid var(--bd);background:var(--bg2);font-family:var(--mono);font-size:11px;animation:si .25s ease}
@keyframes si{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.wrow.chg{border-color:var(--amber2);background:#1a150a}
.wrow.rec{border-color:var(--purple2);background:#12101e}
.tag{font-size:10px;padding:2px 7px;border-radius:3px;display:inline-block}
.t-ok{background:#0a1a10;color:var(--green);border:1px solid #1a3a20}
.t-chg{background:#1a1200;color:var(--amber);border:1px solid var(--amber2);animation:pulse 1.5s infinite}
.t-rec{background:#100d1e;color:var(--purple);border:1px solid var(--purple2)}
.t-base{background:#0a1a18;color:#4dd0e1;border:1px solid #1a4040}
.wt{color:var(--tx2)}.wp{color:var(--purple)}.fg{color:var(--green)}.fo{color:var(--amber)}.fb{color:var(--red)}.fn{color:var(--tx3)}
.log{font-family:var(--mono);font-size:11px;color:var(--tx2);line-height:1.8;border-top:1px solid var(--bd);padding:10px 18px;max-height:120px;overflow-y:auto}
.lc{color:var(--amber)}.lg{color:var(--green)}.le{color:var(--red)}.li{color:var(--teal)}
.empty{display:flex;align-items:center;justify-content:center;height:160px;color:var(--tx3);font-family:var(--mono);font-size:12px}
</style>
</head>
<body>
<header>
  <h1>⬡ adaptive calibration monitor</h1>
  <span class="pill idle" id="pill">idle</span>
  <span style="margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--tx3)" id="prog"></span>
</header>
<div class="layout">
  <div class="sidebar">
    <div>
      <h2>Config</h2>
      <div style="display:flex;flex-direction:column;gap:10px">
        <div class="field">
          <label>Log file (relative to cooja-sim/)</label>
          <input type="text" id="cfg-log" value="results/Scenario04/synthetic_logs_v2/serial.log">
        </div>
        <div class="field">
          <label>Sender nodes</label>
          <input type="number" id="cfg-nodes" value="20" min="1" max="50" style="width:72px">
        </div>
        <div class="field"><label>Window (s)</label>
          <div class="rrow"><input type="range" min="10" max="120" value="30" step="5" id="sl-w" oninput="sv('v-w',this.value)">
          <span class="rval" id="v-w">30</span></div></div>
        <div class="field"><label>Step (s)</label>
          <div class="rrow"><input type="range" min="5" max="60" value="10" step="5" id="sl-s" oninput="sv('v-s',this.value)">
          <span class="rval" id="v-s">10</span></div></div>
        <div class="field"><label>Playback speed</label>
          <div class="rrow"><input type="range" min="1" max="120" value="10" step="1" id="sl-sp" oninput="sv('v-sp',this.value+'x')">
          <span class="rval" id="v-sp">10x</span></div>
          <div class="rnote">1x = real time &nbsp;·&nbsp; 10x default (60 min experiment ≈ 6 min) &nbsp;·&nbsp; 60x = 1 min demo</div>
        </div>
      </div>
    </div>
    <hr class="sep">
    <div>
      <h2>Pipeline state</h2>
      <div class="steps">
        <div class="step"><span class="dot" id="dot-read"></span>Reading log</div>
        <div class="step"><span class="dot" id="dot-kpi"></span>Extracting KPIs</div>
        <div class="step"><span class="dot" id="dot-det"></span>Change detection</div>
        <div class="step"><span class="dot" id="dot-nn"></span>NN inference</div>
        <div class="step"><span class="dot" id="dot-sim"></span>Cooja simulation</div>
        <div class="step"><span class="dot" id="dot-res"></span>Reading results</div>

      </div>
    </div>
    <hr class="sep">
    <button class="btn btn-run" id="btn-run" onclick="start()">▶ run pipeline</button>
    <button class="btn btn-stop" id="btn-stop" style="display:none" onclick="stop()">■ stop</button>
  </div>

  <div class="main">
    <div class="metrics">
      <div class="mc"><div class="ml">Windows</div><div class="mv" id="m-w">—</div></div>
      <div class="mc"><div class="ml">Changes detected</div><div class="mv" id="m-c">—</div></div>
      <div class="mc"><div class="ml">Avg Δ RSSI</div><div class="mv" id="m-r">—<span> dBm</span></div></div>
      <div class="mc"><div class="ml">Avg Δ loss</div><div class="mv" id="m-l">—<span> %</span></div></div>
    </div>
    <div class="chart-panel">
      <div style="font-family:var(--mono);font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">&#9652; packet loss evolution — live</div>
      <canvas id="chart" height="130" style="width:100%;display:block;border-radius:2px"></canvas>
    </div>
    <div class="feed" id="feed"><div class="empty" id="empty">configure and press run</div></div>
    <div class="log" id="log"></div>
  </div>
</div>

<script>
let es=null,hdr=false,mW=0,mC=0,rS=0,lS=0,fN=0;
let chartData={real:[],sim:[],changes:[]};

function updateChart(){
  const canvas=document.getElementById('chart');
  if(!canvas)return;
  canvas.width=canvas.offsetWidth;
  const W=canvas.width,H=canvas.height;
  const ctx=canvas.getContext('2d');
  const pad={top:14,right:16,bottom:24,left:42};
  const cW=W-pad.left-pad.right,cH=H-pad.top-pad.bottom;
  ctx.fillStyle='#13161e';ctx.fillRect(0,0,W,H);
  const allY=chartData.real.map(d=>d.y).concat(chartData.sim.map(d=>d.y));
  const maxY=allY.length?Math.max(...allY,10):100;
  const n=chartData.real.length;
  const maxX=n?chartData.real[n-1].x:10;
  const sx=x=>pad.left+(x/Math.max(maxX,1))*cW;
  const sy=y=>pad.top+cH-(y/maxY)*cH;
  // grid
  ctx.lineWidth=0.5;ctx.strokeStyle='#252a38';
  for(let i=0;i<=4;i++){
    const y=sy(maxY*i/4);
    ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(W-pad.right,y);ctx.stroke();
    ctx.fillStyle='#6b7285';ctx.font='9px IBM Plex Mono,monospace';ctx.textAlign='right';
    ctx.fillText((maxY*i/4).toFixed(0)+'%',pad.left-4,y+3);
  }
  // axes
  ctx.strokeStyle='#3e4559';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(pad.left,pad.top);ctx.lineTo(pad.left,H-pad.bottom);ctx.lineTo(W-pad.right,H-pad.bottom);ctx.stroke();
  // change markers
  ctx.strokeStyle='#ff5252';ctx.lineWidth=1;ctx.setLineDash([4,3]);
  chartData.changes.forEach(x=>{const px=sx(x);ctx.beginPath();ctx.moveTo(px,pad.top);ctx.lineTo(px,H-pad.bottom);ctx.stroke()});
  ctx.setLineDash([]);
  // real data with rolling mean ± 5σ band
  if(n>1){
    const ys=chartData.real.map(d=>d.y);
    const xs=chartData.real.map(d=>d.x);
    // Faded raw trace
    ctx.strokeStyle='rgba(29,233,182,0.25)';ctx.lineWidth=0.8;ctx.beginPath();
    chartData.real.forEach((d,i)=>{i===0?ctx.moveTo(sx(d.x),sy(d.y)):ctx.lineTo(sx(d.x),sy(d.y))});
    ctx.stroke();
    // Compute 5-point centred rolling mean ± 5σ
    const half=2,rm=[],ru=[],rl=[];
    for(let i=0;i<n;i++){
      const lo=Math.max(0,i-half),hi=Math.min(n,i+half+1);
      const seg=ys.slice(lo,hi);
      const m=seg.reduce((a,v)=>a+v,0)/seg.length;
      const s=Math.sqrt(seg.reduce((a,v)=>a+(v-m)**2,0)/seg.length);
      rm.push(m);ru.push(m+5*s);rl.push(Math.max(0,m-5*s));
    }
    // ±5σ band
    ctx.fillStyle='rgba(29,233,182,0.15)';ctx.beginPath();
    ctx.moveTo(sx(xs[0]),sy(ru[0]));
    for(let i=1;i<n;i++)ctx.lineTo(sx(xs[i]),sy(ru[i]));
    for(let i=n-1;i>=0;i--)ctx.lineTo(sx(xs[i]),sy(rl[i]));
    ctx.closePath();ctx.fill();
    // Rolling mean line
    ctx.strokeStyle='#1de9b6';ctx.lineWidth=1.8;ctx.beginPath();
    rm.forEach((m,i)=>{i===0?ctx.moveTo(sx(xs[i]),sy(m)):ctx.lineTo(sx(xs[i]),sy(m))});
    ctx.stroke();
  }
  // sim triangles
  ctx.fillStyle='#ffb300';
  chartData.sim.forEach(d=>{
    const px=sx(d.x),py=sy(d.y);
    ctx.beginPath();ctx.moveTo(px,py-6);ctx.lineTo(px+5,py+3);ctx.lineTo(px-5,py+3);ctx.closePath();ctx.fill();
  });
  // x-axis labels
  ctx.fillStyle='#6b7285';ctx.font='9px IBM Plex Mono,monospace';ctx.textAlign='center';
  if(maxX>0){ctx.fillText('W1',pad.left,H-2);ctx.fillText('W'+maxX,W-pad.right,H-2);}
}

function sv(id,v){document.getElementById(id).textContent=v}
function dot(id,s){const d=document.getElementById('dot-'+id);d.className='dot'+(s?' '+s:'')}
function clearDots(){['read','kpi','det','nn','sim','res'].forEach(d=>dot(d,''))}
function pill(c,t){const p=document.getElementById('pill');p.className='pill '+c;p.textContent=t}
function log(msg,c=''){const a=document.getElementById('log'),d=document.createElement('div');if(c)d.className=c;d.textContent='> '+msg;a.appendChild(d);a.scrollTop=a.scrollHeight}
function fidCls(v){const n=parseFloat(v);return n<3?'fg':n<7?'fo':'fb'}

function addRow(d){
  const feed=document.getElementById('feed');
  document.getElementById('empty')?.remove();
  if(!hdr){const h=document.createElement('div');h.className='chdr';
    h.innerHTML='<span>status</span><span>window</span><span>real KPIs</span><span>predicted params</span><span>Δ fidelity</span>';
    feed.appendChild(h);hdr=true}
  const row=document.createElement('div');
  row.id='r'+d.wid; row.className='wrow'+(d.chg?' chg':'');
  const tag=d.chg?'<span class="tag t-chg">change!</span>':'<span class="tag t-ok">stable</span>';
  row.innerHTML=`${tag}<span class="wt">${d.t0}–${d.t1}s</span><span>RSSI ${d.rssi} dBm · loss ${d.loss}%</span><span class="fn">—</span><span class="fn">—</span>`;
  feed.appendChild(row);feed.scrollTop=feed.scrollHeight;
}

function updateRow(wid,params,fid){
  const row=document.getElementById('r'+wid);if(!row)return;
  row.className='wrow rec';
  row.children[0].outerHTML='<span><span class="tag t-rec">recalibrated</span></span>';
  if(params)row.children[3].innerHTML=`<span class="wp">α=${params.pl} σ=${params.awgn} i=${params.infl}</span>`;
  if(fid)row.children[4].innerHTML=`<span class="${fidCls(fid.r)}">Δ${fid.r}dBm</span> · <span class="${fidCls(fid.l)}">Δ${fid.l}%</span>`;
}

function updateMetrics(){
  document.getElementById('m-w').textContent=mW||'—';
  document.getElementById('m-c').textContent=mC||'—';
  document.getElementById('m-r').innerHTML=(fN>0?(rS/fN).toFixed(1):'—')+'<span> dBm</span>';
  document.getElementById('m-l').innerHTML=(fN>0?(lS/fN).toFixed(1):'—')+'<span> %</span>';
}

function start(){
  hdr=false;mW=mC=rS=lS=fN=0;
  chartData={real:[],sim:[],changes:[]};updateChart();
  document.getElementById('feed').innerHTML='';
  document.getElementById('log').innerHTML='';
  document.getElementById('btn-run').style.display='none';
  document.getElementById('btn-stop').style.display='';
  pill('running','running');clearDots();updateMetrics();
  const cfg={
    log:    document.getElementById('cfg-log').value,
    nodes:  document.getElementById('cfg-nodes').value,
    window: document.getElementById('sl-w').value,
    step:   document.getElementById('sl-s').value,
    speed:  document.getElementById('sl-sp').value,
  };
  fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})
    .then(r=>r.json()).then(r=>{
      if(r.error){log(r.error,'le');pill('stopped','error');return}
      log('Pipeline started','li');listen();
    });
}

function stop(){
  fetch('/stop',{method:'POST'});
  if(es){es.close();es=null}
  pill('stopped','stopped');clearDots();
  document.getElementById('btn-run').style.display='';
  document.getElementById('btn-stop').style.display='none';
  log('Stopped by user','le');
}

function listen(){
  es=new EventSource('/stream');
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.type==='window'){
      mW=d.wid;
      chartData.real.push({x:d.wid,y:d.loss});updateChart();
      addRow({wid:d.wid,t0:d.t0,t1:d.t1,rssi:d.rssi,loss:d.loss,chg:false});
      dot('read','done');dot('kpi','done');dot('det','active');
      document.getElementById('prog').textContent='W'+d.wid+'  '+d.phase;
      updateMetrics();
    } else if(d.type==='change'){
      mC++;
      chartData.changes.push(d.wid);updateChart();
      const row=document.getElementById('r'+d.wid);
      if(row){row.className='wrow chg';row.children[0].innerHTML='<span class="tag t-chg">change!</span>'}
      dot('det','warn');dot('nn','active');
      log('[W'+d.wid+'] Change detected','lc');updateMetrics();
    } else if(d.type==='params'){
      dot('nn','done');dot('sim','active');
      log('[W'+d.wid+'] α='+d.pl+' σ='+d.awgn+' infl='+d.infl,'lg');
    } else if(d.type==='simstart'){
      log('[W'+d.wid+'] Cooja running...','li');
    } else if(d.type==='result'){
      rS+=parseFloat(d.dr);lS+=parseFloat(d.dl);fN++;
      if(d.sl!=null)chartData.sim.push({x:d.wid,y:parseFloat(d.sl)});updateChart();
      dot('sim','done');dot('res','done');
      updateRow(d.wid,{pl:d.pl,awgn:d.awgn,infl:d.infl},{r:d.dr,l:d.dl});
      log('[W'+d.wid+'] recalibrated — ΔRSSI='+d.dr+'dBm  Δloss='+d.dl+'%','lg');
      setTimeout(clearDots,800);updateMetrics();
    } else if(d.type==='done'){
      pill('done','done');
      document.getElementById('btn-run').style.display='';
      document.getElementById('btn-stop').style.display='none';
      document.getElementById('prog').textContent=d.total+' windows done';
      log('Finished — results → '+d.out,'lg');
      clearDots();updateMetrics();
      es.close();
    } else if(d.type==='log'){
      if(d.msg!=='heartbeat')log(d.msg);
    } else if(d.type==='error'){
      log(d.msg,'le');
    }
  };
  es.onerror=()=>{
    pill('stopped','error');log('Connection lost','le');
    document.getElementById('btn-run').style.display='';
    document.getElementById('btn-stop').style.display='none';
  };
}
</script>
</body>
</html>"""


def _plot_loss_evolution(run_dir, real_loss, sim_loss, change_windows=None):
    """
    Generate loss_evolution.png showing real vs simulation packet loss rate over time.
    real_loss      : [(wid, w_start_s, loss_rate_pct), ...]
    sim_loss       : [(wid, w_start_s, sim_loss_rate_pct), ...]
    change_windows : [wid, ...] windows where change_detected=1
    Returns Path to saved PNG, or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(13, 5))
        fig.patch.set_facecolor('#0d0f14')
        ax.set_facecolor('#13161e')
        for spine in ax.spines.values():
            spine.set_edgecolor('#252a38')
        ax.tick_params(colors='#6b7285', which='both')
        ax.xaxis.label.set_color('#6b7285')
        ax.yaxis.label.set_color('#6b7285')
        ax.title.set_color('#c8cdd8')

        # ── Suggestion 2: dashed vertical lines at detection events ──────────
        if change_windows:
            first_transient = True
            for cw in change_windows:
                lbl = 'Change detected' if first_transient else None
                ax.axvline(cw, color='#ff5722', lw=1.2, ls='--', alpha=0.7, zorder=4, label=lbl)
                first_transient = False

        if real_loss:
            xs = [x[0] for x in real_loss]
            ys = [x[2] for x in real_loss]

            # Raw trace — thin and faded, kept for reference
            ax.plot(xs, ys, color='#1de9b6', lw=0.8, alpha=0.30, zorder=2)
            ax.fill_between(xs, ys, 0, alpha=0.05, color='#1de9b6')

            # ── Suggestion 1: 5-point centred rolling mean ± 1σ band ────────
            half = 2   # half-width → window covers i-2 … i+2 (5 points)
            n = len(ys)
            roll_mean, roll_std = [], []
            for i in range(n):
                lo = max(0, i - half)
                hi = min(n, i + half + 1)
                seg = ys[lo:hi]
                m = sum(seg) / len(seg)
                s = (sum((v - m) ** 2 for v in seg) / len(seg)) ** 0.5
                roll_mean.append(m)
                roll_std.append(s)

            upper = [m + 5 * s for m, s in zip(roll_mean, roll_std)]
            lower = [max(0.0, m - 5 * s) for m, s in zip(roll_mean, roll_std)]

            ax.fill_between(xs, lower, upper, alpha=0.18, color='#1de9b6',
                            zorder=2, label='Real ±5σ band')
            ax.plot(xs, roll_mean, color='#1de9b6', lw=1.8, zorder=3,
                    label='Real network (rolling mean)')

        if sim_loss:
            cx, cy = zip(*[(x[0], x[2]) for x in sim_loss])
            ax.scatter(cx, cy, c='#ffb300', s=90, zorder=5, marker='^',
                       label='Simulation (recalibrated)', edgecolors='#7a5200', linewidths=0.8)
        if len(sim_loss) > 1:
            sx = [x[0] for x in sim_loss]
            sy = [x[2] for x in sim_loss]
            ax.plot(sx, sy, '--', color='#3e4559', lw=1, zorder=2)

        ax.set_xlabel('Window', color='#6b7285')
        ax.set_ylabel('Packet Loss Rate (%)', color='#6b7285')
        ax.set_title('Packet Loss Evolution — Real Network vs Simulation', color='#c8cdd8', pad=12)
        ax.grid(True, color='#252a38', linewidth=0.5, alpha=0.7)
        ax.legend(facecolor='#1a1e28', edgecolor='#252a38', labelcolor='#c8cdd8', fontsize=9)

        plt.tight_layout()
        plot_path = run_dir / "loss_evolution.png"
        plt.savefig(str(plot_path), dpi=150, bbox_inches='tight',
                    facecolor='#0d0f14', edgecolor='none')
        plt.close()
        return plot_path
    except Exception as e:
        print(f"[plot] loss_evolution failed: {e}")
        return None


def pipeline_thread(cfg, q):
    sys.path.insert(0, str(BASE_DIR / "tools"))
    from kpi_extractor   import extract_kpis
    from change_detector import PageHinkley
    from sender_roles    import find_node_positions, get_main_senders

    RESULTS_DIR   = BASE_DIR / "results"
    TEMPLATES_DIR = BASE_DIR / "templates"
    MODELS_DIR    = Path("/home/mihoubrahma/Calibration models")

    window_s = int(cfg["window"])
    step_s   = int(cfg["step"])
    n_nodes  = int(cfg["nodes"])
    speed    = float(cfg["speed"])
    log_path = str(BASE_DIR / cfg["log"])

    # Each experiment carries its own node_positions.json next to the log
    # (e.g. results/ScenarioNN/node_positions.json) — use that instead of a
    # fixed global file, falling back to the repo-root default if not found.
    found_positions = find_node_positions(log_path)
    POSITIONS = Path(found_positions) if found_positions else BASE_DIR / "node_positions.json"
    q.put({"type": "log", "msg": f"Using positions: {POSITIONS}"})

    ts      = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"adaptive_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_csv = run_dir / "adaptive_results.csv"

    # Filter positions to the same sender set used for real KPIs so that the
    # simulation node count matches and throughput normalization is consistent.
    _send_events_pre = []
    try:
        with open(log_path) as _lf:
            for _line in _lf:
                _p = _line.strip().split(";")
                if len(_p) == 3:
                    try:
                        _t = float(_p[0]); _nd = _p[1]; _tk = _p[2].split()
                        if len(_tk) >= 3 and _tk[0] == "s":
                            _send_events_pre.append((_t, _nd))
                    except Exception:
                        pass
    except Exception:
        pass
    _allowed, _src = get_main_senders(log_path, send_events=_send_events_pre or None)
    if _allowed and POSITIONS.exists():
        _filt_pos = run_dir / "calibration_positions.json"
        try:
            _aid = {a.replace("m3-", "") for a in _allowed}
            with open(POSITIONS) as _pf:
                _pd = json.load(_pf)
            _pd["nodes"] = {k: v for k, v in _pd["nodes"].items()
                            if v.get("role") == "receiver" or k in _aid}
            with open(_filt_pos, "w") as _pf:
                json.dump(_pd, _pf, indent=2)
            POSITIONS = _filt_pos
            q.put({"type": "log", "msg": f"Positions filtered to {len(_allowed)} main senders [{_src}]"})
        except Exception as _fe:
            q.put({"type": "log", "msg": f"Position filter failed: {_fe} — using full positions"})

    RESULT_COLS = [
        "window_id","window_start_s","window_end_s","change_detected",
        "real_mean_rssi","real_loss_rate","real_throughput","real_mean_delay",
        "real_std_delay","real_min_rssi","real_std_rssi","real_std_loss","real_min_prr",
        "pred_path_loss","pred_awgn","pred_inflection","pred_rx_sens",
        "sim_mean_rssi","sim_loss_rate","sim_throughput","sim_mean_delay",
        "sim_std_delay","sim_min_rssi","delta_rssi","delta_loss","delta_throughput","delta_delay"
    ]

    def append(row):
        exists = out_csv.exists()
        with open(out_csv,"a",newline="") as f:
            w=csv.DictWriter(f,fieldnames=RESULT_COLS,extrasaction="ignore")
            if not exists: w.writeheader()
            w.writerow(row)

    def run_local(cmd):
        r=subprocess.run(cmd,capture_output=True,text=True,cwd=str(BASE_DIR))
        return r.returncode,r.stdout.strip(),r.stderr.strip()

    detector = PageHinkley(delta=0.5, threshold=5.0, burn_in=3, cooldown=10)
    wid=0
    real_loss_series    = []   # [(wid, w_start_s, loss_rate_pct)]
    sim_loss_series     = []   # [(wid, w_start_s, sim_loss_rate_pct)]
    change_windows_series = []  # [wid, ...] where change_detected=1

    # Determine phase label for display
    PHASES=[(0,900,"STABLE"),(900,1800,"DEGRADED"),(1800,2700,"RECOVERY"),(2700,3600,"CRITICAL")]
    def phase_label(t):
        for s,e,l in PHASES:
            if s<=t<e: return l
        return "CRITICAL"

    try:
        for kpis,w_start,w_end in extract_kpis(
                log_path,window_s=window_s,step_s=step_s,
                n_nodes=n_nodes,realtime=True,speed=speed):

            if not pipeline_running: break
            wid+=1
            q.put({"type":"window","wid":wid,"t0":round(w_start),"t1":round(w_end),
                   "rssi":round(kpis["mean_rssi_dbm"],1),
                   "loss":round(kpis["loss_rate_pct"],1),
                   "phase":phase_label(w_start)})

            changed=detector.update(kpis["loss_rate_pct"])
            row={
                "window_id":wid,"window_start_s":round(w_start),"window_end_s":round(w_end),
                "change_detected":int(changed),
                "real_mean_rssi":kpis["mean_rssi_dbm"],"real_loss_rate":kpis["loss_rate_pct"],
                "real_throughput":kpis["throughput_pkt_s"],"real_mean_delay":kpis["mean_delay_s"],
                "real_std_delay":kpis["std_delay_s"],"real_min_rssi":kpis["min_rssi_dbm"],
                "real_std_rssi":kpis["std_rssi_dbm"],"real_std_loss":kpis["std_loss_rate"],
                "real_min_prr":kpis["per_node_min_prr"]
            }
            real_loss_series.append((wid, round(w_start), kpis["loss_rate_pct"]))

            if not changed:
                append(row); continue

            change_windows_series.append(wid)
            q.put({"type":"change","wid":wid})

            if kpis["loss_rate_pct"] < 2.0:
                q.put({"type":"log","msg":f"[W{wid}] Network recovered (loss < 2%) — skipping calibration"})
                append(row); continue

            # NN inference (local subprocess)
            kpi_str=",".join([str(round(kpis[k],6)) for k in [
                "mean_rssi_dbm","std_rssi_dbm","min_rssi_dbm","loss_rate_pct",
                "throughput_pkt_s","mean_delay_s","std_delay_s","std_loss_rate","per_node_min_prr"]])
            rc,out,err=run_local([sys.executable,str(BASE_DIR/"predict_params.py"),f"--kpis={kpi_str}"])
            if rc!=0: q.put({"type":"error","msg":f"[W{wid}] NN error: {err}"}); append(row); continue

            parts=out.strip().split(",")
            if len(parts)!=4: q.put({"type":"error","msg":f"[W{wid}] bad NN output"}); append(row); continue

            params={"path_loss_exponent":float(parts[0]),"awgn_sigma":float(parts[1]),
                    "rssi_inflection_point":float(parts[2]),"rx_sensitivity":float(parts[3])}
            q.put({"type":"params","wid":wid,
                   "pl":round(params["path_loss_exponent"],3),
                   "awgn":round(params["awgn_sigma"],3),
                   "infl":round(params["rssi_inflection_point"],1)})

            sim_dir=run_dir/f"window_{wid:04d}"
            sim_dir.mkdir(exist_ok=True)

            # Run Cooja — pass predicted radio params directly via flags so they
            # reach generate_csc.py inside run_cooja_only.sh without being
            # overwritten by its defaults.
            q.put({"type":"simstart","wid":wid})
            sim_cmd=["bash",str(BASE_DIR/"run_cooja_only.sh"),
                     "-d","3",
                     "-p",str(POSITIONS),
                     "-g","40",
                     "-e",f"{params['path_loss_exponent']:.4f}",
                     "-w",f"{params['awgn_sigma']:.4f}",
                     "-i",f"{params['rssi_inflection_point']:.4f}",
                     "-x",f"{params['rx_sensitivity']:.4f}"]
            rc,_,err=run_local(sim_cmd)
            if rc!=0: q.put({"type":"error","msg":f"[W{wid}] Cooja failed: {err[:150]}"}); append(row); continue

            # Find the cooja output folder just created and move it under sim_dir
            import glob as _glob, shutil as _shutil
            cooja_runs=sorted(_glob.glob(str(BASE_DIR/"results"/"cooja_*")))
            if not cooja_runs: q.put({"type":"error","msg":f"[W{wid}] cooja output not found"}); append(row); continue
            cooja_out=Path(cooja_runs[-1])
            dest=sim_dir/"cooja_out"
            _shutil.move(str(cooja_out),str(dest))

            mpath=dest/"cooja"/"metrics.csv"
            sim_kpis={}
            if mpath.exists():
                with open(mpath) as f:
                    for r2 in csv.DictReader(f): sim_kpis=r2; break

            def safe(v,d=0.0):
                try: return float(v)
                except: return d
            dr=abs(kpis["mean_rssi_dbm"]   -safe(sim_kpis.get("mean_rssi_dbm")))
            dl=abs(kpis["loss_rate_pct"]    -safe(sim_kpis.get("loss_rate_pct")))
            dt=abs(kpis["throughput_pkt_s"] -safe(sim_kpis.get("throughput_pkt_s")))
            dd=abs(kpis["mean_delay_s"]     -safe(sim_kpis.get("mean_delay_s")))

            if sim_kpis:
                sim_loss_series.append((wid, round(w_start),
                                        safe(sim_kpis.get("loss_rate_pct"))))
            q.put({"type":"result","wid":wid,
                   "pl":round(params["path_loss_exponent"],3),
                   "awgn":round(params["awgn_sigma"],3),
                   "infl":round(params["rssi_inflection_point"],1),
                   "dr":round(dr,2),"dl":round(dl,2),
                   "sl":round(safe(sim_kpis.get("loss_rate_pct")),2) if sim_kpis else None})

            row.update({"pred_path_loss":params["path_loss_exponent"],
                        "pred_awgn":params["awgn_sigma"],
                        "pred_inflection":params["rssi_inflection_point"],
                        "pred_rx_sens":params["rx_sensitivity"],
                        "sim_mean_rssi":sim_kpis.get("mean_rssi_dbm",""),
                        "sim_loss_rate":sim_kpis.get("loss_rate_pct",""),
                        "sim_throughput":sim_kpis.get("throughput_pkt_s",""),
                        "sim_mean_delay":sim_kpis.get("mean_delay_s",""),
                        "sim_std_delay":sim_kpis.get("std_delay_s",""),
                        "sim_min_rssi":sim_kpis.get("min_rssi_dbm",""),
                        "delta_rssi":round(dr,4),"delta_loss":round(dl,4),
                        "delta_throughput":round(dt,4),"delta_delay":round(dd,6)})
            append(row)

    except Exception as e:
        q.put({"type":"error","msg":f"Pipeline error: {e}"})

    plot_url = None
    try:
        pp = _plot_loss_evolution(run_dir, real_loss_series, sim_loss_series, change_windows_series)
        if pp:
            plot_url = "/results/" + str(pp.relative_to(BASE_DIR / "results"))
    except Exception:
        pass
    q.put({"type":"done","total":wid,"out":str(out_csv),"plot_url":plot_url})


@app.route("/")
def index(): return render_template_string(HTML)

@app.route("/start",methods=["POST"])
def start_route():
    global pipeline_running,output_queue
    if pipeline_running: return jsonify({"error":"Already running"})
    output_queue=queue.Queue()
    pipeline_running=True
    t=threading.Thread(target=pipeline_thread,args=(request.get_json(),output_queue),daemon=True)
    t.start()
    return jsonify({"ok":True})

@app.route("/stop",methods=["POST"])
def stop_route():
    global pipeline_running
    pipeline_running=False
    return jsonify({"ok":True})

@app.route("/stream")
def stream():
    def gen():
        global pipeline_running
        while True:
            try:
                item=output_queue.get(timeout=30)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type")=="done":
                    pipeline_running=False; break
            except queue.Empty:
                yield 'data: {"type":"log","msg":"heartbeat"}\n\n'
    return Response(gen(),mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/results/<path:filename>")
def serve_result(filename):
    from flask import send_from_directory
    return send_from_directory(str(BASE_DIR / "results"), filename)

if __name__=="__main__":
    print("Adaptive calibration monitor — server mode")
    print("Access via:  ssh -L 6001:localhost:6001 <user>@<server-ip>")
    print("Then open:   http://localhost:6001")
    app.run(debug=False,host="127.0.0.1",port=6001,threaded=True)
