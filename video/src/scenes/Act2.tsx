import React from 'react';
import { AppScene, Seg } from './AppScene';
import { C } from '../theme';

// Coordinates are recorded-video pixels (1920x1080). They match the replay recordings; re-check after swapping in live runs.

const M1: Seg[] = [
  { a: 0, b: 0.15, src: 'v2', mark: 'call', d: 0.4, meera: { pose: 'pointing', side: 'right', text: 'Live vendor call!', at: 10, dur: 70 } },
  { a: 0.15, b: 0.34, src: 'v2', mark: 'call', d: 7, whip: true, focus: { x: 920, y: 560, w: 450, h: 520 }, callouts: [{ x: 930, y: 570, w: 430, h: 500 }] },
  { a: 0.34, b: 0.52, src: 'v2', mark: 'reject', d: -4, whip: true, focus: { x: 470, y: 640, w: 900, h: 440 }, callouts: [{ x: 565, y: 960, w: 340, h: 100, color: C.orange }] },
  { a: 0.52, b: 0.76, src: 'v2', mark: 'reject', d: 0.8, whip: true, focus: { x: 470, y: 325, w: 900, h: 235 }, callouts: [{ x: 480, y: 332, w: 880, h: 71, color: C.red }], big: { text: 'P(hit) < 0.1%', sub: 'Reject the structure', color: C.red, at: 26, y: 700 }, meera: { pose: 'thinking', side: 'left', text: 'Sounds like 35%... is it?', at: 8, dur: 60 } },
  { a: 0.76, b: 1, src: 'v2', mark: 'sayNext', d: 0.4, whip: true, focus: { x: 470, y: 415, w: 900, h: 145 }, callouts: [{ x: 480, y: 422, w: 880, h: 131, color: C.green }], big: { text: '250 units: 60.5% likely', sub: 'worth 27.1%, or 22% guaranteed', color: C.green, at: 24, y: 700 }, meera: { pose: 'celebrating', side: 'right', text: 'My next line!', at: 40, dur: 70 } },
];

const M2: Seg[] = [
  { a: 0, b: 0.2, src: 'v1', mark: 'decided', d: 1, meera: { pose: 'pointing', side: 'left', text: 'Every number cites a cell.', at: 10, dur: 80 } },
  { a: 0.2, b: 0.62, src: 'v1', mark: 'decided', d: 3, whip: true, focus: { x: 1560, y: 110, w: 350, h: 260 }, callouts: [{ x: 1630, y: 115, w: 270, h: 245, color: C.green }], big: { text: '₹965.50 → ₹956.50', sub: 'caught and corrected', color: C.yellow, at: 30, y: 640 }, meera: { pose: 'thinking', side: 'left', text: '965.50? The sheet says 956.50.', at: 20, dur: 80 } },
  { a: 0.62, b: 1, src: 'v1', mark: 'lever', d: 0.5, whip: true, big: { text: '198 / 200 caught', sub: 'planted errors · 0 false positives', color: C.green, at: 8, y: 640, align: 'center' }, meera: { pose: 'celebrating', side: 'right', at: 20, dur: 90 } },
];

const M3: Seg[] = [
  { a: 0, b: 0.34, src: 'v2', mark: 'intake', d: 5, focus: { x: 480, y: 620, w: 880, h: 140 }, callouts: [{ x: 496, y: 640, w: 850, h: 46, color: C.red }, { x: 700, y: 718, w: 170, h: 32, color: C.yellow }], big: { text: 'Expires 30 Nov 2026', sub: 'the application said 2027', color: C.red, at: 20, y: 700 }, meera: { pose: 'pointing', side: 'right', text: 'The scan says 2026!', at: 14, dur: 70 } },
  { a: 0.34, b: 0.67, src: 'v1label', mark: 'panel', d: -0.3, play: 1.3, whip: true, focus: { x: 498, y: 370, w: 850, h: 700 }, callouts: [{ x: 498, y: 436, w: 846, h: 36, color: C.red }, { x: 890, y: 696, w: 440, h: 40, color: C.yellow }], big: { text: 'Label 30% vs sheet 32%', sub: 'SAM crop of the panel, then re-read', color: C.red, at: 20, y: 120 }, meera: { pose: 'thinking', side: 'left', text: '30 or 32?', at: 14, dur: 60 } },
  { a: 0.67, b: 1, src: 'v1', mark: 'scans', d: -1, whip: true, focus: { x: 480, y: 230, w: 880, h: 110 }, callouts: [{ x: 496, y: 258, w: 848, h: 42, color: C.red }], big: { text: 'HP-D06: ₹3,352 vs ₹3,325', sub: 'price list vs sheet', color: C.red, at: 20, y: 700 }, meera: { pose: 'celebrating', side: 'right', text: 'Caught before listing!', at: 40, dur: 70 } },
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
