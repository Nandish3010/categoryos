// Records the screen flows from the live app into captures/raw/*.webm (+ .json marks), then converts to mp4 in captures/.
// Usage: node capture/capture.mjs [flow ...]   (default: all). BASE_URL overrides the target (e.g. a live-mode deploy).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { BASE, RAW, launch, record, warm } from './lib.mjs';

const OUT = path.resolve(import.meta.dirname, '../captures');
const FLOWS = {
  // V001: run -> verifier catch -> lever drag -> price-list mismatch -> scan viewer (label crop, price list)
  async v1(p, t) {
    await t.goto('/vendors/V001');
    t.mark('start');
    await t.clickBtn('Run agents');
    await t.until(() => p.getByRole('button', { name: 'Re-run agents' }).isVisible(), 120000);
    t.mark('decided');
    await t.wait(900);
    // verifier: Test the verifier opens the injected wrong claim that gets rejected
    t.mark('verifier');
    await t.clickBtn('Test the verifier').catch(() => {});
    await t.wait(3200);
    t.mark('lever');
    const slider = p.locator('input[type=range]').first();
    await t.drag(slider, -150).catch(() => {});
    await t.wait(1500);
    await t.drag(slider, 230).catch(() => {});
    await t.wait(1800);
    await t.scroll(500, 1100);
    await t.wait(1800);
    t.mark('docs');
    await p.mouse.wheel(0, -2000);
    await t.wait(500);
    await t.clickText('Screening passed').catch(() => {});
    await t.wait(1800);
    await t.scroll(380, 900);
    await t.wait(2400); // price-list mismatch row
    t.mark('scans');
    await t.clickText('Show the scans with what was read').catch(() => {});
    await t.wait(2200);
    for (const n of await p.getByRole('tab').allInnerTexts().catch(() => [])) {
      if (/^(Decision|Negotiate)$/.test(n.trim())) continue;
      await t.clickTab(n.trim()).catch(() => {});
      await t.wait(2600);
    }
    t.mark('done');
  },
  // V001 label check: approve Research and Shortlist, Catalog runs, label vs sheet mismatch + the label panel crop
  async v1label(p, t) {
    await t.goto('/vendors/V001');
    await t.clickBtn('Run agents');
    await t.until(() => p.getByRole('button', { name: 'Re-run agents' }).isVisible(), 120000);
    await t.clickBtn('Approve and continue');
    await t.wait(4500);
    await t.clickBtn('Approve and continue').catch(() => {});
    await t.wait(2500);
    await t.until(() => p.getByRole('button', { name: 'Approve catalog' }).first().isVisible(), 120000);
    await t.wait(1200);
    t.mark('catalog');
    await t.scroll(560, 1100);
    await t.wait(2600);
    t.mark('mismatch');
    await t.clickBtn('View the label').catch(() => {});
    await t.wait(1500);
    t.mark('panel');
    await t.scroll(320, 900);
    await t.wait(3200);
    t.mark('done');
  },
  // V002: intake scan (FSSAI expiry) -> negotiate live call (simulated) -> deal evaluator -> say next
  async v2(p, t) {
    await t.goto('/vendors/V002');
    t.mark('start');
    await t.clickBtn('Run agents');
    await t.until(() => p.getByText('Re-run agents').first().isVisible(), 120000);
    await t.wait(700);
    t.mark('intake');
    await t.clickText('Screening passed').catch(() => {});
    await t.wait(1500);
    await t.clickText('Show the scans with what was read').catch(() => {});
    await t.wait(3200);
    t.mark('fssai');
    await p.mouse.wheel(0, -2500);
    await t.wait(400);
    await t.clickBtn('Negotiate').catch(() => {});
    await t.wait(900);
    await t.clickText('Live call').catch(() => {});
    await t.wait(1200);
    t.mark('call');
    const fast = p.getByLabel('4× speed');
    await t.click(fast).catch(() => {});
    await t.clickBtn('Simulate call');
    await t.until(() => p.getByTestId('dont-accept').isVisible(), 120000, 300);
    t.mark('reject');
    await t.wait(900);
    await p.getByTestId('dont-accept').scrollIntoViewIfNeeded().catch(() => {});
    await t.wait(3000);
    t.mark('sayNext');
    await t.until(async () => /Last suggestion/.test(await p.getByTestId('next-ask').innerText()), 25000, 500);
    await p.getByTestId('next-ask').scrollIntoViewIfNeeded().catch(() => {});
    await t.wait(3200);
    t.mark('done');
  },
  // The Run pages, playbook, bring-your-own
  async montage(p, t) {
    for (const [u, tag, scrollBy] of [['/run', 'run', 400], ['/run/price-requests', 'price', 450], ['/run/catalog', 'catalog', 420], ['/run/promotions', 'promos', 380], ['/run/price-watch', 'watch', 380], ['/rules', 'rules', 500], ['/try', 'try', 250]]) {
      await t.goto(u);
      t.mark(tag);
      await t.moveTo(1200, 500);
      await t.wait(900);
      await t.scroll(scrollBy, 1200);
      await t.wait(1400);
    }
  },
  // Impact meter (also captures the /api/impact JSON the app fetches)
  async impact(p, t) {
    let json = null;
    p.on('response', async (r) => { if (r.url().includes('/api/impact') && r.ok()) json = await r.json().catch(() => null); });
    await t.goto('/vendors/V001');
    t.mark('start');
    await t.wait(1200);
    await t.click(p.getByRole('button', { name: /Impact/ }).first()).catch(() => {});
    await t.wait(4500);
    t.mark('open');
    await t.scroll(300, 800);
    await t.wait(1800);
    // vendors board: team impact projection (GET /api/impact)
    await t.goto('/');
    t.mark('board');
    await t.wait(3500);
    await t.scroll(500, 1200);
    await t.wait(2500);
    t.mark('boardEnd');
    if (json) fs.writeFileSync(path.resolve(import.meta.dirname, '../src/data/impact.json'), JSON.stringify(json, null, 2));
  },
};

const want = process.argv.slice(2);
const names = want.length ? want : Object.keys(FLOWS);
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.resolve(import.meta.dirname, '../src/data'), { recursive: true });
const browser = await launch();
console.log('warming', BASE);
await warm(browser);
for (const n of names) {
  await record(browser, n, FLOWS[n]);
  fs.copyFileSync(path.join(RAW, `${n}.mp4`), path.join(OUT, `${n}.mp4`));
  fs.copyFileSync(path.join(RAW, `${n}.json`), path.join(OUT, `${n}.json`));
}
await browser.close();
