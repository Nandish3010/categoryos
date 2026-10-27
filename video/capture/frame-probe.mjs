// Dev helper: print the size and metadata of CDP screencast frames (to verify frames match the 1920x1080 viewport).
import { chromium } from 'playwright-core';
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ viewport: { width: 1920, height: +(process.env.VH || 1080) }, deviceScaleFactor: 1 });
const p = await ctx.newPage();
const cdp = await ctx.newCDPSession(p);
const seen = [];
cdp.on('Page.screencastFrame', (f) => {
  seen.push({ meta: f.metadata, bytes: f.data.length });
  cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
});
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 80, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
await p.goto('https://categoryos.vercel.app/vendors/V002');
await p.waitForTimeout(3000);
console.log(JSON.stringify(seen.slice(-2), null, 1), await p.evaluate(() => [innerWidth, innerHeight]));
await b.close();
