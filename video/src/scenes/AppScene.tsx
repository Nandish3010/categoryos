import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { VoCaptions } from '../components/Captions';
import { BigChip, Callout, Focus, HoursSaved, MeeraPop, ScreenView, Src, TiltFrame, vt } from '../components/AppParts';
import { Pose } from '../components/Meera';
import { body, C, display, E, prog, sceneOf } from '../theme';
import { IMPACT } from '../config';

export type Seg = {
  a: number; b: number; // fractions of the scene
  src: Src; mark: string; d?: number; // video start = mark + d seconds
  focus?: Focus; callouts?: Callout[]; rate?: number; play?: number; // seconds of footage to play, then hold the last frame
  big?: { text: string; sub?: string; color?: string; at?: number; y?: number; align?: 'left' | 'right' | 'center' };
  meera?: { pose: Pose; side: 'left' | 'right'; text?: string; at?: number; dur?: number; h?: number };
  tag?: string; // small label chip (montage)
  tagSub?: string; // second line under the tag, e.g. 'off your plate'
  note?: string; // provenance note, shown briefly
  whip?: boolean;
};

const Backdrop: React.FC<{ hue?: 'blue' | 'green' }> = ({ hue = 'blue' }) => (
  <AbsoluteFill style={{ background: hue === 'blue' ? 'radial-gradient(1300px 800px at 50% 35%, #1b2440 0%, #0F1117 62%)' : 'radial-gradient(1300px 800px at 50% 35%, #123222 0%, #0c1a14 62%)' }} />
);

const SegView: React.FC<{ s: Seg; frames: number }> = ({ s, frames }) => {
  const lf = useCurrentFrame();
  const wp = s.whip ? 1 - prog(lf, 0, 9, E.out) : 0;
  return (
    <div style={{ position: 'absolute', inset: 0, transform: `translateX(${wp * -240}px)`, filter: wp > 0.02 ? `blur(${wp * 14}px)` : undefined }}>
      <ScreenView src={s.src} from={vt(s.src, s.mark, s.d ?? 0)} lf={lf} frames={frames} focus={s.focus} callouts={s.callouts} rate={s.rate} playFrames={s.play !== undefined ? Math.round(s.play * 30) : undefined} />
    </div>
  );
};

const Overlay: React.FC<{ s: Seg; frames: number }> = ({ s, frames }) => {
  const lf = useCurrentFrame();
  return (
    <>
      {s.big ? <BigChip lf={lf} at={s.big.at ?? 30} end={frames - 4} text={s.big.text} sub={s.big.sub} color={s.big.color} y={s.big.y ?? 118} align={s.big.align} /> : null}
      {s.meera ? <MeeraPop pose={s.meera.pose} side={s.meera.side} lf={lf} at={s.meera.at ?? 14} end={Math.min(frames - 10, (s.meera.at ?? 14) + (s.meera.dur ?? 70))} text={s.meera.text} h={s.meera.h} /> : null}
      {s.tag ? <TagChip lf={lf} text={s.tag} sub={s.tagSub} /> : null}
      {s.note ? <NoteChip lf={lf} text={s.note} end={frames} /> : null}
    </>
  );
};

const TagChip: React.FC<{ lf: number; text: string; sub?: string }> = ({ lf, text, sub }) => {
  const p = prog(lf, 4, 16);
  return (
    <div style={{ position: 'absolute', left: 150, top: 44, zIndex: 36, opacity: p, transform: `translateY(${(1 - p) * -14}px)` }}>
      <div style={{ background: C.blue, color: '#0F1117', fontFamily: display, fontWeight: 700, fontSize: 40, padding: '8px 26px', borderRadius: 999, boxShadow: '0 10px 30px rgba(0,0,0,.4)' }}>{text}</div>
      {sub ? <div style={{ marginTop: 8, marginLeft: 6, display: 'inline-block', background: 'rgba(15,17,23,.9)', border: `2px solid ${C.green}`, color: C.green, fontFamily: body, fontWeight: 700, fontSize: 28, padding: '2px 16px', borderRadius: 999 }}>{sub}</div> : null}
    </div>
  );
};

const NoteChip: React.FC<{ lf: number; text: string; end: number }> = ({ lf, text, end }) => {
  const p = prog(lf, 4, 16) * (1 - prog(lf, end - 8, end));
  return (
    <div style={{ position: 'absolute', left: 150, top: 44, zIndex: 36, opacity: p }}>
      <div style={{ background: 'rgba(15,17,23,.9)', border: `2px solid ${C.green}`, color: C.text, fontFamily: body, fontWeight: 500, fontSize: 30, padding: '6px 22px', borderRadius: 999 }}>{text}</div>
    </div>
  );
};

export const AppScene: React.FC<{ sceneId: string; segs: Seg[]; hours: [number, number]; frameScale?: number; hue?: 'blue' | 'green'; showHours?: boolean }> = ({ sceneId, segs, hours, frameScale = 0.84, hue = 'blue', showHours = true }) => {
  const sc = sceneOf(sceneId);
  const f = useCurrentFrame();
  const max = (IMPACT.hours_saved_per_month as number) ?? 0;
  const p = hours[0] + (hours[1] - hours[0]) * E.inOut(f / sc.frames);
  return (
    <AbsoluteFill>
      <Backdrop hue={hue} />
      <TiltFrame lf={f} scale={frameScale} enter={0}>
        {segs.map((s, i) => {
          const from = Math.round(s.a * sc.frames), to = Math.round(s.b * sc.frames);
          return <Sequence key={i} from={from} durationInFrames={to - from}><SegView s={s} frames={to - from} /></Sequence>;
        })}
      </TiltFrame>
      {segs.map((s, i) => {
        const from = Math.round(s.a * sc.frames), to = Math.round(s.b * sc.frames);
        return <Sequence key={i} from={from} durationInFrames={to - from} layout="none"><Overlay s={s} frames={to - from} /></Sequence>;
      })}
      {showHours ? <HoursSaved p0={p} p1={p} max={max} /> : null}
      <VoCaptions sceneId={sceneId} accent={C.blue} bottom={52} />
    </AbsoluteFill>
  );
};

void body;
