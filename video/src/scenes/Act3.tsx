import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { Meera } from '../components/Meera';
import { VoCaptions } from '../components/Captions';
import { body, C, display, E, FPS, H, MARGIN_X, pop, prog, rnd, sceneOf, W } from '../theme';
import { IMPACT, MODELS, URL } from '../config';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const ROWS = 8;
const TASKS = ['Emails', 'Sheets', 'Calls', 'Licences', 'Chasing', 'Catalog', 'Reports', 'Follow-ups'];
const GOOD = ['Strategy', 'Vendors', 'Growth'];
const CELL_W = 214, CELL_H = 70, GAP = 6, GX = MARGIN_X + 30, GY = 232;

const savedPct = IMPACT.saved_pct as number; // modelled % of the week, read from GET /api/impact at capture time
const saved = Math.round(savedPct);
const SAVED_BLOCKS = Math.round((DAYS.length * ROWS * savedPct) / 100);
// the blocks that dissolve into green (deterministic pick)
const order = Array.from({ length: DAYS.length * ROWS }, (_, i) => i).sort((a, b) => rnd(a * 1.3 + 4) - rnd(b * 1.3 + 4));
const GREEN = new Set(order.slice(0, SAVED_BLOCKS));

export const WeekScene: React.FC = () => {
  const lf = useCurrentFrame();
  const sc = sceneOf('a3-week');
  const melt = sc.frames * 0.3; // melt starts here
  const hours = (IMPACT.hours_saved_per_month as number) ?? 0;
  const calm = prog(lf, melt, melt + 60, E.inOut);
  const pct = (IMPACT.saved_pct as number) * prog(lf, melt + 10, melt + 70, E.out);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(1300px 800px at 50% 35%, ${calm > 0.5 ? '#123222' : '#2a1613'} 0%, ${calm > 0.5 ? '#0c1a14' : '#140b09'} 62%)`, transition: 'none' }}>
      <AbsoluteFill style={{ background: `radial-gradient(1300px 800px at 50% 35%, #123222 0%, #0c1a14 62%)`, opacity: calm }} />
      <div style={{ position: 'absolute', left: GX, top: 60, fontFamily: display, fontWeight: 700, fontSize: 64, color: C.text }}>
        {calm < 0.5 ? <span style={{ color: C.red }}>Before</span> : <span style={{ color: C.green }}>With CategoryOS</span>}
        <span style={{ fontFamily: body, fontWeight: 500, fontSize: 36, color: C.dim, marginLeft: 22 }}>a category team's week</span>
      </div>
      {DAYS.map((d, c) => <div key={d} style={{ position: 'absolute', left: GX + c * (CELL_W + GAP), top: 180, width: CELL_W, textAlign: 'center', fontFamily: display, fontWeight: 700, fontSize: 34, color: C.dim }}>{d}</div>)}
      {Array.from({ length: DAYS.length * ROWS }).map((_, i) => {
        const c = Math.floor(i / ROWS), r = i % ROWS;
        const inAt = 2 + (c * ROWS + r) * 0.9;
        const p = pop(lf, inAt, FPS, 14, 220, 0.5);
        const g = GREEN.has(i);
        const rank = order.indexOf(i);
        const meltAt = melt + rank * 2.6;
        const m = g ? prog(lf, meltAt, meltAt + 14, E.inOut) : 0;
        const warm = i % 3 === 0 ? C.orange : C.red;
        const bg = m > 0.5 ? C.green : warm;
        const label = m > 0.5 ? GOOD[i % 3] : TASKS[(c * 3 + r) % TASKS.length];
        return (
          <div key={i} style={{ position: 'absolute', left: GX + c * (CELL_W + GAP), top: GY + r * (CELL_H + GAP), width: CELL_W, height: CELL_H, borderRadius: 12, background: bg, color: '#10131a', fontFamily: body, fontWeight: 700, fontSize: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${p * (1 + Math.sin(m * Math.PI) * 0.1)})`, opacity: Math.min(1, p * 1.5) * (m > 0 && m < 0.5 ? 1 - m * 1.4 : 1), boxShadow: m > 0.5 ? `0 0 28px ${C.green}88` : 'none' }}>{label}</div>
        );
      })}
      {/* big modelled number */}
      <div style={{ position: 'absolute', right: MARGIN_X, top: 130, width: 520, textAlign: 'right', opacity: prog(lf, melt + 20, melt + 40) }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 170, lineHeight: 1, color: C.green }}>{pct.toFixed(1)}%</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 36, color: C.text }}>of the week back</div>
        <div style={{ display: 'inline-block', marginTop: 14, background: C.yellow, color: '#10131a', fontWeight: 700, fontSize: 32, fontFamily: body, padding: '6px 20px', borderRadius: 999 }}>modelled, not measured</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 32, color: C.dim, marginTop: 18 }}>{hours.toFixed(0)} h / month for this team</div>
      </div>
      <div style={{ position: 'absolute', left: GX, top: 960 - 56, fontFamily: body, fontSize: 28, color: C.dim, opacity: prog(lf, melt + 50, melt + 70) }} />
      <WeekCaption lf={lf} start={melt + 40} />
      {lf > melt + 40 ? <Meera pose="relaxed" x={1640} y={H - 120} h={430} sy={1 + Math.sin(lf * 0.12) * 0.006} z={5} /> : null}
      {lf > melt + 40 ? <Steam lf={lf} x={1590} y={H - 120 - 270} /> : null}
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
      {'≈'} a third of the category team's week, back (modelled)
    </div>
  );
};

export const CloseScene: React.FC = () => {
  const lf = useCurrentFrame();
  const sc = sceneOf('a3-close');
  const waveP = pop(lf, 0, FPS, 11, 140, 0.8);
  const wave = Math.sin(lf * 0.35) * 5;
  const url = prog(lf, sc.frames * 0.55, sc.frames * 0.55 + 20, E.out);
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
      <Meera pose="waving" x={1560} y={H - 120} h={640} sx={0.9 + 0.1 * waveP} sy={0.9 + 0.1 * waveP} rot={wave} z={5} />
      <Sequence from={0} layout="none"><VoCaptions sceneId="a3-close" accent={C.green} bottom={40} /></Sequence>
    </AbsoluteFill>
  );
};

void W;
void saved;
