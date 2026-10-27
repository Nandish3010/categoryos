import React from 'react';
import { AppScene, Seg } from './AppScene';
import { C } from '../theme';
import { bx, FB, focusOn, ring, union } from '../boxes';

// Coordinates are recorded-video pixels (1920x1080). They match the replay recordings; re-check after swapping in live runs.

const banner = bx('v2', 'banner', FB.banner), say = bx('v2', 'say', FB.say), cond = bx('v2', 'condOffer', FB.condOffer), gap = bx('v2', 'gap', FB.gap);
const gstC = bx('v2', 'gstCard', FB.gstCard), price = bx('v1', 'priceRow', FB.priceRow);
const fssai = bx('v2', 'fssaiRow', FB.fssaiRow), protein = bx('v1label', 'proteinRow', FB.proteinRow);

const M1: Seg[] = [
  { a: 0, b: 0.15, src: 'v2', mark: 'call', d: 0.4, note: 'Replay of a real live run \u00B7 recorded 27 Oct 2026', meera: { pose: 'pointing', side: 'right', text: 'Live vendor call!', at: 10, dur: 70 } },
  { a: 0.15, b: 0.34, src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: { x: gap.x - 10, y: gap.y - 10, w: gap.w + 20, h: 520 }, callouts: [{ x: gap.x - 8, y: gap.y - 6, w: gap.w + 16, h: 500, color: C.yellow }] },
  { a: 0.34, b: 0.52, src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: focusOn({ x: cond.x, y: cond.y, w: 430, h: 90 }, 900, 380), callouts: [{ x: cond.x - 8, y: cond.y - 8, w: 446, h: 100, color: C.orange }] },
  { a: 0.52, b: 0.76, src: 'v2', mark: 'settled', d: 0.2, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(banner, C.red)], big: { text: 'P(hit) < 0.1%', sub: 'Reject the structure', color: C.red, at: 26, y: 700 }, meera: { pose: 'thinking', side: 'left', text: 'Sounds like 35%... is it?', at: 8, dur: 60 } },
  { a: 0.76, b: 1, src: 'v2', mark: 'settled', d: 0.4, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(say, C.green)], big: { text: '250 units: 60.5% likely', sub: 'worth 27.1%, or 22% guaranteed', color: C.green, at: 24, y: 700 }, meera: { pose: 'celebrating', side: 'right', text: 'My next line!', at: 40, dur: 70 } },
];

const gstRing = { x: gstC.x - 28, y: gstC.y - 14, w: 270, h: 300, color: C.yellow };
const M2: Seg[] = [
  { a: 0, b: 0.2, src: 'v2', mark: 'intakeOpen', d: 0, meera: { pose: 'pointing', side: 'left', text: 'Every number cites its source.', at: 10, dur: 80 } },
  { a: 0.2, b: 0.7, src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, focus: focusOn(gstRing, 360, 300), callouts: [gstRing], big: { text: '01 APR 2023 vs 2025', sub: 'two reads disagree: flagged, not guessed', color: C.yellow, at: 30, y: 330, align: 'right' }, meera: { pose: 'thinking', side: 'left', text: 'Which one? It will not guess.', at: 20, dur: 80 } },
  { a: 0.7, b: 1, src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, big: { text: '198 / 200 caught', sub: 'planted errors \u00B7 0 false positives', color: C.green, at: 8, y: 640, align: 'center' }, meera: { pose: 'celebrating', side: 'right', at: 20, dur: 90 } },
];

const M3: Seg[] = [
  { a: 0, b: 0.34, src: 'v2', mark: 'intakeOpen', d: 0.3, focus: focusOn(fssai, 880, 140), callouts: [ring(fssai, C.red, 6)], big: { text: 'Expires 30 Nov 2026', sub: 'the application said 2027', color: C.red, at: 20, y: 700 }, meera: { pose: 'pointing', side: 'right', text: 'The scan says 2026!', at: 14, dur: 70 } },
  { a: 0.34, b: 0.67, src: 'v1label', mark: 'panelSettled', d: 0.1, whip: true, focus: { x: protein.x, y: protein.y - 80, w: 850, h: 700 }, callouts: [ring(protein, C.red, 4)], big: { text: 'Label 30% vs sheet 32%', sub: 'SAM crop of the panel, then re-read', color: C.red, at: 20, y: 700 }, meera: { pose: 'thinking', side: 'left', text: '30 or 32?', at: 14, dur: 60 } },
  { a: 0.67, b: 1, src: 'v1', mark: 'scans', d: 0.3, whip: true, focus: focusOn(price, 880, 110), callouts: [ring(price, C.red, 6)], big: { text: 'HP-D06: \u20B93,352 vs \u20B93,325', sub: 'price list vs sheet', color: C.red, at: 20, y: 700 }, meera: { pose: 'celebrating', side: 'right', text: 'Caught before listing!', at: 40, dur: 70 } },
];

const F = { x: 400, y: 30, w: 1120, h: 640 };
const M4: Seg[] = ([
  { src: 'montage', mark: 'run', tag: 'Category MIS' },
  { src: 'montage', mark: 'price', tag: 'Price requests', callouts: [{ x: 1000, y: 240, w: 520, h: 170, color: C.green }] },
  { src: 'montage', mark: 'catalog', tag: 'Catalog QC: 36 issues, 32 fixes', callouts: [{ x: 408, y: 330, w: 1100, h: 75, color: C.green }] },
  { src: 'montage', mark: 'promos', tag: 'Promotions' },
  { src: 'montage', mark: 'watch', tag: 'Price watch', callouts: [{ x: 408, y: 250, w: 1104, h: 100, color: C.yellow }] },
  { src: 'montage', mark: 'rules', tag: 'Playbook: every rule editable' },
  { src: 'montage', mark: 'try', tag: 'Bring your own: pet, beauty, electronics' },
] as Seg[]).map((s, i): Seg => ({
  ...s, a: i / 7, b: (i + 1) / 7, d: 0.5, whip: true, focus: F,
  meera: i === 1 ? { pose: 'pointing' as const, side: 'right' as const, at: 20, dur: 50 } : i === 4 ? { pose: 'thinking' as const, side: 'left' as const, at: 20, dur: 50 } : i === 6 ? { pose: 'celebrating' as const, side: 'right' as const, at: 24, dur: 60 } : undefined,
}));

export const M1Scene = () => <AppScene sceneId="m1-call" segs={M1} hours={[0.0, 0.3]} />;
export const M2Scene = () => <AppScene sceneId="m2-verifier" segs={M2} hours={[0.3, 0.55]} />;
export const M3Scene = () => <AppScene sceneId="m3-vision" segs={M3} hours={[0.55, 0.8]} />;
export const M4Scene = () => <AppScene sceneId="m4-run" segs={M4} hours={[0.8, 1.0]} />;
