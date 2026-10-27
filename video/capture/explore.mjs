// Dev helper: run a sequence of steps and screenshot after each. node capture/explore.mjs <path> <outprefix> "click:Text" "wait:2000" "shot"
import { chromium } from 'playwright-core';
const BASE = process.env.BASE_URL || 'https://categoryos.vercel.app';
const [path, prefix, ...steps] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome', headless: true });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
await p.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 120000 });
await p.waitForTimeout(3000);
let n = 0;
for (const s of steps) {
  const [k, ...r] = s.split(':');
  const v = r.join(':');
  try {
    if (k === 'click') await p.getByText(v, { exact: false }).first().click({ timeout: 8000 });
    else if (k === 'btn') await p.getByRole('button', { name: v }).first().click({ timeout: 8000 });
    else if (k === 'tab') await p.getByRole('tab', { name: v }).first().click({ timeout: 8000 });
    else if (k === 'wait') await p.waitForTimeout(+v);
    else if (k === 'eval') console.log(JSON.stringify(await p.evaluate(v)));
    else if (k === 'scroll') await p.mouse.wheel(0, +v);
    else if (k === 'shot') await p.screenshot({ path: `${prefix}-${n++}.png` });
    else if (k === 'text') console.log((await p.evaluate(() => document.body.innerText)).slice(0, +v || 1500));
  } catch (e) {
    console.log('FAIL', s, String(e).slice(0, 100));
  }
}
await b.close();
