// Shared helpers for the screen-capture flows: recorded context, smooth fake cursor, click ripple, marks.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

export const BASE = process.env.BASE_URL || 'https://categoryos.vercel.app';
export const RAW = path.resolve(import.meta.dirname, '../captures/raw');

const CURSOR_JS = `
(() => {
  if (window.__cur) return;
  const mk = () => {
    if (!document.body) return requestAnimationFrame(mk);
    const c = document.createElement('div');
    c.id = '__cur';
    c.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;left:0;top:0;width:34px;height:34px;transform:translate(-100px,-100px);transition:none';
    c.innerHTML = '<svg width="34" height="34" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.6L9 19z" fill="#fff" stroke="#0F1117" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    window.__cur = c;
    addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)'; }, true);
    addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;border-radius:50%;border:4px solid #6EA8FE;width:20px;height:20px;left:' + (e.clientX - 10) + 'px;top:' + (e.clientY - 10) + 'px;opacity:.95;transition:all .55s cubic-bezier(.2,.7,.2,1)';
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.width = '90px'; r.style.height = '90px'; r.style.left = (e.clientX - 45) + 'px'; r.style.top = (e.clientY - 45) + 'px'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 700);
    }, true);
  };
  mk();
})();
`;

export async function launch() {
  return chromium.launch({ channel: 'chrome', headless: true });
}

/** Load the app once (any page) so a cold backend wakes up. */
export async function warm(browser) {
  const p = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  for (const u of ['/vendors/V001', '/vendors/V002', '/run']) {
    await p.goto(BASE + u, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await p.waitForTimeout(2500);
  }
  await p.close();
}

/** Record a flow via CDP screencast (no Playwright-bundled ffmpeg needed) and encode with system ffmpeg.
 *  fn(page, t) gets a helper kit; t.mark(name) stamps the time offset (ms) into <name>.json. */
export async function record(browser, name, fn) {
  fs.mkdirSync(RAW, { recursive: true });
  const dir = path.join(RAW, `_tmp_${name}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(CURSOR_JS);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  const frames = [];
  cdp.on('Page.screencastFrame', (f) => {
    const file = path.join(dir, `f${String(frames.length).padStart(6, '0')}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
    frames.push({ file, ts: f.metadata.timestamp });
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  const t0 = Date.now();
  const marks = {};
  const kit = makeKit(page, (n) => { marks[n] = Date.now() - t0; });
  try {
    await fn(page, kit);
  } catch (e) {
    console.log(`[${name}] flow error: ${String(e).slice(0, 200)}`);
  }
  marks.end = Date.now() - t0;
  await cdp.send('Page.stopScreencast').catch(() => {});
  await ctx.close();
  // concat list with per-frame durations; first frame defines t=0 so marks (relative to t0) get a small offset
  const first = frames[0].ts;
  marks._videoOffsetMs = Math.round(first * 1000 - t0); // video time of a mark = mark - this offset
  const lines = [];
  frames.forEach((f, i) => {
    const d = i + 1 < frames.length ? frames[i + 1].ts - f.ts : Math.max(0.1, Date.now() / 1000 - f.ts); // hold the last frame to the end of the flow
    lines.push(`file '${f.file}'`, `duration ${Math.max(0.001, d).toFixed(4)}`);
  });
  lines.push(`file '${frames[frames.length - 1].file}'`);
  fs.writeFileSync(path.join(dir, 'list.txt'), lines.join('\n'));
  const dst = path.join(RAW, `${name}.mp4`);
  execFileSync('/opt/homebrew/bin/ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'list.txt'), '-vf', 'scale=1920:1080,fps=30,format=yuv420p', '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-an', dst]);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.writeFileSync(path.join(RAW, `${name}.json`), JSON.stringify(marks, null, 2));
  console.log(`[${name}] ${(marks.end / 1000).toFixed(1)}s`, marks);
}

function makeKit(p, mark) {
  let cx = 960, cy = 540;
  const kit = {
    mark,
    wait: (ms) => p.waitForTimeout(ms),
    async moveTo(x, y, steps = 28) {
      for (let i = 1; i <= steps; i++) {
        const k = i / steps, e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; // ease in-out
        await p.mouse.move(cx + (x - cx) * e, cy + (y - cy) * e);
        await p.waitForTimeout(12);
      }
      cx = x; cy = y;
    },
    async point(loc, dy = 0) {
      await loc.scrollIntoViewIfNeeded({ timeout: 6000 }).catch(() => {});
      const b = await loc.boundingBox();
      if (!b) throw new Error('no box');
      await kit.moveTo(b.x + b.width / 2, b.y + b.height / 2 + dy);
      return b;
    },
    async click(loc) {
      await kit.point(loc);
      await p.waitForTimeout(160);
      await p.mouse.down(); await p.mouse.up();
      await p.waitForTimeout(350);
    },
    async clickText(text, opts = {}) { await kit.click(p.getByText(text, { exact: false }).first()); },
    async clickBtn(name) { await kit.click(p.getByRole('button', { name }).first()); },
    async clickTab(name) { await kit.click(p.getByRole('tab', { name }).first()); },
    /** Smooth scroll of the main scroll container (or window) by dy px over ms. */
    async scroll(dy, ms = 900) {
      const steps = Math.max(8, Math.round(ms / 30));
      for (let i = 0; i < steps; i++) { await p.mouse.wheel(0, dy / steps); await p.waitForTimeout(ms / steps); }
    },
    async until(fn, ms = 90000, every = 400) {
      const t = Date.now();
      while (Date.now() - t < ms) { if (await fn().catch(() => false)) return true; await p.waitForTimeout(every); }
      return false;
    },
    async visible(text) { return p.getByText(text, { exact: false }).first().isVisible(); },
    async goto(u) { await p.goto(BASE + u, { waitUntil: 'domcontentloaded', timeout: 120000 }); await p.waitForTimeout(1800); },
    async drag(loc, dx) {
      const b = await kit.point(loc);
      const x = b.x + b.width / 2, y = b.y + b.height / 2;
      await p.mouse.down();
      const n = 20;
      for (let i = 1; i <= n; i++) { await p.mouse.move(x + (dx * i) / n, y); await p.waitForTimeout(25); }
      await p.mouse.up(); cx = x + dx;
    },
  };
  return kit;
}
