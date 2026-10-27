// Sound-effect cue sheet (seconds on the final timeline). Used by scripts/mix.mjs. VO placement comes from timing.json.
import { act1Times, DASH_LEN, DASH_PRE } from './act1Timing.js';

export const SEG_BOUNDS = {
  'm1-call': [0, 0.15, 0.34, 0.52, 0.76],
  'm2-verifier': [0, 0.2, 0.62],
  'm3-vision': [0, 0.34, 0.67],
  'm4-run': [0, 1 / 7, 2 / 7, 3 / 7, 4 / 7, 5 / 7, 6 / 7],
};
// frame offsets (inside a segment) where a big number / highlight lands -> ding or alert
export const CHIP_HITS = {
  'm1-call': [[0.52, 26, 'error'], [0.76, 24, 'ding']],
  'm2-verifier': [[0.2, 30, 'ding'], [0.62, 8, 'chime']],
  'm3-vision': [[0, 20, 'error'], [0.34, 20, 'error'], [0.67, 20, 'error'], [0.67, 45, 'chime']],
};

export function demoCues(T) {
  const fps = T.fps;
  const sc = (id) => T.scenes.find((s) => s.id === id);
  const cues = [];
  const add = (t, sfx, gain = 0.5) => cues.push({ t, sfx, gain });
  const a = sc('a1-intro'), b = sc('a1-mid'), c = sc('a1-end');
  const t0 = a.start / fps;
  const A = act1Times(a.frames / fps, b.frames / fps, c.frames / fps);
  [0.05, 0.35, 0.65, 0.95, 1.25].forEach((t) => add(t0 + t, 'tick', 0.5));
  A.dashStart.forEach((s, i) => {
    add(t0 + s + DASH_PRE / fps, 'whoosh-short', 0.55);
    add(t0 + s + (DASH_PRE + (i === 0 ? 18 : DASH_LEN)) / fps, 'thud', 0.5);
  });
  A.rainWps.forEach((w) => { add(t0 + w.t, 'whoosh-short', 0.55); add(t0 + w.t + 0.55, 'thud', 0.45); });
  A.stations.forEach((s) => add(t0 + s, 'pop', 0.6));
  add(t0 + A.stations[2], 'ring', 0.4);
  add(t0 + A.stations[4], 'alert', 0.35);
  for (let t = A.notesStart; t < A.M; t += 0.55) add(t0 + t, 'rustle', 0.35);
  add(t0 + A.buried, 'thud', 0.9);
  add(t0 + A.buried + 0.05, 'rustle', 0.6);
  add(t0 + A.freeze, 'error', 0.4);
  const s = sc('a2-slam').start / fps;
  add(s + 0.3, 'rustle', 0.6);
  add(s + 0.45, 'whoosh-short', 0.5);
  add(s + 1.4, 'thud', 0.6);
  add(s + 62 / fps, 'slam', 0.9);
  add(s + 66 / fps, 'whoosh', 0.8);
  add(s + 100 / fps, 'chime', 0.5);
  for (const [id, bounds] of Object.entries(SEG_BOUNDS)) {
    const sceneS = sc(id);
    bounds.forEach((f, i) => { if (i > 0) add((sceneS.start + f * sceneS.frames) / fps, 'whoosh-short', 0.45); });
    (CHIP_HITS[id] || []).forEach(([f, off, sfx]) => add((sceneS.start + f * sceneS.frames + off) / fps, sfx, 0.5));
  }
  const w = sc('a3-week');
  add((w.start + w.frames * 0.3) / fps, 'chime', 0.7);
  for (let i = 0; i < 12; i++) add((w.start + 2 + i * 1.6) / fps, 'tick', 0.25);
  const cl = sc('a3-close');
  for (let i = 0; i < 5; i++) add((cl.start + 10 + i * 6) / fps, 'pop', 0.5);
  add((cl.start + cl.frames * 0.55) / fps, 'chime', 0.7);
  return cues;
}

export function xCues() {
  const cues = [];
  const add = (t, sfx, gain = 0.5) => cues.push({ t, sfx, gain });
  [0.05, 0.4, 0.8].forEach((t) => add(t, 'tick', 0.5));
  [0.6, 1.5, 2.4].forEach((t) => add(t, 'whoosh-short', 0.5));
  add(2.0, 'ring', 0.35); add(4.5, 'thud', 0.8);
  [4.6, 8.8, 12.2, 15.8, 19, 23.5, 27].forEach((t) => add(t, 'whoosh-short', 0.55));
  add(5.2, 'error', 0.5); add(9.4, 'ding', 0.5); add(12.9, 'ding', 0.5); add(16.5, 'error', 0.5);
  [19.2, 20.1, 21.0, 21.9, 22.8].forEach((t) => add(t, 'pop', 0.4));
  add(24.0, 'chime', 0.7); add(27.3, 'pop', 0.5); add(28.0, 'chime', 0.6);
  return cues;
}
