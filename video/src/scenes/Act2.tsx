import React from 'react';
import { useCurrentFrame } from 'remotion';
import { MeeraWalker, planWalk, Plan, WalkOpts, WalkState } from '../components/MeeraWalker';
import { Card, FlyingDocs, PaperStack, sheetsLeft, TaskCards, Throw } from '../components/WalkerProps';
import { AppScene, Seg } from './AppScene';
import { C } from '../theme';
import { bx, FB, focusOn, ring, union } from '../boxes';
import { phraseFrame, sceneOf } from '../theme';

// Coordinates are recorded-video pixels (1920x1080). They match the replay recordings; re-check after swapping in live runs.

const banner = bx('v2', 'banner', FB.banner), say = bx('v2', 'say', FB.say), cond = bx('v2', 'condOffer', FB.condOffer), gap = bx('v2', 'gap', FB.gap);
const gstC = bx('v2', 'gstCard', FB.gstCard), price = bx('v1', 'priceRow', FB.priceRow);
const fssai = bx('v2', 'fssaiRow', FB.fssaiRow), protein = bx('v1label', 'proteinRow', FB.proteinRow);

/** Fraction of scene `id` at which `phrase` is spoken (null = start, 'end' = 1). Segments cut on the words, so the picture follows the sentence. */
const fr = (id: string, phrase: string | null) => (phrase === null ? 0 : phrase === 'end' ? 1 : phraseFrame(id, phrase) / sceneOf(id).frames);
/** Frames from the start of the segment [from..] to the moment `phrase` is spoken (for chips that should land on a word). */
const at = (id: string, from: string | null, phrase: string, plus = 0) => Math.max(4, phraseFrame(id, phrase) - (from === null ? 0 : phraseFrame(id, from)) + plus);
const S = (id: string, from: string | null, to: string, s: Omit<Seg, 'a' | 'b'>): Seg => ({ a: fr(id, from), b: fr(id, to), ...s });

const M1: Seg[] = [
  S('m1-call', null, 'The vendor offers', { src: 'v2', mark: 'call', d: 0.4, note: 'Replay of a real live run \u00B7 recorded 27 Oct 2026' }),
  S('m1-call', 'The vendor offers', 'Sounds like thirty-five', { src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: { x: gap.x - 10, y: gap.y - 10, w: gap.w + 20, h: 520 }, callouts: [{ x: gap.x - 8, y: gap.y - 6, w: gap.w + 16, h: 500, color: C.yellow }] }),
  S('m1-call', 'Sounds like thirty-five', 'But it simulates', { src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: focusOn({ x: cond.x, y: cond.y, w: 430, h: 90 }, 900, 380), callouts: [{ x: cond.x - 8, y: cond.y - 8, w: 446, h: 100, color: C.orange }] }),
  S('m1-call', 'But it simulates', 'So it tells me', { src: 'v2', mark: 'settled', d: 0.2, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(banner, C.red)], big: { text: 'P(hit) < 0.1%', sub: 'Reject the structure', color: C.red, at: at('m1-call', 'But it simulates', 'under a tenth', -4), y: 700 } }),
  S('m1-call', 'So it tells me', 'No spreadsheet', { src: 'v2', mark: 'settled', d: 0.4, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(say, C.green)], big: { text: '250 units: 60.5% likely', sub: 'worth 27.1%, or 22% guaranteed', color: C.green, at: at('m1-call', 'So it tells me', 'set the target', -6), y: 700 } }),
  S('m1-call', 'No spreadsheet', 'end', { src: 'v2', mark: 'settled', d: 1.2, whip: true }),
];

const gstRing = { x: gstC.x - 28, y: gstC.y - 14, w: 270, h: 300, color: C.yellow };
const M2: Seg[] = [
  S('m2-verifier', null, 'In this live run', { src: 'v2', mark: 'intakeOpen', d: 0 }),
  S('m2-verifier', 'In this live run', 'On two hundred', { src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, focus: focusOn(gstRing, 360, 300), callouts: [gstRing], big: { text: 'Two reads, two dates', sub: 'flagged for me, not guessed', color: C.yellow, at: at('m2-verifier', 'In this live run', 'two different dates', -6), y: 330, align: 'right' } }),
  S('m2-verifier', 'On two hundred', 'end', { src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, big: { text: '198 / 200 caught', sub: 'planted errors \u00B7 0 false alarms', color: C.green, at: at('m2-verifier', 'On two hundred', 'one hundred and ninety-eight', -4), y: 640, align: 'center' } }),
];

const M3: Seg[] = [
  S('m3-vision', null, 'It reads the food licence', { src: 'v2', mark: 'fssai', d: 0 }),
  S('m3-vision', 'It reads the food licence', 'It cuts out', { src: 'v2', mark: 'intakeOpen', d: 0.3, focus: focusOn(fssai, 880, 140), callouts: [ring(fssai, C.red, 6)], big: { text: 'Expires 30 Nov 2026', sub: 'the application said 2027', color: C.red, at: at('m3-vision', 'It reads the food licence', 'thirtieth', -6), y: 700 } }),
  S('m3-vision', 'It cuts out', 'It even catches', { src: 'v1label', mark: 'panelSettled', d: 0.1, whip: true, focus: { x: protein.x, y: protein.y - 80, w: 850, h: 700 }, callouts: [ring(protein, C.red, 4)], big: { text: 'Label 30% vs sheet 32%', sub: 'label panel cut out, then re-read', color: C.red, at: at('m3-vision', 'It cuts out', 'thirty percent', -6), y: 700 } }),
  S('m3-vision', 'It even catches', 'All before', { src: 'v1', mark: 'scans', d: 0.3, whip: true, focus: focusOn(price, 880, 110), callouts: [ring(price, C.red, 6)], big: { text: 'HP-D06: \u20B93,352 vs \u20B93,325', sub: 'price list vs sheet', color: C.red, at: 14, y: 700 } }),
  S('m3-vision', 'All before', 'end', { src: 'v1', mark: 'scans', d: 1.8, whip: true }),
];

// The Run pages: one short look at each, labelled with what it takes off your plate. Words in the VO choose the cut.
const F = { x: 400, y: 20, w: 1060, h: 600 };
const run = (from: string | null, to: string, mark: string, tag: string, extra: Partial<Seg> = {}): Seg => S('m4-run', from, to, { src: 'montage', mark, d: 0.3, whip: true, focus: F, tag, tagSub: 'off your plate', ...extra });
const M4: Seg[] = [
  S('m4-run', null, 'It drafts my weekly', { src: 'montage', mark: 'run', d: 0.2, tag: 'Runs the category with you', focus: F }),
  run('It drafts my weekly', 'answers price-increase', 'run', 'Weekly vendor review: drafted', { d: 0.6 }),
  run('answers price-increase', 'chases late', 'price', 'Price-increase requests: answered'),
  run('chases late', 'queues catalog', 'pos', 'Late PO follow-ups: chased'),
  run('queues catalog', 'plans promotions', 'catalog', 'Catalog fixes: queued'),
  run('plans promotions', 'watches competitor', 'promos', 'Promotions: planned'),
  run('watches competitor', 'and flags stock', 'watch', 'Competitor price watch'),
  run('and flags stock', 'Every rule lives', 'inventory', 'Stock-outs and dead stock: flagged'),
  S('m4-run', 'Every rule lives', 'for pet, beauty', { src: 'montage', mark: 'rules', d: 0.3, whip: true, focus: F, tag: 'One playbook, your rules', tagSub: 'every rule editable' }),
  S('m4-run', 'for pet, beauty', 'end', { src: 'montage', mark: 'try', d: 0.3, whip: true, focus: F, tag: 'Pet, beauty, electronics, or your own' }),
];

// ---- Meera on stage: she walks along the floor beside the tilted frame (components/MeeraWalker.tsx); no pop-ins ----
// She keeps to the two side strips (x ~ 140 and x ~ 1780) so the BigChips (left, y 700) and the captions (centre, bottom) stay clear; she crosses
// the floor only when she paces. Continuity: she walks in from the side she left the scene before, and walks out at the end.
const FLOOR = 1056, MH = 350, XL = 140, XR = 1780;
const pf = (id: string, p: string) => phraseFrame(id, p);

const W1 = { floor: FLOOR, h: MH, enterFrom: 'right' as const, beats: [
  { at: 24, x: XR, pose: 'phone' as const, text: 'Live vendor call!', textAt: 26, textDur: 62 },
  // pacing while the call runs: she turns around at the ends of the right-hand strip (x 1580-1800) and never crosses the app or the caption plate
  ...[70, 120, 170, 220, 270, 320, 370].map((at, i) => ({ at, x: i % 2 ? XR : 1580, pose: 'phone' as const, walkPose: 'phone' as const })),
  { at: pf('m1-call', 'Sounds like thirty-five') + 4, x: XR, pose: 'thinking' as const, walkPose: 'phone' as const, text: 'Sounds like 35%... is it?', textAt: pf('m1-call', 'Sounds like thirty-five') + 8, textDur: 56 },
  { at: pf('m1-call', 'under a tenth') + 8, x: 1650, pose: 'pointing' as const }, // a couple of steps toward the frame as the verdict lands
  { at: pf('m1-call', 'set the target') + 8, x: XR, pose: 'pointing' as const },
  { at: pf('m1-call', 'No spreadsheet') + 4, x: XR, pose: 'celebrating' as const, hop: 30, text: 'No spreadsheet after the call.', textAt: pf('m1-call', 'No spreadsheet') + 8, textDur: 30 },
], exit: { at: pf('m1-call', 'No spreadsheet') + 36, to: 'right' as const, speed: 600 } };

const d2 = pf('m2-verifier', 'two different dates');
const W2 = { floor: FLOOR, h: MH, enterFrom: 'right' as const, beats: [
  { at: 30, x: XR, pose: 'pointing' as const, text: 'Every number cites its source.', textAt: pf('m2-verifier', 'Every number'), textDur: 80 },
  { at: pf('m2-verifier', 'In this live run') + 6, x: 1700, pose: 'pointing' as const },
  { at: d2, x: 1620, pose: 'thinking' as const, lean: -9, text: 'Which one? It will not guess.', textAt: pf('m2-verifier', 'Instead of guessing'), textDur: 80 }, // walks up to the frame and leans in
  { at: pf('m2-verifier', 'one hundred and ninety-eight') + 4, x: XR, pose: 'celebrating' as const, hop: 30 },
], exit: { at: pf('m2-verifier', 'one hundred and ninety-eight') + 66, to: 'right' as const } };

// m3: she carries a tall wobbly stack of paper documents; each catch takes a sheet (three, in fact) off her plate and into the app
const STACK = 9, PER = 3;
const m3Throws: Throw[] = [
  { at: pf('m3-vision', 'thirtieth') - 2, label: 'LICENCE', color: C.red, to: { x: 960, y: 480 } },
  { at: pf('m3-vision', 'thirty percent') - 2, label: 'LABEL', color: C.red, to: { x: 940, y: 500 } },
  { at: pf('m3-vision', 'It even catches') + 12, label: 'PRICE LIST', color: C.red, to: { x: 970, y: 470 } },
];
const W3 = { floor: FLOOR, h: MH, enterFrom: 'right' as const, beats: [
  { at: 34, x: 1715, pose: 'pointing' as const, text: 'Scans, not data.', textAt: pf('m3-vision', 'Vendors send'), textDur: 60 },
  { at: pf('m3-vision', 'though the application') - 4, x: 1625, pose: 'pointing' as const, text: 'The scan says 2026!', textAt: pf('m3-vision', 'though the application'), textDur: 70 },
  { at: pf('m3-vision', 'where the sheet') - 6, x: 1715, pose: 'thinking' as const, text: '30 or 32?', textAt: pf('m3-vision', 'where the sheet'), textDur: 60 },
  { at: pf('m3-vision', 'All before') + 4, x: 1715, pose: 'celebrating' as const, hop: 30, text: 'Caught before listing!', textAt: pf('m3-vision', 'All before') + 10, textDur: 70 },
], exit: { at: pf('m3-vision', 'All before') + 88, to: 'right' as const } };

// m4: as each weekly job tag appears she hands a small task card to the frame, taking a few steps between hand-offs
const JOBS: [string, string, string][] = [
  ['It drafts my weekly', 'Weekly review', C.blue], ['answers price-increase', 'Price reply', C.orange], ['chases late', 'PO chase', C.yellow], ['queues catalog', 'Catalog fix', C.green],
  ['plans promotions', 'Promo plan', '#F9A8D4'], ['watches competitor', 'Price watch', '#C4B5FD'], ['and flags stock', 'Stock flag', C.red],
];
const m4Cards: Card[] = JOBS.map(([p, text, color], i) => ({ at: pf('m4-run', p) + 8, text, color, to: { x: 930 + (i % 3) * 40, y: 430 + (i % 2) * 50 } }));
const W4 = { floor: FLOOR, h: MH, enterFrom: 'right' as const, beats: [
  { at: 40, x: XR, pose: 'pointing' as const },
  ...m4Cards.slice(1).map((c, i) => ({ at: c.at - 6, x: i % 2 ? XR : 1650, pose: 'pointing' as const })),
  { at: pf('m4-run', 'Every rule lives') + 2, x: XR, pose: 'relaxed' as const },
  { at: pf('m4-run', 'for pet, beauty') + 8, x: XR, pose: 'celebrating' as const, hop: 30 },
], exit: { at: sceneOf('m4-run').frames - 36, to: 'right' as const } };

export const W_PLANS = { m1: W1, m2: W2, m3: W3, m4: W4 };
const P3 = planWalk(W3), P4 = planWalk(W4);

const Walk: React.FC<{ o: WalkOpts; extra?: (p: Plan, f: number) => React.ReactNode; prop?: (s: WalkState, p: Plan) => React.ReactNode; plan?: Plan }> = ({ o, extra, prop, plan }) => {
  const f = useCurrentFrame();
  const p = React.useMemo(() => plan ?? planWalk(o), [plan, o]);
  return (<><MeeraWalker {...o} plan={p} prop={prop} />{extra ? extra(p, f) : null}</>);
};

export const M1Scene = () => <AppScene sceneId="m1-call" segs={M1} hours={[0.0, 0.3]}><Walk o={W1} /></AppScene>;
export const M2Scene = () => <AppScene sceneId="m2-verifier" segs={M2} hours={[0.3, 0.55]}><Walk o={W2} /></AppScene>;
export const M3Scene = () => (
  <AppScene sceneId="m3-vision" segs={M3} hours={[0.55, 0.8]}>
    <Walk o={W3} plan={P3} prop={(s) => <PaperStack s={s} sheets={sheetsLeft(STACK, m3Throws, PER, s.f)} total={STACK} />} extra={(p, f) => <FlyingDocs plan={p} f={f} throws={m3Throws} total={STACK} perThrow={PER} />} />
  </AppScene>
);
export const M4Scene = () => (
  <AppScene sceneId="m4-run" segs={M4} hours={[0.8, 1.0]}>
    <Walk o={W4} plan={P4} extra={(p, f) => <TaskCards plan={p} f={f} cards={m4Cards} />} />
  </AppScene>
);
