import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { MeeraWalker } from '../components/MeeraWalker';
import { VoCaptions } from '../components/Captions';
import { body, C, display, E, FPS, H, MARGIN_X, phraseFrame, pop, prog, rnd, sceneOf, W } from '../theme';
import { IMPACT, MODELS, URL } from '../config';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const ROWS = 8;
const CELLS = DAYS.length * ROWS;
const CELL_W = 214, CELL_H = 70, GAP = 6, GX = MARGIN_X + 30, GY = 232;

// Task blocks of the week. The eight kinds below are the modules CategoryOS runs; every pct comes from GET /api/impact modules[].saved_pct
// (saved in src/data/impact.json), nothing is hard-coded. `say` = the VO phrase on which that module's blocks turn green.
type Mod = { key: string; label: string; say: string };
const MODS: Mod[] = [
  { key: 'new_vendor_onboarding', label: 'Onboarding', say: 'Onboarding' },
  { key: 'weekly_review_mis', label: 'Weekly review', say: 'weekly reviews' },
  { key: 'catalog_qc_queue', label: 'Catalog QC', say: 'catalog fixes' },
  { key: 'po_followup', label: 'PO follow-up', say: 'purchase-order' },
  { key: 'promotions_planner', label: 'Promotions', say: 'about a third' },
  { key: 'price_increase_evaluator', label: 'Price requests', say: 'about a third' },
  { key: 'competitor_monitor', label: 'Price watch', say: 'about a third' },
  { key: 'inventory_health_module', label: 'Inventory', say: 'about a third' },
];
const OTHER = ['Emails', 'Sheets', 'Calls', 'Licences', 'Chasing', 'Reports', 'Follow-ups', 'Approvals'];
const modRows = (IMPACT.modules as { key: string; saved_pct: number }[]) ?? [];
const pctOf = (key: string) => modRows.find((m) => m.key === key)?.saved_pct ?? 0;
const savedPct = IMPACT.saved_pct as number; // modelled % of the week back
const SAVED_BLOCKS = Math.round((CELLS * savedPct) / 100);
// blocks per module: largest-remainder share of SAVED_BLOCKS by saved_pct
const modTotal = MODS.reduce((n, x) => n + pctOf(x.key), 0) || 1;
const exact = MODS.map((m) => (pctOf(m.key) / modTotal) * SAVED_BLOCKS);
const counts = exact.map(Math.floor);
exact
  .map((e, i) => ({ i, r: e - Math.floor(e) }))
  .sort((a, b) => b.r - a.r)
  .slice(0, SAVED_BLOCKS - counts.reduce((n, c) => n + c, 0))
  .forEach((x) => { counts[x.i] += 1; });
// spread the module blocks over the week (deterministic shuffle); the rest are other manual work
const order = Array.from({ length: CELLS }, (_, i) => i).sort((a, b) => rnd(a * 1.3 + 4) - rnd(b * 1.3 + 4));
const CELL_MOD: Record<number, number> = {};
const CELL_NTH: Record<number, number> = {};
{
  let cur = 0;
  counts.forEach((c, mi) => { for (let k = 0; k < c; k++) { CELL_MOD[order[cur]] = mi; CELL_NTH[order[cur]] = k; cur++; } });
}
const TEAM = ((IMPACT.roles as { headcount: number }[]) ?? []).reduce((n, r) => n + r.headcount, 0);

/** Meera never pops in: in the week scene she walks in from the right once the first block has melted, in the close she walks in and waves. */
const WEEK_WALK = { floor: H - 70, h: 330, enterFrom: 'right' as const, beats: [{ at: Math.min(...MODS.map((m) => phraseFrame('a3-week', m.say))) + 58, x: 1700, pose: 'relaxed' as const }] };
const CLOSE_WALK = { floor: H - 120, h: 640, enterFrom: 'right' as const, enterSpeed: 520, beats: [{ at: 40, x: 1560, pose: 'waving' as const }] };

export const WeekScene: React.FC = () => {
  const lf = useCurrentFrame();
  const sc = sceneOf('a3-week');
  const hours = (IMPACT.hours_saved_per_month as number) ?? 0;
  const sayF = MODS.map((m) => phraseFrame('a3-week', m.say));
  const firstMelt = Math.min(...sayF);
  const calm = prog(lf, firstMelt, firstMelt + 70, E.inOut);
  const grow = prog(lf, firstMelt + 10, sc.frames - 40, E.inOut);
  const meltAt = (mi: number, n: number) => sayF[mi] + n * 5;
  return (
    <AbsoluteFill style={{ background: `radial-gradient(1300px 800px at 50% 35%, ${calm > 0.5 ? '#123222' : '#2a1613'} 0%, ${calm > 0.5 ? '#0c1a14' : '#140b09'} 62%)` }}>
      <AbsoluteFill style={{ background: 'radial-gradient(1300px 800px at 50% 35%, #123222 0%, #0c1a14 62%)', opacity: calm }} />
      <div style={{ position: 'absolute', left: GX, top: 60, fontFamily: display, fontWeight: 700, fontSize: 64, color: C.text }}>
        {calm < 0.5 ? <span style={{ color: C.red }}>Before</span> : <span style={{ color: C.green }}>With CategoryOS</span>}
        <span style={{ fontFamily: body, fontWeight: 500, fontSize: 36, color: C.dim, marginLeft: 22 }}>a category team's week</span>
      </div>
      {DAYS.map((d, c) => <div key={d} style={{ position: 'absolute', left: GX + c * (CELL_W + GAP), top: 180, width: CELL_W, textAlign: 'center', fontFamily: display, fontWeight: 700, fontSize: 34, color: C.dim }}>{d}</div>)}
      {Array.from({ length: CELLS }).map((_, i) => {
        const c = Math.floor(i / ROWS), r = i % ROWS;
        const inAt = 2 + (c * ROWS + r) * 0.9;
        const p = pop(lf, inAt, FPS, 14, 220, 0.5);
        const mi = CELL_MOD[i];
        const isMod = mi !== undefined;
        const at0 = isMod ? meltAt(mi, CELL_NTH[i]) : 0;
        const m = isMod ? prog(lf, at0, at0 + 14, E.inOut) : 0;
        const warm = i % 3 === 0 ? C.orange : C.red;
        const bg = m > 0.5 ? C.green : warm;
        const label = isMod ? MODS[mi].label : OTHER[(c * 3 + r) % OTHER.length];
        return (
          <div key={i} style={{ position: 'absolute', left: GX + c * (CELL_W + GAP), top: GY + r * (CELL_H + GAP), width: CELL_W, height: CELL_H, borderRadius: 12, background: bg, color: '#10131a', fontFamily: body, fontWeight: 700, fontSize: label.length > 12 ? 24 : 28, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${p * (1 + Math.sin(m * Math.PI) * 0.1)})`, opacity: Math.min(1, p * 1.5), boxShadow: m > 0.5 ? `0 0 28px ${C.green}88` : 'none' }}>{label}{m > 0.5 ? ' ✓' : ''}</div>
        );
      })}
      {/* big modelled number + the per-module split */}
      <div style={{ position: 'absolute', right: MARGIN_X, top: 120, width: 600, textAlign: 'right', opacity: prog(lf, firstMelt + 10, firstMelt + 30) }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 150, lineHeight: 1, color: C.green }}>{(savedPct * grow).toFixed(1)}%</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 34, color: C.text }}>of the week back</div>
        <div style={{ display: 'inline-block', marginTop: 10, background: C.yellow, color: '#10131a', fontWeight: 700, fontSize: 30, fontFamily: body, padding: '4px 18px', borderRadius: 999 }}>modelled, not measured</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 30, color: C.dim, marginTop: 12 }}>{(hours * grow).toFixed(0)} h / month for a team of {TEAM}</div>
      </div>
      <div style={{ position: 'absolute', right: MARGIN_X, top: 440, width: 600, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 10px' }}>
        {MODS.map((m, mi) => {
          const p = prog(lf, sayF[mi] + 2, sayF[mi] + 14);
          return (
            <div key={m.key} style={{ opacity: p, transform: `translateX(${(1 - p) * 30}px)`, background: 'rgba(15,17,23,.7)', border: `2px solid ${C.green}88`, borderRadius: 12, padding: '4px 12px', fontFamily: body, fontWeight: 700, fontSize: 24, color: C.text, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{m.label}</span><span style={{ color: C.green }}>{pctOf(m.key).toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
      <WeekCaption lf={lf} start={firstMelt + 40} />
      {/* she walks in from the right (where she left the Run scene) and settles with her coffee */}
      <MeeraWalker {...WEEK_WALK} z={5} />
      {lf > firstMelt + 58 ? <Steam lf={lf} x={1650} y={H - 70 - 205} /> : null}
      <VoCaptions sceneId="a3-week" accent={C.green} bottom={40} />
    </AbsoluteFill>
  );
};

const Steam: React.FC<{ lf: number; x: number; y: number }> = ({ lf, x, y }) => (
  <>
    {[0, 1, 2].map((i) => {
      const t = ((lf * 0.9 + i * 18) % 54) / 54;
      return <div key={i} style={{ position: 'absolute', left: x + Math.sin(t * 6 + i) * 10 + i * 14, top: y - t * 70, width: 12, height: 26, borderRadius: 8, background: 'rgba(255,255,255,.5)', opacity: (1 - t) * 0.6, filter: 'blur(4px)' }} />;
    })}
  </>
);

const WeekCaption: React.FC<{ lf: number; start: number }> = ({ lf, start }) => {
  const p = prog(lf, start, start + 16);
  return (
    <div style={{ position: 'absolute', left: GX, top: 868, right: 640, opacity: p, transform: `translateY(${(1 - p) * 16}px)`, fontFamily: display, fontWeight: 700, fontSize: 40, color: C.green }}>
      {'\u2248'} a third of the team's week, back (modelled)
    </div>
  );
};

export const CloseScene: React.FC = () => {
  const lf = useCurrentFrame();
  const sc = sceneOf('a3-close');
  const urlAt = phraseFrame('a3-close', 'Try it');
  const url = prog(lf, urlAt, urlAt + 14, E.out);
  return (
    <AbsoluteFill style={{ background: 'radial-gradient(1300px 800px at 50% 35%, #123222 0%, #0c1a14 62%)' }}>
      <div style={{ position: 'absolute', left: MARGIN_X, top: 70, fontFamily: display, fontWeight: 700, fontSize: 60, color: C.text }}>Built on five Meta models</div>
      <div style={{ position: 'absolute', left: MARGIN_X, top: 170, display: 'flex', flexWrap: 'wrap', gap: 18, width: 1250 }}>
        {MODELS.map((m, i) => {
          const p = pop(lf, 10 + i * 6, FPS, 12, 190, 0.6);
          return <div key={m} style={{ background: C.surface, border: `3px solid ${[C.blue, C.orange, C.yellow, C.green, C.red][i]}`, color: C.text, fontFamily: display, fontWeight: 700, fontSize: 38, padding: '12px 28px', borderRadius: 16, transform: `scale(${p}) rotate(${(1 - p) * -4}deg)`, opacity: Math.min(1, p * 2) }}>{m}</div>;
        })}
      </div>
      <div style={{ position: 'absolute', left: MARGIN_X, top: 470, fontFamily: body, fontWeight: 500, fontSize: 32, color: C.dim, opacity: prog(lf, 50, 64) }}>Presenter generated with Muse Image</div>
      <div style={{ position: 'absolute', left: MARGIN_X, top: 560, opacity: url, transform: `translateY(${(1 - url) * 40}px) scale(${0.96 + 0.04 * url})`, transformOrigin: '0 50%' }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 108, color: C.green, textShadow: `0 0 60px ${C.green}55` }}>categoryos.vercel.app</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 34, color: C.dim, marginTop: 6 }}>{URL}</div>
      </div>
      <MeeraWalker {...CLOSE_WALK} z={5} extraRot={(f) => Math.sin(f * 0.35) * 5} />
      <Sequence from={0} layout="none"><VoCaptions sceneId="a3-close" accent={C.green} bottom={40} /></Sequence>
    </AbsoluteFill>
  );
};

void W;
