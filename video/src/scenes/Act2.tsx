import React from 'react';
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
  S('m1-call', null, 'The vendor offers', { src: 'v2', mark: 'call', d: 0.4, note: 'Replay of a real live run \u00B7 recorded 27 Oct 2026', meera: { pose: 'pointing', side: 'right', text: 'Live vendor call!', at: 10, dur: 70 } }),
  S('m1-call', 'The vendor offers', 'Sounds like thirty-five', { src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: { x: gap.x - 10, y: gap.y - 10, w: gap.w + 20, h: 520 }, callouts: [{ x: gap.x - 8, y: gap.y - 6, w: gap.w + 16, h: 500, color: C.yellow }] }),
  S('m1-call', 'Sounds like thirty-five', 'But it simulates', { src: 'v2', mark: 'reject', d: 0.3, whip: true, focus: focusOn({ x: cond.x, y: cond.y, w: 430, h: 90 }, 900, 380), callouts: [{ x: cond.x - 8, y: cond.y - 8, w: 446, h: 100, color: C.orange }], meera: { pose: 'thinking', side: 'left', text: 'Sounds like 35%... is it?', at: 6, dur: 55 } }),
  S('m1-call', 'But it simulates', 'So it tells me', { src: 'v2', mark: 'settled', d: 0.2, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(banner, C.red)], big: { text: 'P(hit) < 0.1%', sub: 'Reject the structure', color: C.red, at: at('m1-call', 'But it simulates', 'under a tenth', -4), y: 700 } }),
  S('m1-call', 'So it tells me', 'No spreadsheet', { src: 'v2', mark: 'settled', d: 0.4, whip: true, focus: focusOn(union(banner, say), 900, 300), callouts: [ring(say, C.green)], big: { text: '250 units: 60.5% likely', sub: 'worth 27.1%, or 22% guaranteed', color: C.green, at: at('m1-call', 'So it tells me', 'set the target', -6), y: 700 } }),
  S('m1-call', 'No spreadsheet', 'end', { src: 'v2', mark: 'settled', d: 1.2, whip: true, meera: { pose: 'celebrating', side: 'right', text: 'No spreadsheet after the call.', at: 14, dur: 70 } }),
];

const gstRing = { x: gstC.x - 28, y: gstC.y - 14, w: 270, h: 300, color: C.yellow };
const M2: Seg[] = [
  S('m2-verifier', null, 'In this live run', { src: 'v2', mark: 'intakeOpen', d: 0, meera: { pose: 'pointing', side: 'left', text: 'Every number cites its source.', at: at('m2-verifier', null, 'Every number'), dur: 80 } }),
  S('m2-verifier', 'In this live run', 'On two hundred', { src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, focus: focusOn(gstRing, 360, 300), callouts: [gstRing], big: { text: 'Two reads, two dates', sub: 'flagged for me, not guessed', color: C.yellow, at: at('m2-verifier', 'In this live run', 'two different dates', -6), y: 330, align: 'right' }, meera: { pose: 'thinking', side: 'left', text: 'Which one? It will not guess.', at: at('m2-verifier', 'In this live run', 'Instead of guessing'), dur: 80 } }),
  S('m2-verifier', 'On two hundred', 'end', { src: 'v2', mark: 'intakeOpen', d: 0.3, whip: true, big: { text: '198 / 200 caught', sub: 'planted errors \u00B7 0 false alarms', color: C.green, at: at('m2-verifier', 'On two hundred', 'one hundred and ninety-eight', -4), y: 640, align: 'center' }, meera: { pose: 'celebrating', side: 'right', at: 20, dur: 90 } }),
];

const M3: Seg[] = [
  S('m3-vision', null, 'It reads the food licence', { src: 'v2', mark: 'fssai', d: 0, meera: { pose: 'pointing', side: 'right', text: 'Scans, not data.', at: at('m3-vision', null, 'Vendors send'), dur: 60 } }),
  S('m3-vision', 'It reads the food licence', 'It cuts out', { src: 'v2', mark: 'intakeOpen', d: 0.3, focus: focusOn(fssai, 880, 140), callouts: [ring(fssai, C.red, 6)], big: { text: 'Expires 30 Nov 2026', sub: 'the application said 2027', color: C.red, at: at('m3-vision', 'It reads the food licence', 'thirtieth', -6), y: 700 }, meera: { pose: 'pointing', side: 'right', text: 'The scan says 2026!', at: at('m3-vision', 'It reads the food licence', 'though the application'), dur: 70 } }),
  S('m3-vision', 'It cuts out', 'It even catches', { src: 'v1label', mark: 'panelSettled', d: 0.1, whip: true, focus: { x: protein.x, y: protein.y - 80, w: 850, h: 700 }, callouts: [ring(protein, C.red, 4)], big: { text: 'Label 30% vs sheet 32%', sub: 'label panel cut out, then re-read', color: C.red, at: at('m3-vision', 'It cuts out', 'thirty percent', -6), y: 700 }, meera: { pose: 'thinking', side: 'left', text: '30 or 32?', at: at('m3-vision', 'It cuts out', 'where the sheet'), dur: 60 } }),
  S('m3-vision', 'It even catches', 'All before', { src: 'v1', mark: 'scans', d: 0.3, whip: true, focus: focusOn(price, 880, 110), callouts: [ring(price, C.red, 6)], big: { text: 'HP-D06: \u20B93,352 vs \u20B93,325', sub: 'price list vs sheet', color: C.red, at: 14, y: 700 } }),
  S('m3-vision', 'All before', 'end', { src: 'v1', mark: 'scans', d: 1.8, whip: true, meera: { pose: 'celebrating', side: 'right', text: 'Caught before listing!', at: 24, dur: 80 } }),
];

// The Run pages: one short look at each, labelled with what it takes off your plate. Words in the VO choose the cut.
const F = { x: 400, y: 20, w: 1060, h: 600 };
const run = (from: string | null, to: string, mark: string, tag: string, extra: Partial<Seg> = {}): Seg => S('m4-run', from, to, { src: 'montage', mark, d: 0.3, whip: true, focus: F, tag, tagSub: 'off your plate', ...extra });
const M4: Seg[] = [
  S('m4-run', null, 'It drafts my weekly', { src: 'montage', mark: 'run', d: 0.2, tag: 'Runs the category with you', focus: F }),
  run('It drafts my weekly', 'answers price-increase', 'run', 'Weekly vendor review: drafted', { d: 0.6 }),
  run('answers price-increase', 'chases late', 'price', 'Price-increase requests: answered', { meera: { pose: 'pointing', side: 'right', at: 20, dur: 50 } }),
  run('chases late', 'queues catalog', 'pos', 'Late PO follow-ups: chased'),
  run('queues catalog', 'plans promotions', 'catalog', 'Catalog fixes: queued'),
  run('plans promotions', 'watches competitor', 'promos', 'Promotions: planned'),
  run('watches competitor', 'and flags stock', 'watch', 'Competitor price watch', { meera: { pose: 'thinking', side: 'left', at: 14, dur: 50 } }),
  run('and flags stock', 'Every rule lives', 'inventory', 'Stock-outs and dead stock: flagged'),
  S('m4-run', 'Every rule lives', 'for pet, beauty', { src: 'montage', mark: 'rules', d: 0.3, whip: true, focus: F, tag: 'One playbook, your rules', tagSub: 'every rule editable' }),
  S('m4-run', 'for pet, beauty', 'end', { src: 'montage', mark: 'try', d: 0.3, whip: true, focus: F, tag: 'Pet, beauty, electronics, or your own', meera: { pose: 'celebrating', side: 'right', at: 24, dur: 60 } }),
];

export const M1Scene = () => <AppScene sceneId="m1-call" segs={M1} hours={[0.0, 0.3]} />;
export const M2Scene = () => <AppScene sceneId="m2-verifier" segs={M2} hours={[0.3, 0.55]} />;
export const M3Scene = () => <AppScene sceneId="m3-vision" segs={M3} hours={[0.55, 0.8]} />;
export const M4Scene = () => <AppScene sceneId="m4-run" segs={M4} hours={[0.8, 1.0]} />;
