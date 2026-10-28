import React from 'react';
import { body, C, display, E, FPS, prog, rnd } from '../theme';
import { Plan, stateAt, WalkState } from './MeeraWalker';

/** Things Meera carries and hands off while she walks (all drawn with divs: no new image assets). */

const PITCH = 40; // vertical pitch of the documents in the stack
export const DOC_W = 120;
const DOC_COLORS = ['#F5F1E6', '#FFFFFF', '#EFE9D8', '#F8F4EA'];
const BAND = [C.blue, C.orange, C.green, C.yellow, '#F9A8D4', C.red];

/** One paper document (front view). */
const Doc: React.FC<{ w?: number; i?: number; label?: string; tint?: string }> = ({ w = DOC_W, i = 0, label, tint }) => {
  const h = w * 0.62;
  const band = tint ?? BAND[i % BAND.length];
  return (
    <div style={{ width: w, height: h, background: DOC_COLORS[i % DOC_COLORS.length], borderRadius: 4, boxShadow: '0 3px 8px rgba(0,0,0,.4)', border: '1px solid rgba(0,0,0,.18)', position: 'relative', overflow: 'hidden' }}>
      <div style={{ height: h * 0.2, background: band }} />
      {label ? (
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: w * 0.15, color: '#1a1d26', textAlign: 'center', marginTop: h * 0.1 }}>{label}</div>
      ) : (
        <>
          <div style={{ height: 3, background: '#9aa0ad', margin: `${h * 0.14}px ${w * 0.1}px 0`, borderRadius: 2 }} />
          <div style={{ height: 3, background: '#9aa0ad', margin: `${h * 0.1}px ${w * 0.1}px 0 ${w * 0.1}px`, width: w * 0.55, borderRadius: 2 }} />
        </>
      )}
    </div>
  );
};

export type Throw = { at: number; label?: string; color?: string; to: { x: number; y: number }; dur?: number };

/** Documents that have already left the stack at frame f (sheets go top-down). */
export const sheetsLeft = (total: number, throws: Throw[], perThrow: number, f: number) => {
  let gone = 0;
  throws.forEach((t) => { for (let k = 0; k < perThrow; k++) if (f >= t.at + k * 5) gone++; });
  return Math.max(0, total - gone);
};

/** Top-centre of the stack for a walker state (screen px). */
const stackBase = (s: WalkState) => ({ x: s.x + 0.335 * s.h, y: s.y - 0.36 * s.h });

/**
 * A tall, wobbly pile of documents that Meera carries (it sits on her right, screen side, so it never covers her face or the pointing arm).
 * `sheets(f)` says how many are left; the pile sways with her steps and with a slow wobble of its own, the top sways more than the bottom.
 */
export const PaperStack: React.FC<{ s: WalkState; sheets: number; total: number }> = ({ s, sheets, total }) => {
  if (sheets <= 0) return null;
  const { x, y } = stackBase(s);
  const f = s.f;
  const walk = s.walking ? Math.sin(f * 0.5) * 2.4 : 0;
  const tilt = s.rot * 1.4 + Math.sin(f * 0.09) * 1.4 + walk;
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: 0, height: 0, zIndex: 31, transform: `rotate(${tilt}deg)`, transformOrigin: '0 0' }}>
      {Array.from({ length: sheets }).map((_, i) => {
        const hi = i / (total - 1);
        const jitter = (rnd(i * 3.7 + 1) - 0.5) * 18;
        const wob = Math.sin(f * 0.13 - i * 0.55) * (3 + hi * hi * 16) * (0.6 + (s.walking ? 0.8 : 0.3));
        const rot = (rnd(i * 1.9 + 2) - 0.5) * 7 + Math.sin(f * 0.11 - i * 0.4) * hi * 3;
        return (
          <div key={i} style={{ position: 'absolute', left: -DOC_W / 2 + jitter + wob, top: -(i + 1) * PITCH, transform: `rotate(${rot}deg)` }}>
            <Doc i={i} />
          </div>
        );
      })}
    </div>
  );
};

/** Where a thrown sheet leaves the stack (top of the pile at frame t). */
const docStart = (plan: Plan, t: number, sheetsBefore: number) => {
  const s = stateAt(plan, t);
  const b = stackBase(s);
  return { x: b.x, y: b.y - Math.max(1, sheetsBefore) * PITCH };
};

/** A document flying from the stack into the app frame in an arc; the agent takes it off her plate (ring pulse + tick on landing). */
export const FlyingDocs: React.FC<{ plan: Plan; f: number; throws: Throw[]; total: number; perThrow: number }> = ({ plan, f, throws, total, perThrow }) => (
  <>
    {throws.flatMap((t, ti) =>
      Array.from({ length: perThrow }).map((_, k) => {
        const t0 = t.at + k * 5, dur = t.dur ?? 24;
        if (f < t0 || f > t0 + dur + 16) return null;
        const left = total - (ti * perThrow + k); // sheets in the stack just before this one leaves
        const st = docStart(plan, t0, left);
        const u = prog(f, t0, t0 + dur, E.inOut);
        const tx = t.to.x + (k - 1) * 26, ty = t.to.y + (k - 1) * 14;
        const x = st.x + (tx - st.x) * u, y = st.y + (ty - st.y) * u - Math.sin(Math.PI * u) * 210;
        const big = 1 + 0.45 * Math.sin(Math.PI * Math.min(1, u * 1.3)) - (u > 0.8 ? (u - 0.8) * 2.4 : 0);
        const fade = 1 - prog(f, t0 + dur - 3, t0 + dur + 3);
        const landed = f - (t0 + dur);
        return (
          <React.Fragment key={`${ti}-${k}`}>
            <div style={{ position: 'absolute', left: x - DOC_W / 2, top: y - DOC_W * 0.31, transform: `rotate(${-14 + u * 380 * (k % 2 ? -1 : 1)}deg) scale(${Math.max(0.2, big)})`, opacity: fade, zIndex: 36 }}>
              <Doc i={k + ti} label={k === 0 ? t.label : undefined} w={DOC_W} tint={t.color} />
            </div>
            {k === 0 && landed >= 0 ? <LandPulse x={t.to.x} y={t.to.y} a={landed} color={t.color ?? C.green} /> : null}
          </React.Fragment>
        );
      }),
    )}
  </>
);

const LandPulse: React.FC<{ x: number; y: number; a: number; color: string }> = ({ x, y, a, color }) => {
  const p = Math.min(1, a / 14);
  return (
    <div style={{ position: 'absolute', left: x - 70 * p, top: y - 70 * p, width: 140 * p, height: 140 * p, borderRadius: '50%', border: `${Math.max(1, 8 * (1 - p))}px solid ${color}`, opacity: 1 - p, zIndex: 36 }} />
  );
};

export type Card = { at: number; text: string; color: string; to: { x: number; y: number }; dur?: number };

/** Where her hand is when she hands something off (pointing arm: the fingertips). */
const handAt = (plan: Plan, t: number) => {
  const s = stateAt(plan, t);
  const reach = s.pose === 'pointing' ? 0.33 * s.h * (s.dir) : 0.2 * s.h * s.dir;
  return { x: s.x + reach, y: s.y - (s.pose === 'pointing' ? 0.76 : 0.5) * s.h };
};

/** Small coloured task cards that fly from her hand to the app frame (ring pulse + tick where they land). */
export const TaskCards: React.FC<{ plan: Plan; f: number; cards: Card[] }> = ({ plan, f, cards }) => (
  <>
    {cards.map((c, i) => {
      const dur = c.dur ?? 20;
      if (f < c.at || f > c.at + dur + 18) return null;
      const st = handAt(plan, c.at);
      const u = prog(f, c.at, c.at + dur, E.inOut);
      const x = st.x + (c.to.x - st.x) * u, y = st.y + (c.to.y - st.y) * u - Math.sin(Math.PI * u) * 150;
      const sc = (0.4 + 0.75 * Math.min(1, u * 2.2)) * (u > 0.82 ? 1 - (u - 0.82) * 3 : 1);
      const fade = 1 - prog(f, c.at + dur - 2, c.at + dur + 3);
      const landed = f - (c.at + dur);
      return (
        <React.Fragment key={i}>
          <div style={{ position: 'absolute', left: x - 92, top: y - 40, width: 184, transform: `rotate(${(1 - u) * -16 + u * 6}deg) scale(${Math.max(0.2, sc)})`, opacity: fade, zIndex: 36 }}>
            <div style={{ background: c.color, color: '#10131a', fontFamily: body, fontWeight: 700, fontSize: 26, lineHeight: 1.1, padding: '12px 14px', borderRadius: 12, boxShadow: '0 8px 22px rgba(0,0,0,.45)', textAlign: 'center' }}>{c.text}</div>
          </div>
          {landed >= 0 ? <LandPulse x={c.to.x} y={c.to.y} a={landed} color={c.color} /> : null}
        </React.Fragment>
      );
    })}
  </>
);

/** A burst of four-point sparkles and a ring (the high-five). `a` = frames since the contact. */
export const SparkleBurst: React.FC<{ x: number; y: number; a: number; size?: number }> = ({ x, y, a, size = 1 }) => {
  if (a < 0 || a > 40) return null;
  const SPARK = [C.yellow, '#FFFFFF', C.orange, '#F9A8D4', C.blue];
  const ring = Math.min(1, a / 12);
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: 0, height: 0, zIndex: 38 }}>
      <div style={{ position: 'absolute', left: -90 * ring * size, top: -90 * ring * size, width: 180 * ring * size, height: 180 * ring * size, borderRadius: '50%', border: `${Math.max(1, 10 * (1 - ring))}px solid ${C.yellow}`, opacity: 1 - ring, boxShadow: `0 0 40px ${C.yellow}88` }} />
      {Array.from({ length: 12 }).map((_, i) => {
        const ang = (i / 12) * Math.PI * 2 + rnd(i) * 0.4;
        const dist = (60 + rnd(i * 2.1) * 130) * E.out(Math.min(1, a / 22)) * size;
        const life = 1 - Math.min(1, Math.max(0, (a - 10) / 28));
        const sz = (22 + rnd(i * 5.3) * 30) * size * (0.4 + 0.6 * life) * (1 + 0.25 * Math.sin(a * 0.9 + i));
        return (
          <svg key={i} width={sz} height={sz} viewBox="-10 -10 20 20" style={{ position: 'absolute', left: Math.cos(ang) * dist - sz / 2, top: Math.sin(ang) * dist - sz / 2 - a * 0.6, opacity: life, transform: `rotate(${a * 6 + i * 20}deg)`, overflow: 'visible' }}>
            <path d="M0 -10 C1 -2 2 -1 10 0 C2 1 1 2 0 10 C-1 2 -2 1 -10 0 C-2 -1 -1 -2 0 -10Z" fill={SPARK[i % SPARK.length]} />
          </svg>
        );
      })}
    </div>
  );
};
