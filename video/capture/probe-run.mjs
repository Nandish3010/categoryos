// Dev helper: screenshot each Run page after it settles, to check what a capture will show. Usage: node capture/probe-run.mjs /tmp/probe
import { chromium } from 'playwright-core';
import fs from 'node:fs';
const BASE = process.env.BASE_URL || 'https://categoryos.vercel.app';
const dir = process.argv[2] || '/tmp/probe';
fs.mkdirSync(dir, { recursive: true });
const b = await chromium.launch({ channel: 'chrome', headless: true });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
await p.addInitScript("try { localStorage.setItem('categoryos.tour.v1', 'done'); } catch (e) {}");
for (const u of ['/run', '/run/price-requests', '/run/pos', '/run/catalog', '/run/promotions', '/run/price-watch', '/run/inventory-health']) {
  const t0 = Date.now();
  await p.goto(BASE + u, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await p.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
  const pulses = await p.locator('.animate-pulse').count();
  await p.waitForTimeout(1500);
  console.log(u, 'settled in', Date.now() - t0, 'ms; skeletons', pulses, '->', await p.locator('.animate-pulse').count());
  await p.screenshot({ path: `${dir}/${u.replace(/\W+/g, '_')}.png` });
}
await b.close();
