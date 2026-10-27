// Dev helper: dump buttons / headings of a page to discover selectors. Usage: node capture/probe.mjs /vendors/V001 [click text...]
import { chromium } from 'playwright-core';
const BASE = process.env.BASE_URL || 'https://categoryos.vercel.app';
const [path, ...clicks] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome', headless: true });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
await p.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 120000 });
await p.waitForTimeout(4000);
for (const c of clicks) {
  await p.getByText(c, { exact: false }).first().click({ timeout: 8000 }).catch((e) => console.log('click fail', c));
  await p.waitForTimeout(2500);
}
const info = await p.evaluate(() => ({
  title: document.title,
  buttons: [...document.querySelectorAll('button,a[href],[role=tab],input,[role=slider]')].map((e) => `${e.tagName}:${(e.innerText || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.getAttribute('href') || '').trim().slice(0, 50).replace(/\n/g, ' ')}`),
  text: document.body.innerText.slice(0, 1800),
}));
console.log(info.buttons.join(' | '));
console.log('----');
console.log(info.text);
await p.screenshot({ path: process.env.SHOT || '/tmp/probe.png' });
await b.close();
