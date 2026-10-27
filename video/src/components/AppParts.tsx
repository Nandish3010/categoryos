import React from 'react';
import { Freeze, OffthreadVideo, staticFile } from 'remotion';
import { body, C, display, E, FPS, pop, prog } from '../theme';
import { Meera, Pose } from './Meera';
import v1m from '../../captures/v1.json';
import v1lm from '../../captures/v1label.json';
import v2m from '../../captures/v2.json';
import mm from '../../captures/montage.json';
import im from '../../captures/impact.json';

export const MARKS = { v1: v1m, v1label: v1lm, v2: v2m, montage: mm, impact: im } as unknown as Record<string, Record<string, number>>;
export type Src = 'v1' | 'v1label' | 'v2' | 'montage' | 'impact';

/** Video-time (seconds) of a recorded mark + delta. */
export function vt(src: Src, mark: string, d = 0): number {
  const m = MARKS[src];
  return Math.max(0, (m[mark] - (m._videoOffsetMs ?? 0)) / 1000 + d);
}

export type Focus = { x: number; y: number; w: number; h: number };
export type Callout = { x: number; y: number; w: number; h: number; color?: string };

export const zoomFor = (f: Focus) => Math.min(2.8, (1920 * 0.94) / f.w, (1080 * 0.94) / f.h);

/** The recorded screen, with a zoom-to-focus camera and pulsing highlight rings drawn in video space. */
export const ScreenView: React.FC<{
  src: Src; from: number; lf: number; frames: number; focus?: Focus; callouts?: Callout[]; zoomIn?: number; rate?: number; zoom?: number; holdZoom?: boolean; playFrames?: number;
}> = ({ src, from, lf, frames, focus, callouts = [], zoomIn = 2, rate = 1, zoom, holdZoom = false, playFrames }) => {
  const zin = prog(lf, zoomIn, zoomIn + 16, E.inOut);
  const zout = holdZoom ? 0 : prog(lf, frames - 14, frames - 2, E.inOut);
  const k = focus ? zin * (1 - zout) : 0;
  const Z = focus ? zoom ?? zoomFor(focus) : 1;
  const s = 1 + (Z - 1) * k;
  const tx = focus ? k * (960 - (focus.x + focus.w / 2) * Z) : 0;
  const ty = focus ? k * (540 - (focus.y + focus.h / 2) * Z) : 0;
  return (
    <div style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, transformOrigin: '0 0', transform: `translate(${tx}px,${ty}px) scale(${s})` }}>
      <Freeze frame={playFrames ?? 1e9} active={playFrames !== undefined && lf >= playFrames}>
        <OffthreadVideo src={staticFile(`captures/${src}.mp4`)} startFrom={Math.round(from * FPS)} playbackRate={rate} muted style={{ width: 1920, height: 1080 }} />
      </Freeze>
      {callouts.map((c, i) => {
        const a = 16 + i * 8;
        const p = pop(lf, a, FPS, 12, 200, 0.6);
        const pulse = 1 + 0.015 * Math.sin((lf - a) * 0.25);
        const col = c.color ?? C.yellow;
        return (
          <div key={i} style={{ position: 'absolute', left: c.x - 8, top: c.y - 8, width: c.w + 16, height: c.h + 16, border: `${Math.max(5, 5 / s)}px solid ${col}`, borderRadius: 14, boxShadow: `0 0 ${30 / s}px ${col}aa, inset 0 0 ${20 / s}px ${col}33`, transform: `scale(${(1.35 - 0.35 * p) * pulse})`, opacity: Math.min(1, p * 1.4) }} />
        );
      })}
    </div>
  );
};

/** Slightly 3D-tilted browser window. Children are laid out in a 1920x1080 space scaled to fit. */
export const TiltFrame: React.FC<{ lf: number; children: React.ReactNode; scale?: number; url?: string; enter?: number; tilt?: number; x?: number; y?: number }> = ({ lf, children, scale = 0.84, url = 'categoryos.vercel.app', enter = 0, tilt = 1, x = 960, y = 500 }) => {
  const w = 1920 * scale, h = 1080 * scale, bar = 46;
  const p = pop(lf, enter, FPS, 14, 120, 0.9);
  const ry = (-5 + Math.sin(lf * 0.02) * 1.2) * tilt, rx = 2.2 * tilt;
  return (
    <div style={{ position: 'absolute', inset: 0, perspective: 2600, perspectiveOrigin: '50% 45%' }}>
      <div style={{ position: 'absolute', left: x - w / 2, top: y - (h + bar) / 2, width: w, height: h + bar, borderRadius: 18, overflow: 'hidden', background: '#0a0a0a', border: '2px solid #2b3040', boxShadow: '0 40px 90px rgba(0,0,0,.65), 0 0 120px rgba(110,168,254,.18)', transform: `rotateY(${ry}deg) rotateX(${rx}deg) scale(${0.9 + 0.1 * p})`, opacity: Math.min(1, p * 2) }}>
        <div style={{ height: bar, background: '#171A23', display: 'flex', alignItems: 'center', gap: 10, padding: '0 18px' }}>
          {['#F87171', '#F5C542', '#4ADE80'].map((c) => <div key={c} style={{ width: 14, height: 14, borderRadius: 7, background: c }} />)}
          <div style={{ marginLeft: 18, background: '#0F1117', borderRadius: 9, padding: '4px 18px', fontFamily: body, fontSize: 28, color: C.dim }}>{url}</div>
        </div>
        <div style={{ position: 'relative', width: w, height: h, overflow: 'hidden' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, transformOrigin: '0 0', transform: `scale(${scale})` }}>{children}</div>
        </div>
      </div>
    </div>
  );
};

export const Bubble: React.FC<{ text: string; x: number; y: number; side: 'left' | 'right'; lf: number; at: number; end: number }> = ({ text, x, y, side, lf, at, end }) => {
  const p = pop(lf, at, FPS, 11, 220, 0.6) * (1 - prog(lf, end - 6, end, E.in));
  if (p <= 0.01) return null;
  return (
    <div style={{ position: 'absolute', left: side === 'right' ? undefined : x, right: side === 'right' ? 1920 - x : undefined, top: y, maxWidth: 520, transform: `scale(${p})`, transformOrigin: side === 'right' ? '90% 100%' : '10% 100%', zIndex: 40 }}>
      <div style={{ background: '#fff', color: '#0F1117', fontFamily: display, fontWeight: 700, fontSize: 36, lineHeight: 1.18, padding: '18px 26px', borderRadius: 26, boxShadow: '0 14px 36px rgba(0,0,0,.45)', position: 'relative' }}>
        {text}
        <div style={{ position: 'absolute', bottom: -18, [side === 'right' ? 'right' : 'left']: 70, width: 0, height: 0, borderLeft: '18px solid transparent', borderRight: '18px solid transparent', borderTop: '22px solid #fff' }} />
      </div>
    </div>
  );
};

/** Meera pops in from the screen edge, holds, then slips back out. */
export const MeeraPop: React.FC<{ pose: Pose; side: 'left' | 'right'; lf: number; at: number; end: number; text?: string; h?: number }> = ({ pose, side, lf, at, end, text, h = 520 }) => {
  if (lf < at || lf > end + 14) return null;
  const inP = pop(lf, at, FPS, 10, 150, 0.8);
  const out = prog(lf, end, end + 12, E.in);
  const dir = side === 'right' ? 1 : -1;
  const restX = side === 'right' ? 1760 : 160;
  const x = restX + dir * (1 - inP) * 360 + dir * out * 380;
  const squash = 0.06 * Math.exp(-(lf - at) * 0.2) * Math.cos((lf - at) * 0.8);
  const bob = Math.sin(lf * 0.2) * 0.008;
  return (
    <>
      <Meera pose={pose} x={x} y={1048} h={h} sx={1 + squash} sy={1 - squash + bob} rot={dir * (1 - inP) * -10} flip={side === 'right' && pose === 'pointing'} z={30} shadow={false} />
      {text ? <Bubble text={text} x={side === 'right' ? 1760 : 60} y={1048 - h - 150} side={side} lf={lf} at={at + 8} end={end} /> : null}
    </>
  );
};

export const BigChip: React.FC<{ lf: number; at: number; end: number; text: string; sub?: string; color?: string; x?: number; y?: number; align?: 'left' | 'right' | 'center' }> = ({ lf, at, end, text, sub, color = C.yellow, x = 96, y = 120, align = 'left' }) => {
  const p = pop(lf, at, FPS, 13, 170, 0.75) * (1 - prog(lf, end - 6, end, E.in));
  if (p <= 0.01) return null;
  return (
    <div style={{ position: 'absolute', left: align === 'right' ? undefined : align === 'center' ? 0 : x, right: align === 'right' ? 96 : align === 'center' ? 0 : undefined, top: y, display: 'flex', justifyContent: align === 'center' ? 'center' : 'flex-start', zIndex: 35, transform: `translateY(${(1 - p) * 30}px) scale(${0.9 + 0.1 * p})`, opacity: Math.min(1, p * 1.5) }}>
      <div style={{ background: 'rgba(15,17,23,0.92)', border: `3px solid ${color}`, borderRadius: 20, padding: '14px 30px 16px', boxShadow: `0 0 50px ${color}55, 0 16px 40px rgba(0,0,0,.5)` }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 84, lineHeight: 1.04, color }}>{text}</div>
        {sub ? <div style={{ fontFamily: body, fontWeight: 500, fontSize: 34, color: C.text, marginTop: 6 }}>{sub}</div> : null}
      </div>
    </div>
  );
};

/** Persistent corner counter during Act 2: modelled team hours back per month (value read from GET /api/impact). */
export const HoursSaved: React.FC<{ p0: number; p1: number; max: number }> = ({ p0, p1, max }) => {
  const v = max * (p0 + (p1 - p0) * 1);
  return (
    <div style={{ position: 'absolute', right: 40, top: 22, zIndex: 45, textAlign: 'right', background: 'rgba(15,17,23,.78)', border: `2px solid ${C.green}66`, borderRadius: 16, padding: '8px 20px' }}>
      <div style={{ fontFamily: body, fontWeight: 500, fontSize: 28, color: C.dim }}>hours back / month (modelled)</div>
      <div style={{ fontFamily: display, fontWeight: 700, fontSize: 58, lineHeight: 1, color: C.green }}>{v.toFixed(0)} h</div>
    </div>
  );
};
