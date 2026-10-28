import React from 'react';
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from 'remotion';
import { Meera, Pose } from '../components/Meera';
import { VoCaptions } from '../components/Captions';
import { body, C, display, E, FPS, H, MARGIN_X, pop, prog, rnd, sceneOf, T, W } from '../theme';
import script from '../../script.json';
import { act1Times, DASH_LEN, DASH_PRE, IDLE_POSE, XS } from '../act1Timing.js';
import { baselineHours, baselineTag, chaosCaption } from '../config';

const FLOOR = 880;
const MEERA_H = 480;
const sec = (s: number) => s * FPS;

type Wp = { f: number; x: number; pose: Pose; len: number };

function useTimes() {
  const a = sceneOf('a1-intro'), b = sceneOf('a1-mid'), c = sceneOf('a1-end');
  return { t: act1Times(T, script), a, b, c };
}

function waypoints(t: ReturnType<typeof act1Times>): Wp[] {
  const w: Wp[] = [];
  t.visits.forEach((v, i) => w.push({ f: sec(t.dashStart[i]), x: XS[v.st], pose: IDLE_POSE[v.st] as Pose, len: i === 0 ? 18 : DASH_LEN }));
  t.rainWps.forEach((r) => w.push({ f: sec(r.t), x: r.x, pose: r.pose as Pose, len: 16 }));
  return w;
}

type MS = { flip: boolean; x: number; pose: Pose; sx: number; sy: number; rot: number; hop: number; vx: number; blur: number; phase: string; dashT: number; landT: number; from: number };

function meeraState(f: number, wps: Wp[]): MS | null {
  let idx = -1;
  wps.forEach((w, i) => { if (f >= w.f) idx = i; });
  if (idx < 0) return null;
  const w = wps[idx];
  const from = idx === 0 ? -320 : wps[idx - 1].x;
  const pre = DASH_PRE;
  const lf = f - w.f;
  const flip = idx > 0 && w.x < from;
  const base: MS = { flip, x: from, pose: 'running', sx: 1, sy: 1, rot: 0, hop: 0, vx: 0, blur: 0, phase: 'pre', dashT: 0, landT: 0, from };
  if (lf < pre) {
    const u = E.out(lf / pre);
    // anticipation: crouch and lean back before the dash (slow-in)
    return { ...base, pose: idx === 0 ? 'running' : wps[idx - 1].pose, sx: 1 + 0.1 * u, sy: 1 - 0.13 * u, rot: -7 * u };
  }
  if (lf < pre + w.len) {
    const u = (lf - pre) / w.len;
    const e = E.inOut(u), e2 = E.inOut(Math.min(1, u + 1 / w.len));
    const vx = ((e2 - e) * (w.x - from));
    const sp = Math.min(1, Math.abs(vx) / 40);
    return { ...base, x: from + (w.x - from) * e, vx, pose: 'running', sx: 1.06 + 0.08 * sp, sy: 0.95 - 0.04 * sp, rot: 9 * sp - 1, hop: Math.abs(Math.sin(lf * 0.75)) * 20 * Math.sin(Math.PI * u) * 1.2, blur: sp * 3.2, phase: 'dash', dashT: u };
  }
  const lt = lf - pre - w.len;
  // landing: squash then damped overshoot (follow-through), rotation settles back to upright
  const damp = Math.exp(-lt * 0.22);
  const sq = 0.17 * damp * Math.cos(lt * 0.85);
  const idle = lt > 4 ? Math.sin(f * 0.33) * 0.012 : 0;
  return { ...base, x: w.x, pose: lt < 2 ? 'running' : w.pose, sx: 1 + sq * 0.7, sy: 1 - sq + idle, rot: 9 * damp * Math.cos(lt * 0.5) * 0.5, phase: 'land', landT: lt };
}

// ---- background pieces ----
const Dust: React.FC<{ f: number; at: number; x: number; dir: number }> = ({ f, at, x, dir }) => {
  const lt = f - at;
  if (lt < 0 || lt > 20) return null;
  return (
    <>
      {Array.from({ length: 7 }).map((_, i) => {
        const r = rnd(at * 7 + i);
        const u = lt / 20;
        const px = x + dir * (20 + r * 90) * E.out(u) + (r - 0.5) * 30;
        const py = FLOOR - 10 - (20 + r * 50) * E.out(u);
        const size = (14 + r * 22) * (0.6 + u);
        return <div key={i} style={{ position: 'absolute', left: px - size / 2, top: py - size / 2, width: size, height: size, borderRadius: '50%', background: 'rgba(245,200,170,0.55)', opacity: (1 - u) * 0.7, filter: 'blur(3px)', zIndex: 4 }} />;
      })}
    </>
  );
};

const SpeedLines: React.FC<{ x: number; u: number; vx: number }> = ({ x, u, vx }) => {
  const dir = Math.sign(vx) || 1;
  const a = Math.sin(Math.PI * u);
  return (
    <>
      {Array.from({ length: 9 }).map((_, i) => {
        const r = rnd(i * 3.3);
        const len = (160 + r * 260) * a;
        return <div key={i} style={{ position: 'absolute', left: dir > 0 ? x - 200 - len : x + 200, top: FLOOR - 120 - r * 400, width: len, height: 4 + (i % 3), background: `linear-gradient(${dir > 0 ? 90 : 270}deg, transparent, rgba(255,255,255,0.75))`, borderRadius: 4, opacity: a, zIndex: 3 }} />;
      })}
    </>
  );
};

const NOTE_COLORS = [C.yellow, C.orange, '#F9A8D4', C.blue, '#86EFAC', '#FDE68A', '#EDEEF2'];
const Notes: React.FC<{ f: number; start: number; end: number; front: boolean }> = ({ f, start, end, front }) => {
  const N = 110;
  return (
    <>
      {Array.from({ length: N }).map((_, i) => {
        const r = rnd(i + 1), r2 = rnd(i * 2.7 + 9);
        // later notes fall more often (accelerating chaos)
        const k = Math.pow(i / N, 0.75);
        const t0 = start + k * (end - start);
        const fall = 22 + r2 * 10;
        const u = (f - t0) / fall;
        if (u < 0) return null;
        const x = 110 + r * 1700;
        const mound = 190 * Math.exp(-Math.pow((x - 960) / 330, 2)) * r2;
        const landY = FLOOR - 20 - r2 * 70 - mound * k;
        const y = interpolate(Math.min(1, u), [0, 1], [-120, landY], { easing: E.in });
        const rot = (r - 0.5) * 70 + (u < 1 ? u * 240 * (r2 - 0.5) : 0);
        const isFront = i % 3 === 0;
        if (isFront !== front) return null;
        const size = 62 + r2 * 34;
        return <div key={i} style={{ position: 'absolute', left: x - size / 2, top: y - size / 2, width: size, height: size, background: NOTE_COLORS[i % NOTE_COLORS.length], transform: `rotate(${rot}deg)`, borderRadius: 3, boxShadow: '0 6px 12px rgba(0,0,0,.35)', zIndex: front ? 9 : 2 }} />;
      })}
    </>
  );
};

// ---- stations ----
const CARD_W = 310, CARD_H = 300, CARD_Y = 215;
const Card: React.FC<{ i: number; f: number; at: number; color: string; title: string; children: React.ReactNode; shake?: number }> = ({ i, f, at, color, title, children, shake = 0 }) => {
  if (f < at) return null;
  const s = pop(f, at, FPS, 10, 190, 0.7);
  const lf = f - at;
  return (
    <div style={{ position: 'absolute', left: XS[i] - CARD_W / 2, top: CARD_Y, width: CARD_W, height: CARD_H, transform: `scale(${0.3 + 0.7 * s}) rotate(${(1 - s) * (i % 2 ? 8 : -8) + Math.sin(lf * 1.7) * shake}deg)`, opacity: Math.min(1, lf / 4), transformOrigin: '50% 100%', background: 'linear-gradient(180deg,#2a1a18,#1d1413)', border: `4px solid ${color}`, borderRadius: 22, boxShadow: `0 0 40px ${color}55, 0 18px 40px rgba(0,0,0,.5)`, padding: '18px 20px', fontFamily: body, color: C.text, overflow: 'hidden', zIndex: 3 }}>
      <div style={{ fontFamily: display, fontWeight: 700, fontSize: 32, color, marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
};

const Inbox: React.FC<{ f: number; at: number; full: number }> = ({ f, at, full }) => {
  const n = Math.round(47 * Math.pow(prog(f, at + 6, full, E.in), 1.6)); // racing: accelerates to 47 right as she says it
  const done = f > full;
  const flash = done ? 1 + 0.06 * Math.sin((f - at) * 0.6) : 1;
  return (
    <Card i={0} f={f} at={at} color={C.red} title="Inbox">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <svg width="84" height="64" viewBox="0 0 84 64"><rect x="2" y="6" width="80" height="52" rx="8" fill="#F1F2F6" /><path d="M4 12 L42 38 L80 12" stroke="#B4B9C6" strokeWidth="4" fill="none" /></svg>
        <div style={{ background: C.red, borderRadius: 40, padding: '2px 22px', fontFamily: display, fontWeight: 700, fontSize: 84, lineHeight: 1.1, color: '#fff', transform: `scale(${flash})`, minWidth: 110, textAlign: 'center' }}>{n}</div>
      </div>
      <div style={{ fontSize: 30, marginTop: 16, color: C.dim }}>unread</div>
    </Card>
  );
};

const Sheet: React.FC<{ f: number; at: number }> = ({ f, at }) => {
  const cells = ['Rs.399/-', 'tbc', '', 'Rs.399/-', 'see mail', '??'];
  return (
    <Card i={1} f={f} at={at} color={C.orange} title="Vendor sheet">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {cells.map((c, i) => {
          const p = prog(f, at + 6 + i * 3, at + 14 + i * 3);
          return <div key={i} style={{ height: 62, background: c ? '#F4ECE6' : '#5a2b27', color: '#2a1a18', fontWeight: 700, fontSize: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, opacity: p, border: c ? 'none' : `3px dashed ${C.red}`, transform: `scale(${0.6 + 0.4 * p})` }}>{c || <span style={{ color: C.red, fontSize: 28 }}>blank</span>}</div>;
        })}
      </div>
    </Card>
  );
};

const Phone: React.FC<{ f: number; at: number }> = ({ f, at }) => (
  <Card i={2} f={f} at={at} color={C.yellow} title="Vendor calling" shake={f - at < 60 ? 5 : 1.5}>
    <div style={{ fontSize: 32, fontWeight: 700, lineHeight: 1.18 }}>
      "+20% marketing if you sell 2,000 units!"
    </div>
    <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
      {[0, 1, 2].map((i) => <div key={i} style={{ width: 18, height: 18, borderRadius: 9, background: C.yellow, opacity: 0.35 + 0.65 * Math.abs(Math.sin((f - at) * 0.4 - i * 0.7)) }} />)}
    </div>
  </Card>
);

const Licences: React.FC<{ f: number; at: number }> = ({ f, at }) => (
  <Card i={3} f={f} at={at} color={C.blue} title="Licence scans">
    <div style={{ position: 'relative', height: 200 }}>
      {['FSSAI', 'GST', 'PAN'].map((t, i) => {
        const p = pop(f, at + 4 + i * 5);
        return (
          <div key={t} style={{ position: 'absolute', left: 10 + i * 24, top: 6 + i * 26, width: 210, height: 120, background: '#F4F1EA', borderRadius: 8, transform: `rotate(${(i - 1) * 7}deg) scale(${p})`, boxShadow: '0 6px 14px rgba(0,0,0,.4)', color: '#2a2a33', fontFamily: display, fontWeight: 700, fontSize: 32, padding: 12 }}>
            {t}
            <div style={{ height: 8, background: '#C9C4B8', borderRadius: 4, marginTop: 8, width: '80%' }} />
            <div style={{ height: 8, background: '#C9C4B8', borderRadius: 4, marginTop: 8, width: '55%' }} />
          </div>
        );
      })}
    </div>
  </Card>
);

const Alert: React.FC<{ f: number; at: number }> = ({ f, at }) => {
  const blink = Math.sin((f - at) * 0.55) > 0;
  return (
    <Card i={4} f={f} at={at} color={C.red} title="Competitor">
      <div style={{ background: blink ? C.red : '#7a2a2a', borderRadius: 14, padding: '16px 14px', textAlign: 'center', transition: 'none' }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 40, color: '#fff' }}>price drop</div>
        <div style={{ fontSize: 80, lineHeight: 1, color: '#fff' }}>{'▼'}</div>
      </div>
      <div style={{ fontSize: 30, marginTop: 14, color: C.text, fontWeight: 700 }}>Match it? Now?</div>
    </Card>
  );
};

// ---- HUD ----
const Clock: React.FC<{ f: number; big: number; endF: number }> = ({ f, big, endF }) => {
  const spin = f * 14; // spinning minute hand
  const dia = 150 + big * 330;
  const left = MARGIN_X + big * (W / 2 - MARGIN_X - dia / 2);
  const top = 30 + big * 220;
  const mins = 9 * 60 + Math.floor(prog(f, 30, endF, (x) => x * x * 0.5 + x * 0.5) * 12 * 60);
  const h12 = Math.floor(mins / 60) % 12 || 12, mm = mins % 60;
  const label = `${h12}:${String(mm).padStart(2, '0')} ${mins >= 12 * 60 && mins < 24 * 60 ? 'PM' : 'AM'}`;
  return (
    <div style={{ position: 'absolute', left, top, zIndex: 20, display: 'flex', alignItems: 'center', gap: 20, flexDirection: big > 0.5 ? 'column' : 'row' }}>
      <svg width={dia} height={dia} viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="47" fill="#F1F2F6" stroke={C.red} strokeWidth="5" />
        {Array.from({ length: 12 }).map((_, i) => <line key={i} x1="50" y1="9" x2="50" y2={i % 3 === 0 ? 17 : 13} stroke="#333" strokeWidth="2" transform={`rotate(${i * 30} 50 50)`} />)}
        <line x1="50" y1="50" x2="50" y2="22" stroke="#222" strokeWidth="4.5" strokeLinecap="round" transform={`rotate(${spin / 12} 50 50)`} />
        <line x1="50" y1="50" x2="50" y2="12" stroke={C.red} strokeWidth="3" strokeLinecap="round" transform={`rotate(${spin} 50 50)`} />
        <circle cx="50" cy="50" r="4" fill="#222" />
      </svg>
      <div style={{ fontFamily: display, fontWeight: 700, fontSize: 52 + big * 70, color: C.text, textShadow: '0 4px 20px rgba(0,0,0,.6)' }}>{label}</div>
    </div>
  );
};

const TimeSpent: React.FC<{ f: number; endF: number }> = ({ f, endF }) => {
  const h = interpolate(f, [sec(2.5), endF], [0, baselineHours], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: E.inOut });
  const vis = prog(f, sec(2.2), sec(3));
  return (
    <div style={{ position: 'absolute', right: MARGIN_X, top: 36, textAlign: 'right', opacity: vis, zIndex: 20 }}>
      <div style={{ fontFamily: body, fontWeight: 500, fontSize: 30, color: C.dim }}>time spent ({baselineTag})</div>
      <div style={{ fontFamily: display, fontWeight: 700, fontSize: 84, lineHeight: 1, color: C.orange }}>{h.toFixed(1)} h</div>
    </div>
  );
};

// ---- Act 1 ----
export const Act1Visual: React.FC<{ f: number }> = ({ f }) => {
  const { t } = useTimes();
  const wps = React.useMemo(() => waypoints(t), [t]);
  const ms = meeraState(f, wps);
  const bigClock = 1 - prog(f, 34, 58, E.inOut);
  const stF = t.stations.map(sec);
  const buriedF = sec(t.buried);
  const frozen = f > sec(t.freeze);
  const alertPulse = f > stF[4] ? 0.12 * (0.5 + 0.5 * Math.sin(f * 0.5)) : 0;
  const rainEnd = sec(t.M);
  // Camera: slow push-in with a tiny follow of Meera; punches on each station pop
  const punch = stF.reduce((n, s) => n + (f >= s ? Math.max(0, 0.05 * Math.exp(-(f - s) * 0.18)) : 0), 0);
  const zoomEnd = prog(f, buriedF, buriedF + 20) * 0.04;
  const cam = 1 + punch + zoomEnd + f * 0.00004;
  const camX = ms ? (W / 2 - ms.x) * 0.06 : 0;
  const endF = sec(t.end);
  const dashing = ms?.phase === 'dash';

  return (
    <AbsoluteFill style={{ background: 'radial-gradient(1200px 800px at 50% 40%, #2c1613 0%, #1a0f0c 55%, #0d0706 100%)', overflow: 'hidden', fontFamily: body }}>
      <div style={{ position: 'absolute', inset: 0, transform: `translateX(${camX}px) scale(${cam})`, transformOrigin: '50% 70%' }}>
        <div style={{ position: 'absolute', left: 0, right: 0, top: FLOOR - 12, height: 90, background: 'linear-gradient(180deg,#3a211c,#1a0f0c)' }} />
        <div style={{ opacity: 1 - 0.92 * prog(f, sec(t.freeze), sec(t.freeze) + 12) }}>
        <Inbox f={f} at={stF[0]} full={sec(t.inboxFull)} />
        <Sheet f={f} at={stF[1]} />
        <Phone f={f} at={stF[2]} />
        <Licences f={f} at={stF[3]} />
        <Alert f={f} at={stF[4]} />
        </div>
        <Notes f={f} start={sec(t.notesStart)} end={rainEnd + 20} front={false} />
        {ms && f < buriedF + 4 ? (
          <>
            {dashing ? (
              <>
                {[2, 1].map((k) => <Meera key={k} pose="running" flip={ms.flip} x={ms.x - ms.vx * k * 1.6} y={FLOOR - ms.hop} h={MEERA_H} sx={ms.sx} sy={ms.sy} rot={ms.rot} opacity={0.22 / k} blur={3 * k} shadow={false} z={4} />)}
                <SpeedLines x={ms.x} u={ms.dashT} vx={ms.vx} />
              </>
            ) : null}
            <Meera pose={ms.pose} flip={ms.flip && ms.pose === 'running'} x={ms.x} y={FLOOR - ms.hop} h={MEERA_H} sx={ms.sx} sy={ms.sy} rot={ms.rot} blur={ms.blur} />
          </>
        ) : null}
        {wps.map((w, i) => {
          const d = i === 0 ? -320 : wps[i - 1].x;
          const dir = Math.sign(w.x - d) || 1;
          return (
            <React.Fragment key={i}>
              <Dust f={f} at={w.f + DASH_PRE} x={d} dir={-dir} />
              <Dust f={f} at={w.f + DASH_PRE + w.len} x={w.x} dir={-dir} />
            </React.Fragment>
          );
        })}
        {f >= buriedF ? <BuriedBeat f={f} at={buriedF} frozen={frozen} /> : null}
        <Notes f={f} start={sec(t.notesStart)} end={rainEnd + 20} front />
      </div>
      <div style={{ position: 'absolute', inset: 0, background: `rgba(248,113,113,${alertPulse})`, pointerEvents: 'none', zIndex: 15 }} />
      <div style={{ position: 'absolute', inset: 0, boxShadow: 'inset 0 0 280px rgba(0,0,0,.75)', zIndex: 16, pointerEvents: 'none' }} />
      <Clock f={f} big={bigClock} endF={endF} />
      <TimeSpent f={f} endF={endF - sec(1.5)} />
      {f >= sec(t.freeze) ? <ChaosCard f={f - sec(t.freeze)} /> : null}
      {f < sec(0.35) ? <div style={{ position: 'absolute', inset: 0, background: '#fff', opacity: 1 - f / sec(0.35), zIndex: 30 }} /> : null}
    </AbsoluteFill>
  );
};

const BuriedBeat: React.FC<{ f: number; at: number; frozen: boolean }> = ({ f, at, frozen }) => {
  const lf = f - at;
  const s = pop(f, at, FPS, 9, 140, 0.9);
  const y = FLOOR + 10;
  const sq = frozen ? 0 : 0.05 * Math.exp(-lf * 0.15) * Math.cos(lf * 0.9);
  return (
    <>
      <Meera pose="buried" x={1380} y={y} h={620 * (0.55 + 0.45 * s)} sy={1 - sq} sx={1 + sq} shadow={false} z={7} />
      {Array.from({ length: 26 }).map((_, i) => {
        const r = rnd(i + 40), r2 = rnd(i * 1.9 + 2);
        const u = Math.min(1, lf / 34);
        const ang = (i / 26) * Math.PI * 2;
        const dist = (160 + r * 420) * E.out(u);
        const x = 1380 + Math.cos(ang) * dist, yy = y - 280 + Math.sin(ang) * dist * 0.7 + 300 * u * u;
        return <div key={i} style={{ position: 'absolute', left: x, top: yy, width: 44 + r2 * 30, height: 44 + r2 * 30, background: NOTE_COLORS[i % NOTE_COLORS.length], transform: `rotate(${u * 360 * (r2 - 0.5) * 2}deg)`, opacity: 1 - u * 0.6, borderRadius: 3, zIndex: 8 }} />;
      })}
    </>
  );
};

const ChaosCard: React.FC<{ f: number }> = ({ f }) => {
  const p = pop(f, 0, FPS, 14, 150, 0.8);
  const tag = prog(f, 14, 26);
  return (
    <div style={{ position: 'absolute', left: MARGIN_X, top: 260, zIndex: 25, transform: `translateX(${(1 - p) * -120}px)`, opacity: Math.min(1, p * 1.5) }}>
      <div style={{ fontFamily: display, fontWeight: 700, fontSize: 124, lineHeight: 1.02, color: C.text, textShadow: '0 8px 30px rgba(0,0,0,.6)', maxWidth: 900 }}>{chaosCaption}</div>
      <div style={{ marginTop: 22, display: 'inline-block', background: C.orange, color: '#1a0f0c', fontFamily: body, fontWeight: 700, fontSize: 34, padding: '8px 22px', borderRadius: 999, opacity: tag, transform: `translateY(${(1 - tag) * 14}px)` }}>{baselineTag}</div>
    </div>
  );
};

/** Act 1 is one continuous piece spanning 3 VO scenes; captions are laid on per scene. */
export const Act1: React.FC = () => {
  const f = useCurrentFrame();
  const a = sceneOf('a1-intro'), b = sceneOf('a1-mid'), c = sceneOf('a1-end');
  return (
    <AbsoluteFill>
      <Act1Visual f={f} />
      {[a, b, c].map((s) => (
        <Sequence key={s.id} from={s.start - a.start} durationInFrames={s.frames} layout="none">
          <VoCaptions sceneId={s.id} accent={C.orange} bottom={56} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
