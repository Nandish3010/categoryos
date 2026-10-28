import React from 'react';
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from 'remotion';
import { Meera } from '../components/Meera';
import { OFF_R } from '../components/MeeraWalker';
import { ScreenView, TiltFrame, vt } from '../components/AppParts';
import { VoCaptions } from '../components/Captions';
import { body, C, display, E, FPS, pop, prog, rnd, sceneOf, T } from '../theme';
import script from '../../script.json';
import { slamLocalFrame } from '../voTime.js';

const NOTE = [C.yellow, C.orange, '#F9A8D4', C.blue, '#86EFAC', '#EDEEF2'];
const FLOOR = 880;

/** Meera bursts out of the pile, slams the big glowing button, and we zoom through it into the real app. */
export const Slam: React.FC = () => {
  const lf = useCurrentFrame();
  const sc = sceneOf('a2-slam');
  const SLAM = slamLocalFrame(T, script); // the button goes down as she says the name
  const cool = prog(lf, SLAM + 2, SLAM + 22, E.inOut); // warm -> cool grade change
  // the paperwork bursts as she leaps off
  const burst = prog(lf, 10, 40, E.out);
  // she has just walked off to the right at the end of the team scene: she dashes back in from that edge (2110 -> 1380), then jumps
  const dash = prog(lf, 0, 12, E.out);
  const dashX = OFF_R + (1380 - OFF_R) * dash;
  const dashBob = Math.abs(Math.sin(dash * Math.PI * 3)) * 22 * (1 - dash);
  // jump arc from the dash end (x=1380) to beside the button (x=470)
  const jump = prog(lf, 12, 42, E.inOut);
  const mx = 1380 + (470 - 1380) * jump;
  const my = FLOOR - Math.sin(Math.PI * jump) * 260;
  const landSq = lf > 42 ? 0.14 * Math.exp(-(lf - 42) * 0.2) * Math.cos((lf - 42) * 0.8) : 0;
  const stretch = jump > 0 && jump < 1 ? 0.09 * Math.sin(Math.PI * jump) : 0;
  // pre-slam: arm-raise anticipation via lean back, then lunge forward
  const lean = lf < SLAM - 12 ? 0 : lf < SLAM ? -8 * E.out((lf - (SLAM - 12)) / 12) : 12 * Math.exp(-(lf - SLAM) * 0.25);
  const btn = pop(lf, 26, FPS, 11, 200, 0.7);
  const press = lf >= SLAM ? 0.13 * Math.exp(-(lf - SLAM) * 0.3) : 0;
  const glow = 0.6 + 0.4 * Math.sin(lf * 0.3);
  const ring = prog(lf, SLAM, SLAM + 26, E.out);
  const flash = lf >= SLAM && lf < SLAM + 10 ? 1 - (lf - SLAM) / 10 : 0;
  // zoom-through into the app
  const zt = prog(lf, SLAM + 4, SLAM + 40, E.inOut);
  const scale = 0.06 + 0.94 * zt;
  const gone = zt >= 1;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${mix('#2c1613', '#1b2440', cool)}, ${mix('#0d0706', '#0F1117', cool)})`, overflow: 'hidden' }}>
      {!gone ? (
        <AbsoluteFill style={{ opacity: 1 - prog(lf, SLAM + 14, SLAM + 36), transform: `scale(${1 + zt * 1.6})`, transformOrigin: '61% 52%', filter: zt > 0.05 ? `blur(${zt * 10}px)` : undefined }}>
          <div style={{ position: 'absolute', left: 0, right: 0, top: FLOOR - 12, height: 90, background: 'linear-gradient(180deg,#3a211c,#1a0f0c)' }} />
          {/* the pile we came from */}
          {lf < 40 ? <Pile lf={lf} /> : null}
          {/* shockwave */}
          <div style={{ position: 'absolute', left: 1180 - 520 * ring, top: 560 - 520 * ring, width: 1040 * ring, height: 1040 * ring, borderRadius: '50%', border: `${14 * (1 - ring)}px solid ${C.blue}`, opacity: ring > 0 && ring < 1 ? 1 : 0 }} />
          {/* the glowing button */}
          <div style={{ position: 'absolute', left: 1180 - 270, top: 560 - 85 + press * 40, width: 540, height: 170 * (1 - press), transform: `scale(${btn})`, borderRadius: 34, background: `linear-gradient(180deg, ${C.blue}, #3b6fd1)`, boxShadow: `0 ${14 - press * 80}px 0 #2a4f99, 0 0 ${80 * glow}px ${C.blue}, 0 0 ${200 * glow}px ${C.blue}66`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: display, fontWeight: 700, fontSize: 64, color: '#0F1117' }}>
            Run CategoryOS
          </div>
          {lf < 12 ? (
            <Meera pose="running" flip x={dashX} y={FLOOR - dashBob} h={520} rot={-8 * (1 - dash)} sy={1 + 0.04 * (1 - dash)} />
          ) : lf < 42 ? (
            <Meera pose="celebrating" x={mx} y={my} h={520} sx={1 - stretch * 0.5 + landSq * 0.6} sy={1 + stretch - landSq} rot={lean} shadow={lf > 40} />
          ) : (
            <Meera pose="pointing" x={mx} y={FLOOR} h={520} sx={1 + landSq * 0.6} sy={1 - landSq} rot={lean} />
          )}
        </AbsoluteFill>
      ) : null}
      {zt > 0 ? (
        <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: '61% 52%', opacity: Math.min(1, zt * 2.2), filter: zt < 0.95 ? `blur(${(1 - zt) * 8}px)` : undefined }}>
          <TiltFrame lf={lf - SLAM} enter={0} tilt={1 + (1 - zt) * 3}>
            <ScreenView src="v1" from={vt('v1', 'decided', 0.5)} lf={lf - SLAM} frames={sc.frames - SLAM} focus={{ x: 480, y: 250, w: 880, h: 260 }} zoomIn={36} />
          </TiltFrame>
        </AbsoluteFill>
      ) : null}
      <div style={{ position: 'absolute', inset: 0, background: '#fff', opacity: flash * 0.85, zIndex: 50 }} />
      <Sequence from={0} layout="none"><VoCaptions sceneId="a2-slam" accent={C.blue} bottom={52} /></Sequence>
    </AbsoluteFill>
  );
};

const Pile: React.FC<{ lf: number }> = ({ lf }) => {
  const u = prog(lf, 10, 40, E.out);
  return (
    <>
      {Array.from({ length: 40 }).map((_, i) => {
        const r = rnd(i + 5), r2 = rnd(i * 1.7 + 3);
        const ang = (i / 40) * Math.PI * 2;
        const d = (120 + r * 520) * u;
        return <div key={i} style={{ position: 'absolute', left: 1380 + Math.cos(ang) * d, top: 640 + Math.sin(ang) * d * 0.8 + 260 * u * u, width: 50 + r2 * 40, height: 50 + r2 * 40, background: NOTE[i % NOTE.length], transform: `rotate(${u * 540 * (r2 - 0.5)}deg)`, opacity: 1 - u * 0.8, borderRadius: 3 }} />;
      })}
    </>
  );
};

const mix = (a: string, b: string, t: number) => {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(interpolate(t, [0, 1], [v, pb[i]]))).join(',')})`;
};
