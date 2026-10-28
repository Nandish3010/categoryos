import React from 'react';
import { useCurrentFrame } from 'remotion';
import { body, C, display, E, FPS, clamp, pop, prog } from '../theme';
import { Meera, Pose } from './Meera';

/**
 * A persistent on-stage Meera who WALKS between x positions along a floor line (no pop-ins).
 *
 * Give it beats {at, x, pose, text?}: `at` is the frame she has ARRIVED at `x` and shows `pose`. The walk to the beat starts early enough
 * (distance / speed) so that she arrives on `at`; if the previous beat leaves too little time she walks faster (never below the hold time).
 * Walk = the `running` pose with a step cycle: abs-sine bob (an arc, grounded on every footfall), a lean into the direction of travel, a squash on
 * each footfall, dust puffs, a flip to face the direction of travel, a trapezoid velocity profile (ease-in and ease-out), an anticipation crouch
 * before she sets off and a damped squash when she arrives. Between beats she idles with a breathing scale and a tiny weight shift.
 * See DIRECTION.md "Motion principles" for the vocabulary (anticipation, follow-through, arcs).
 */
export type Beat = {
  at: number; // frame she has arrived and shows `pose`
  x: number;
  pose: Pose;
  walkPose?: Pose; // pose shown while travelling TO this beat (default 'running')
  text?: string; // speech bubble
  textAt?: number; // default: at + 4
  textDur?: number; // default 70
  lean?: number; // degrees while standing here (+ = leans right); used to "lean in" to the frame
  hop?: number; // px hop on arrival (celebrations)
  speed?: number; // px/s for the walk to this beat (default 480)
  flip?: boolean; // force the facing of the idle pose
};
export type Exit = { at: number; to: 'left' | 'right'; speed?: number };
export type WalkOpts = {
  beats: Beat[];
  enterFrom?: 'left' | 'right';
  exit?: Exit;
  floor?: number; // y of the feet (px)
  h?: number; // on-screen height (px)
  walkSpeed?: number;
  enterSpeed?: number;
};

export const OFF_L = -190, OFF_R = 2110;
const STEP = 190; // nominal px per step
const SPEED = 480; // px/s default
const MIN_WALK = 12; // frames (even a one-step shuffle takes a beat)

type WalkSeg = { t0: number; t1: number; x0: number; x1: number; pose: Pose; steps: number; r: number; kind: 'enter' | 'walk' | 'exit'; beat: number };
type Foot = { f: number; x: number; dir: number };
export type Plan = { segs: WalkSeg[]; beats: Beat[]; feet: Foot[]; endF: number; floor: number; h: number; speeds: { kind: string; px: number; frames: number; avgPxS: number }[] };

export function planWalk(o: WalkOpts): Plan {
  const beats = [...o.beats].sort((a, b) => a.at - b.at);
  const segs: WalkSeg[] = [];
  const speeds: Plan['speeds'] = [];
  const mk = (kind: WalkSeg['kind'], t0: number, t1: number, x0: number, x1: number, pose: Pose, beat: number) => {
    const dist = Math.abs(x1 - x0);
    const D = Math.max(1, t1 - t0);
    segs.push({ t0, t1, x0, x1, pose, steps: Math.max(1, Math.round(dist / STEP)), r: Math.min(8, D / 3), kind, beat });
    speeds.push({ kind, px: Math.round(dist), frames: D, avgPxS: Math.round((dist / D) * FPS) });
  };
  let prevX = o.enterFrom === 'right' ? OFF_R : OFF_L;
  let prevAt = -Infinity;
  beats.forEach((b, i) => {
    const dist = Math.abs(b.x - prevX);
    if (dist > 3) {
      const sp = (b.speed ?? (i === 0 ? o.enterSpeed : o.walkSpeed) ?? SPEED) / FPS;
      const want = Math.max(MIN_WALK, Math.round(dist / sp));
      const t0 = Math.max(i === 0 ? 0 : prevAt + 8, b.at - want);
      mk(i === 0 ? 'enter' : 'walk', t0, b.at, prevX, b.x, b.walkPose ?? 'running', i);
    }
    prevX = b.x;
    prevAt = b.at;
  });
  let endF = Infinity;
  if (o.exit) {
    const off = o.exit.to === 'right' ? OFF_R : OFF_L;
    const dist = Math.abs(off - prevX);
    const D = Math.max(MIN_WALK, Math.round(dist / ((o.exit.speed ?? SPEED) / FPS)));
    mk('exit', o.exit.at, o.exit.at + D, prevX, off, 'running', beats.length);
    endF = o.exit.at + D;
  }
  // footfalls (frames at which a foot lands), for dust puffs
  const feet: Foot[] = [];
  segs.forEach((s) => {
    const D = s.t1 - s.t0, dir = Math.sign(s.x1 - s.x0);
    let k = 1;
    for (let u = 1; u <= D && k <= s.steps; u++) {
      while (k <= s.steps && trap(u, D, s.r) * s.steps >= k - 1e-6) { feet.push({ f: s.t0 + u, x: s.x0 + ((s.x1 - s.x0) * k) / s.steps, dir }); k++; }
    }
  });
  return { segs, beats, feet, endF, floor: o.floor ?? 1056, h: o.h ?? 350, speeds };
}

/** Trapezoid position profile: speeds up over `r` frames, cruises, slows down over `r` frames. 0..1 */
function trap(u: number, D: number, r: number): number {
  if (u <= 0) return 0;
  if (u >= D) return 1;
  const vp = 1 / (D - r);
  if (u < r) return (0.5 * vp * u * u) / r;
  if (u <= D - r) return vp * (0.5 * r + (u - r));
  const w = D - u;
  return 1 - (0.5 * vp * w * w) / r;
}
/** Speed as a fraction of the cruise speed (0..1) */
function trapSpeed(u: number, D: number, r: number): number {
  if (u <= 0 || u >= D) return 0;
  if (u < r) return u / r;
  if (u > D - r) return (D - u) / r;
  return 1;
}

export type WalkState = {
  f: number; x: number; y: number; // y = feet (with bob / hop)
  floor: number; h: number; pose: Pose; flip: boolean; dir: 1 | -1; // dir = the way she faces (+1 right)
  walking: boolean; sf: number; // speed factor 0..1
  bob: number; // 0..1 abs-sine arc
  rot: number; sx: number; sy: number;
  visible: boolean; since: number; // frames since the current beat began
  beat: number; // index of the beat she is at / heading for
};

export function stateAt(plan: Plan, f: number): WalkState {
  const { segs, beats, floor, h } = plan;
  const base: WalkState = { f, x: 0, y: floor, floor, h, pose: 'running', flip: false, dir: 1, walking: false, sf: 0, bob: 0, rot: 0, sx: 1, sy: 1, visible: true, since: 999, beat: 0 };
  if (f >= plan.endF) return { ...base, visible: false, x: segs[segs.length - 1]?.x1 ?? 0 };
  const seg = segs.find((s) => f >= s.t0 && f < s.t1);
  if (seg) {
    const D = seg.t1 - seg.t0, u = f - seg.t0;
    const p = trap(u, D, seg.r);
    const dir = (Math.sign(seg.x1 - seg.x0) || 1) as 1 | -1;
    const sf = trapSpeed(u, D, seg.r);
    const phase = p * seg.steps;
    const bob = Math.abs(Math.sin(Math.PI * phase));
    const footDip = Math.pow(1 - bob, 5); // 1 on the frame a foot lands
    const lean = dir * 6.5 * sf;
    const sway = 1.7 * Math.cos(Math.PI * phase) * sf;
    return {
      ...base, x: seg.x0 + (seg.x1 - seg.x0) * p, y: floor - bob * 0.045 * h * sf, pose: seg.pose, flip: dir < 0, dir, walking: true, sf, bob: bob * sf,
      rot: lean + sway, sx: 1 + 0.03 * footDip * sf + (1 - sf) * 0.0, sy: 1 - 0.05 * footDip * sf + 0.03 * sf * bob, since: u, beat: seg.beat,
    };
  }
  // standing: the last beat that has arrived (or, before the first, the first)
  let bi = 0;
  beats.forEach((b, i) => { if (f >= b.at) bi = i; });
  const b = beats[bi];
  const next = segs.find((s) => s.t0 > f && s.beat === bi + 1);
  const arrived = f >= b.at ? f - b.at : 0;
  const prevPose = bi > 0 ? beats[bi - 1].pose : b.pose;
  const lastWalk = [...segs].reverse().find((s) => s.t1 <= f + 0.01 && s.beat === bi && s.kind !== 'exit');
  const cameWalking = !!lastWalk && Math.abs(lastWalk.t1 - b.at) <= 1;
  // the cut-out points to the LEFT; by default she points toward the middle of the screen (the app frame)
  const flip = b.flip ?? (b.pose === 'pointing' ? b.x < 960 : false);
  const dir = (b.pose === 'pointing' ? (flip ? 1 : -1) : flip ? -1 : 1) as 1 | -1;
  // idle: breathing + weight shift
  const br = Math.sin(f * 0.11);
  let sx = 1 - 0.004 * br, sy = 1 + 0.009 * br, rot = 0.5 * Math.sin(f * 0.05 + bi);
  let y = floor;
  // lean in (eases in over 10 frames)
  const leanP = prog(arrived, 0, 12, E.out);
  rot += (b.lean ?? 0) * leanP;
  // arrival: damped squash (landing) and optional hop
  if (cameWalking || b.hop) {
    const a = arrived;
    const sq = 0.075 * Math.exp(-a * 0.22) * Math.cos(a * 0.85);
    sy -= sq; sx += sq * 0.6;
  }
  if (b.hop) {
    const a = arrived;
    const air = a < 14 ? Math.sin(Math.PI * (a / 14)) : 0;
    y -= air * b.hop;
    sy += air * 0.05; sx -= air * 0.03;
  }
  // a turn on the spot when the pose changes without a walk: squeeze the width through the swap
  if (!cameWalking && b.pose !== prevPose && arrived < 10) sx *= 1 - 0.32 * Math.sin(Math.PI * (arrived / 10));
  // anticipation: a 6-frame crouch and lean back before she sets off
  if (next) {
    const ant = prog(f, next.t0 - 6, next.t0, E.out);
    const nd = Math.sign(next.x1 - next.x0) || 1;
    sy -= 0.07 * ant; sx += 0.05 * ant; rot -= nd * 5 * ant;
  }
  return { ...base, x: b.x, y, pose: b.pose, flip, dir, rot, sx, sy, since: arrived, beat: bi, sf: 0 };
}

const BubbleAt: React.FC<{ text: string; x: number; headY: number; lf: number; at: number; end: number }> = ({ text, x, headY, lf, at, end }) => {
  const p = pop(lf, at, FPS, 11, 220, 0.6) * (1 - prog(lf, end - 6, end, E.in));
  if (p <= 0.01) return null;
  const right = x > 960;
  const style: React.CSSProperties = right ? { right: clamp(1920 - (x + 70), 40, 1800) } : { left: clamp(x - 70, 40, 1380) };
  return (
    <div style={{ position: 'absolute', ...style, bottom: 1080 - headY + 22, maxWidth: 520, transform: `scale(${p})`, transformOrigin: right ? '90% 100%' : '10% 100%', zIndex: 34 }}>
      <div style={{ background: '#fff', color: '#0F1117', fontFamily: display, fontWeight: 700, fontSize: 36, lineHeight: 1.18, padding: '16px 26px', borderRadius: 26, boxShadow: '0 14px 36px rgba(0,0,0,.45)', position: 'relative' }}>
        {text}
        <div style={{ position: 'absolute', bottom: -18, [right ? 'right' : 'left']: 70, width: 0, height: 0, borderLeft: '18px solid transparent', borderRight: '18px solid transparent', borderTop: '22px solid #fff' }} />
      </div>
    </div>
  );
};

const Dust: React.FC<{ plan: Plan; f: number }> = ({ plan, f }) => (
  <>
    {plan.feet.filter((q) => f >= q.f && f < q.f + 16).map((q, i) => {
      const a = (f - q.f) / 16;
      return [0, 1].map((k) => (
        <div key={`${i}-${k}`} style={{ position: 'absolute', left: q.x - q.dir * (14 + a * 34 + k * 12) - 12, top: plan.floor - 18 - a * (14 + k * 8) - k * 4, width: 18 + a * 26, height: 18 + a * 26, borderRadius: '50%', background: 'rgba(255,255,255,0.5)', opacity: (1 - a) * (k ? 0.18 : 0.3), filter: 'blur(5px)', zIndex: 29 }} />
      ));
    })}
  </>
);

export type PropRenderer = (s: WalkState, plan: Plan) => React.ReactNode;

export const MeeraWalker: React.FC<WalkOpts & { prop?: PropRenderer; z?: number; plan?: Plan; extraRot?: (f: number) => number }> = ({ prop, z = 30, plan: given, extraRot, ...opts }) => {
  const f = useCurrentFrame();
  const plan = React.useMemo(() => given ?? planWalk(opts), [given]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = stateAt(plan, f);
  const bubbles = plan.beats.filter((b) => b.text);
  return (
    <>
      {s.visible ? (
        <>
          <div style={{ position: 'absolute', left: s.x - s.h * 0.27, top: s.floor - 12, width: s.h * 0.54 * (1 - 0.18 * s.bob), height: 24, borderRadius: '50%', background: 'rgba(0,0,0,0.5)', filter: 'blur(9px)', opacity: 0.85 - 0.3 * s.bob, zIndex: z - 2 }} />
          <Meera pose={s.pose} x={s.x} y={s.y} h={s.h} sx={s.sx} sy={s.sy} rot={s.rot + (extraRot && !s.walking ? extraRot(f) : 0)} flip={s.flip} shadow={false} z={z} />
          {prop ? prop(s, plan) : null}
        </>
      ) : null}
      <Dust plan={plan} f={f} />
      {bubbles.map((b, i) => {
        const at = b.textAt ?? b.at + 4, end = at + (b.textDur ?? 70);
        return s.visible && f >= at - 1 && f < end + 2 ? <BubbleAt key={i} text={b.text!} x={b.x} headY={plan.floor - plan.h} lf={f} at={at} end={end} /> : null;
      })}
    </>
  );
};
void body; void C;
