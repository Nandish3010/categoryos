import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { MeeraWalker, planWalk, stateAt } from '../components/MeeraWalker';
import { SparkleBurst } from '../components/WalkerProps';
import { VoCaptions } from '../components/Captions';
import { body, C, display, E, FPS, phraseFrame, pop, prog, rnd, sceneOf } from '../theme';
import { TEAM, TEAM_BUILT_FOR, TeamMember } from '../config';

const FLOOR = 880; // same floor as the slam scene, so she hands over on the same line
const H = 500;
const CARD_CX = 850, CARD_TOP = 190;

/** Warm (Act 1) to neutral and back to warm, so the cut into the slam scene matches. */
const mix = (a: string, b: string, t: number) => {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(interpolate(t, [0, 1], [v, pb[i]]))).join(',')})`;
};

const Avatar: React.FC<{ m: TeamMember; size: number }> = ({ m, size }) => {
  const initials = m.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  return (
    <div style={{ width: size, height: size, borderRadius: '50%', flex: 'none', overflow: 'hidden', border: `6px solid ${C.orange}`, boxShadow: `0 0 36px ${C.orange}55`, background: `linear-gradient(145deg, ${C.orange}, #d9694f 55%, ${C.blue})`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {m.photo ? (
        <Img src={staticFile(`team/${m.photo}`)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      ) : (
        <span style={{ fontFamily: display, fontWeight: 700, fontSize: size * 0.46, color: '#1a0f0c', letterSpacing: -2 }}>{initials}</span>
      )}
    </div>
  );
};

const Card: React.FC<{ m: TeamMember; w: number; lift: number }> = ({ m, w, lift }) => (
  <div style={{ width: w, background: C.surface, border: '3px solid rgba(245,169,98,.6)', borderRadius: 30, padding: '30px 34px 28px', boxShadow: `0 ${30 + lift}px 70px rgba(0,0,0,.55), 0 0 90px rgba(245,169,98,${0.14 + lift * 0.01})`, transform: `translateY(${-lift}px)` }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 30 }}>
      <Avatar m={m} size={w > 700 ? 180 : 140} />
      <div>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: w > 700 ? 80 : 60, lineHeight: 1, color: C.text }}>{m.name}</div>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 30, lineHeight: 1.2, color: C.dim, marginTop: 10 }}>{m.role}</div>
      </div>
    </div>
    <div style={{ height: 2, background: 'rgba(255,255,255,.1)', margin: '24px 0 18px' }} />
    <div style={{ display: 'inline-block', background: 'rgba(245,169,98,.13)', border: '2px solid rgba(245,169,98,.55)', borderRadius: 26, padding: '8px 22px', fontFamily: body, fontWeight: 500, fontSize: 28, lineHeight: 1.3, color: C.text }}>
      {TEAM_BUILT_FOR.join(' · ')}
    </div>
  </div>
);

/** "Meet the team": Meera walks in, a builder card rises, she turns to camera, they high-five, she walks off to the right (into the slam scene). */
export const TeamScene: React.FC = () => {
  const f = useCurrentFrame();
  const sc = sceneOf('a2-team');
  const nF = phraseFrame('a2-team', 'Nandish designed');
  const turn = phraseFrame('a2-team', 'And I');
  const hi5 = phraseFrame('a2-team', 'category manager');
  const stand = 1520;
  const opts = React.useMemo(() => ({
    floor: FLOOR, h: H, enterFrom: 'left' as const, enterSpeed: 500,
    beats: [
      { at: Math.max(90, nF + 40), x: stand, pose: 'pointing' as const }, // presents the builder (the cut-out points left, at the card)
      { at: turn + 4, x: stand, pose: 'celebrating' as const, hop: 34 }, // turns to camera on "And I'm the category manager", lands on the high-five
    ],
    exit: { at: hi5 + 22, to: 'right' as const, speed: 590 },
  }), [nF, turn, hi5]);
  const plan = React.useMemo(() => planWalk(opts), [opts]);
  const t = prog(f, 20, 170, E.inOut) * (1 - prog(f, sc.frames - 40, sc.frames - 2, E.inOut));
  const cardP = pop(f, nF, FPS, 13, 150, 0.8);
  const since = f - hi5;
  const lift = since >= 0 && since < 16 ? 16 * Math.sin((Math.PI * since) / 16) : 0; // the card hops on the high-five
  const n = TEAM.length;
  const cardW = n === 1 ? 830 : Math.min(560, (1160 - (n - 1) * 26) / n);
  const groupW = n * cardW + (n - 1) * 26;
  const hand = stateAt(plan, hi5);
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${mix('#2c1613', '#1d202b', t)}, ${mix('#0d0706', '#0f1117', t)})`, overflow: 'hidden' }}>
      <AbsoluteFill style={{ background: `radial-gradient(900px 620px at ${CARD_CX}px 380px, rgba(245,169,98,${0.16 + 0.05 * Math.sin(f * 0.06)}) 0%, rgba(245,169,98,0) 70%)` }} />
      {Array.from({ length: 14 }).map((_, i) => (
        <div key={i} style={{ position: 'absolute', left: rnd(i + 20) * 1920, top: 80 + rnd(i * 2 + 7) * 620, width: 36 + rnd(i * 3.1) * 90, height: 36 + rnd(i * 3.1) * 90, borderRadius: '50%', background: i % 3 ? 'rgba(245,169,98,.07)' : 'rgba(110,168,254,.06)', filter: 'blur(6px)', transform: `translateY(${Math.sin(f * 0.02 + i) * 8}px)` }} />
      ))}
      <div style={{ position: 'absolute', left: 0, right: 0, top: FLOOR - 12, height: 220, background: 'linear-gradient(180deg,#3a211c,#1a0f0c)', opacity: 0.9 - 0.4 * t }} />
      <div style={{ position: 'absolute', left: 0, right: 0, top: FLOOR - 12, height: 3, background: 'rgba(245,169,98,.35)' }} />
      <div style={{ position: 'absolute', left: CARD_CX - groupW / 2, top: 78, opacity: prog(f, 6, 20), transform: `translateY(${(1 - prog(f, 6, 20)) * -14}px)`, fontFamily: display, fontWeight: 700, fontSize: 60, color: C.text }}>
        Meet the <span style={{ color: C.orange }}>team</span>
      </div>
      <div style={{ position: 'absolute', left: CARD_CX - groupW / 2, top: CARD_TOP + 10, display: 'flex', gap: 26, transform: `translateY(${(1 - cardP) * 300}px) scale(${0.9 + 0.1 * cardP})`, transformOrigin: '50% 100%', opacity: Math.min(1, cardP * 2.4) }}>
        {TEAM.map((m) => <Card key={m.name} m={m} w={cardW} lift={lift} />)}
      </div>
      <MeeraWalker {...opts} plan={plan} />
      <SparkleBurst x={(hand.x - 0.3 * H + CARD_CX + groupW / 2) / 2 + 50} y={FLOOR - 0.72 * H} a={since} size={1.25} />
      <VoCaptions sceneId="a2-team" accent={C.orange} bottom={52} />
    </AbsoluteFill>
  );
};
