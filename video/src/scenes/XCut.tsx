import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { Act1Visual } from './Act1';
import { Meera } from '../components/Meera';
import { Callout, Focus, ScreenView, Src, vt } from '../components/AppParts';
import { body, C, display, E, FPS, pop, prog } from '../theme';
import { baselineTag, chaosCaption, IMPACT } from '../config';
import { act1Times } from '../act1Timing.js';
import { sceneOf, T } from '../theme';
import script from '../../script.json';
import { bx, FB, focusOn, ring, union } from '../boxes';

const SEG = (s: number) => Math.round(s * FPS);
export const X_FRAMES = SEG(30);
const SQ = 1080;
const banner = bx('v2', 'banner', FB.banner), say = bx('v2', 'say', FB.say), gstC = bx('v2', 'gstCard', FB.gstCard), protein = bx('v1label', 'proteinRow', FB.proteinRow);
const gstRing = { x: gstC.x - 28, y: gstC.y - 14, w: 270, h: 300, color: C.yellow };

/** A 1080x1080 window onto a recorded screen, zoomed on a region. */
const Shot: React.FC<{ src: Src; mark: string; d?: number; focus: Focus; zoom: number; frames: number; ring?: Callout }> = ({ src, mark, d = 0, focus, zoom, frames, ring }) => {
  const lf = useCurrentFrame();
  return (
    <AbsoluteFill style={{ overflow: 'hidden', background: '#0a0a0a' }}>
      <div style={{ position: 'absolute', left: -(1920 - SQ) / 2, top: 0, width: 1920, height: 1080 }}>
        <ScreenView src={src} from={vt(src, mark, d)} lf={lf} frames={frames} focus={focus} zoom={zoom} holdZoom zoomIn={2} callouts={ring ? [ring] : []} />
      </div>
      <div style={{ position: 'absolute', inset: 0, boxShadow: 'inset 0 0 120px rgba(0,0,0,.6)' }} />
    </AbsoluteFill>
  );
};

const Cap: React.FC<{ text: string; sub?: string; color?: string; top?: boolean; at?: number }> = ({ text, sub, color = C.yellow, top = false, at = 6 }) => {
  const lf = useCurrentFrame();
  const p = pop(lf, at, FPS, 13, 180, 0.7);
  return (
    <div style={{ position: 'absolute', left: 48, right: 48, [top ? 'top' : 'bottom']: 56, transform: `translateY(${(1 - p) * (top ? -30 : 30)}px)`, opacity: Math.min(1, p * 1.6), zIndex: 30 }}>
      <div style={{ background: 'rgba(15,17,23,.92)', border: `4px solid ${color}`, borderRadius: 24, padding: '16px 28px', boxShadow: `0 0 50px ${color}44` }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 76, lineHeight: 1.04, color }}>{text}</div>
        {sub ? <div style={{ fontFamily: body, fontWeight: 500, fontSize: 38, color: C.text, marginTop: 6 }}>{sub}</div> : null}
      </div>
    </div>
  );
};

const ChaosPart: React.FC = () => {
  const lf = useCurrentFrame();
  const a = sceneOf('a1-intro'), b = sceneOf('a1-mid'), c = sceneOf('a1-end');
  const t = act1Times(T, script);
  // play the busiest 3.4 s of Act 1 (stations 2-4 and the first notes), then jump to the buried freeze
  const f = lf < SEG(3.2) ? Math.round((t.stations[2] - 0.6) * FPS) + lf : Math.round(t.freeze * FPS) + (lf - SEG(3.2));
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <div style={{ position: 'absolute', left: -(1920 - SQ) / 2, top: 0, width: 1920, height: 1080 }}>
        <Act1Visual f={f} />
      </div>
      {lf < SEG(3.2) ? <Cap text="One vendor onboarding..." color={C.orange} top at={4} /> : <Cap text={chaosCaption} sub={baselineTag} color={C.orange} top at={2} />}
    </AbsoluteFill>
  );
};

const Montage: React.FC = () => {
  const items: { mark: string; tag: string }[] = [{ mark: 'run', tag: 'Run the category' }, { mark: 'price', tag: 'Price requests' }, { mark: 'catalog', tag: 'Catalog QC' }, { mark: 'rules', tag: 'Playbook' }, { mark: 'try', tag: 'Pet, beauty, electronics' }];
  return (
    <AbsoluteFill>
      {items.map((it, i) => (
        <Sequence key={it.mark} from={i * SEG(0.9)} durationInFrames={SEG(0.9)}>
          <Shot src="montage" mark={it.mark} d={0.6} focus={{ x: 400, y: 60, w: 760, h: 760 }} zoom={1.4} frames={SEG(0.9)} />
          <Cap text={it.tag} color={C.blue} at={1} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

const WeekBack: React.FC = () => {
  const lf = useCurrentFrame();
  const pct = (IMPACT.saved_pct as number) * prog(lf, 4, 40, E.out);
  return (
    <AbsoluteFill style={{ background: 'radial-gradient(900px 700px at 50% 30%, #123222 0%, #0c1a14 70%)' }}>
      <div style={{ position: 'absolute', top: 90, left: 0, right: 0, textAlign: 'center' }}>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 250, color: C.green, lineHeight: 1 }}>{pct.toFixed(1)}%</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 52, color: C.text }}>of a category team's week, back</div>
        <div style={{ display: 'inline-block', marginTop: 16, background: C.yellow, color: '#10131a', fontWeight: 700, fontSize: 38, padding: '8px 26px', borderRadius: 999 }}>modelled, not measured</div>
      </div>
      <Meera pose="relaxed" x={540} y={1050} h={440} z={5} />
    </AbsoluteFill>
  );
};

const EndCard: React.FC = () => {
  const lf = useCurrentFrame();
  const p = pop(lf, 2, FPS, 12, 170, 0.8);
  return (
    <AbsoluteFill style={{ background: 'radial-gradient(900px 700px at 50% 30%, #123222 0%, #0c1a14 70%)' }}>
      <div style={{ position: 'absolute', top: 120, left: 40, right: 40, textAlign: 'center', transform: `scale(${0.9 + 0.1 * p})`, opacity: Math.min(1, p * 2) }}>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 46, color: C.dim }}>Built on Meta Muse</div>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 92, color: C.green, marginTop: 20, lineHeight: 1.05 }}>categoryos.vercel.app</div>
      </div>
      <Meera pose="waving" x={540} y={1040} h={600} sx={0.9 + 0.1 * p} sy={0.9 + 0.1 * p} z={5} />
    </AbsoluteFill>
  );
};

/** 30 s square cut for X: chaos -> one hero moment -> verifier -> vision -> fast montage -> week back -> URL. */
export const XCut: React.FC = () => (
  <AbsoluteFill style={{ background: C.bg }}>
    <Sequence from={0} durationInFrames={SEG(4.6)}><ChaosPart /></Sequence>
    <Sequence from={SEG(4.6)} durationInFrames={SEG(4.2)}>
      <Shot src="v2" mark="settled" d={0.2} focus={focusOn(union(banner, say), 900, 300)} zoom={1.15} frames={SEG(4.2)} ring={ring(banner, C.red)} />
      <Cap text="P(hit) < 0.1%" sub="Reject the structure" color={C.red} />
    </Sequence>
    <Sequence from={SEG(8.8)} durationInFrames={SEG(3.4)}>
      <Shot src="v2" mark="settled" d={0.4} focus={focusOn(union(banner, say), 900, 300)} zoom={1.15} frames={SEG(3.4)} ring={ring(say, C.green)} />
      <Cap text="Say next: 250 units" sub="60.5% likely, worth 27.1%, or 22% guaranteed" color={C.green} />
    </Sequence>
    <Sequence from={SEG(12.2)} durationInFrames={SEG(3.6)}>
      <Shot src="v2" mark="intakeOpen" d={0.3} focus={focusOn(gstRing, 360, 300)} zoom={2.6} frames={SEG(3.6)} ring={gstRing} />
      <Cap text="01 APR 2023 vs 2025" sub="two reads disagree: flagged, not guessed" color={C.yellow} />
    </Sequence>
    <Sequence from={SEG(15.8)} durationInFrames={SEG(3.2)}>
      <Shot src="v1label" mark="panelSettled" d={0.1} focus={{ x: protein.x, y: protein.y - 80, w: 850, h: 700 }} zoom={1.2} frames={SEG(3.2)} ring={ring(protein, C.red, 4)} />
      <Cap text="Label 30% vs sheet 32%" sub="caught before listing" color={C.red} />
    </Sequence>
    <Sequence from={SEG(19)} durationInFrames={SEG(4.5)}><Montage /></Sequence>
    <Sequence from={SEG(23.5)} durationInFrames={SEG(3.5)}><WeekBack /></Sequence>
    <Sequence from={SEG(27)} durationInFrames={SEG(3)}><EndCard /></Sequence>
  </AbsoluteFill>
);
