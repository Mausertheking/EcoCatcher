import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import { spawn } from 'node:child_process';
const mode = process.argv[2] || 'stills';           // stills | video
const FPS = 30, DUR = 28.2;
const b = await chromium.launch();
const ctx = await b.newContext({ viewport:{width:1920,height:1080}, deviceScaleFactor:1, reducedMotion:'no-preference' });
await ctx.addInitScript(()=>{ let s=1234567; Math.random=()=>{ s^=s<<13; s^=s>>>17; s^=s<<5; return ((s>>>0)%1e9)/1e9; }; });
const p = await ctx.newPage();
await p.clock.install({ time: new Date('2026-10-08T12:00:00Z') });
await p.goto('http://127.0.0.1:8765/brag-output/work/comp.html');
await p.clock.runFor(2000);
await p.evaluate(()=>window.compReady);
await p.waitForTimeout(800); // real time for fonts/layout
const step = 1000/FPS;
let simT = 0;                                       // seconds of animation time already advanced
async function frameAt(t){
  await p.evaluate(t=>window.renderAt(t), t);
  const target = t*1000; if (target > simT) { await p.clock.runFor(Math.round(target - simT)); simT = target; }
}
if (mode === 'stills') {
  const times = (process.argv[3]||'1.5,2.9,4.8,6.4,7.9,8.95,9.5,11.5,12.5,13.0,14.6,16.2,16.9,18.2,19.6,20.6,22.5,23.9').split(',').map(Number);
  let last = 0;
  for (const t of times) {
    for (let x = last; x < t; x += step/1000) await frameAt(x);   // run sequentially so state carries
    await frameAt(t); last = t;
    await p.screenshot({ path:`still-${t.toFixed(2)}.png` });
  }
} else {
  const ff = spawn('ffmpeg', ['-y','-loglevel','error','-f','image2pipe','-framerate',String(FPS),'-c:v','png','-i','-','-c:v','libx264','-preset','medium','-crf','16','-pix_fmt','yuv420p','video-silent.mp4'], { stdio:['pipe','inherit','inherit'] });
  const N = Math.round(DUR*FPS);
  for (let i=0;i<N;i++){
    await frameAt(i/FPS);
    const buf = await p.screenshot({ type:'png' });
    if (!ff.stdin.write(buf)) await new Promise(r=>ff.stdin.once('drain',r));
    if (i%60===0) console.log('frame',i,'/',N);
  }
  ff.stdin.end(); await new Promise(r=>ff.on('close',r));
}
await b.close();
