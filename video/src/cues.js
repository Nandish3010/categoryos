// Sound-effect cue sheet (seconds on the final timeline) and the music anchors. Used by scripts/mix.mjs and scripts/music.mjs.
// VO placement and every VO-driven moment come from timing.json + script.json (see voTime.js), so cues follow the words.
// Noise-based SFX are limited to three `whoosh` hits (buried, slam zoom, week melt); everything else is tonal (pops, ticks, blips, chimes).
import { act1Times, DASH_LEN, DASH_PRE } from './act1Timing.js';
import { phraseSec, slamLocalFrame } from './voTime.js';

/** Cut points inside the Act 2 scenes, as the VO phrase on which the picture changes (kept in step with src/scenes/Act2.tsx). */
export const CUTS = {
  'm1-call': ['The vendor offers', 'Sounds like thirty-five', 'But it simulates', 'So it tells me', 'No spreadsheet'],
  'm2-verifier': ['In this live run', 'On two hundred'],
  'm3-vision': ['It reads the food licence', 'It cuts out', 'It even catches', 'All before'],
  'm4-run': ['It drafts my weekly', 'answers price-increase', 'chases late', 'queues catalog', 'plans promotions', 'watches competitor', 'and flags stock', 'Every rule lives', 'for pet, beauty'],
};
/** [phrase, offset seconds, sfx] where a big number / highlight lands. */
export const HITS = {
  'm1-call': [['under a tenth', 0.0, 'error'], ['set the target', 0.0, 'ding']],
  'm2-verifier': [['two different dates', 0.0, 'error'], ['one hundred and ninety-eight', 0.0, 'chime']],
  'm3-vision': [['thirtieth', 0.0, 'error'], ['thirty percent', 0.0, 'error'], ['It even catches', 0.4, 'error'], ['All before', 0.2, 'chime']],
};

/** Key moments (seconds on the final timeline) used by both the cue sheet and the music arrangement. */
export function anchors(T, script) {
  const fps = T.fps;
  const sc = (id) => T.scenes.find((s) => s.id === id);
  const at = (id, phrase, off = 0) => sc(id).start / fps + phraseSec(T, script, id, phrase) + off;
  const A = act1Times(T, script);
  const slam = sc('a2-slam').start / fps + slamLocalFrame(T, script) / fps;
  const week = sc('a3-week');
  const close = sc('a3-close');
  return {
    A,
    act1Mid: sc('a1-mid').start / fps,
    buried: A.buried, // Act 1 timeline starts at 0
    freeze: A.freeze,
    slamScene: sc('a2-slam').start / fps,
    slam,
    m1: sc('m1-call').start / fps,
    m2: sc('m2-verifier').start / fps,
    m3: sc('m3-vision').start / fps,
    m4: sc('m4-run').start / fps,
    weekStart: week.start / fps,
    melt: at('a3-week', 'Onboarding'),
    closeStart: close.start / fps,
    url: at('a3-close', 'Try it'),
    end: T.total / fps,
    // hero moments: the lead motif plays here
    hero: [
      [at('m1-call', 'But it simulates'), at('m1-call', 'No spreadsheet')],
      [at('m2-verifier', 'On two hundred'), sc('m2-verifier').start / fps + sc('m2-verifier').frames / fps],
      [at('m3-vision', 'It cuts out'), at('m3-vision', 'All before')],
      [at('a3-week', 'Onboarding', -0.2), week.start / fps + week.frames / fps],
    ],
  };
}

export function demoCues(T, script) {
  const fps = T.fps;
  const sc = (id) => T.scenes.find((s) => s.id === id);
  const cues = [];
  const add = (t, sfx, gain = 0.5) => cues.push({ t, sfx, gain });
  const an = anchors(T, script);
  const A = an.A;
  // --- Act 1: a few clock ticks, a pop per station, a soft tonal tock where each dash lands ---
  [0.05, 0.65, 1.25].forEach((t) => add(t, 'tick', 0.4));
  A.visits.forEach((v, i) => {
    const dashStart = A.dashStart[i];
    add(dashStart + (DASH_PRE + (i === 0 ? 18 : DASH_LEN)) / fps, 'tock', 0.35);
    add(v.t, A.visits.findIndex((x) => x.st === v.st) === i ? 'pop' : 'blip', 0.5);
  });
  add(A.inboxFull, 'blip', 0.5);
  add(A.stations[2] + 0.05, 'ring', 0.3);
  add(A.stations[4] + 0.05, 'alert', 0.28);
  A.rainWps.forEach((w) => add(w.t + (DASH_PRE + 16) / fps, 'tock', 0.3));
  for (let t = A.notesStart + 0.3; t < A.M - 0.3; t += 0.8) add(t, 'tock', 0.18);
  add(A.buried, 'thud', 0.85);
  add(A.buried + 0.04, 'whoosh', 0.5); // key transition 1: the avalanche
  add(A.freeze, 'error', 0.35);
  // --- slam ---
  const s = an.slamScene;
  add(s + 26 / fps, 'pop', 0.5); // the button pops up
  add(s + 1.4, 'thud', 0.5); // she lands
  add(an.slam, 'slam', 0.9);
  add(an.slam + 0.05, 'whoosh', 0.55); // key transition 2: zoom-through
  add(an.slam + 100 / fps, 'chime', 0.45);
  // --- Act 2 ---
  for (const [id, phrases] of Object.entries(CUTS)) {
    const t0 = sc(id).start / fps;
    phrases.forEach((p) => add(t0 + phraseSec(T, script, id, p) - 0.02, id === 'm4-run' ? 'blip' : 'tock', id === 'm4-run' ? 0.4 : 0.35));
  }
  for (const [id, hits] of Object.entries(HITS)) {
    const t0 = sc(id).start / fps;
    hits.forEach(([p, off, sfx]) => add(t0 + phraseSec(T, script, id, p) + off, sfx, 0.45));
  }
  // --- Act 3: blocks turn green as each module is named ---
  const w = sc('a3-week');
  const w0 = w.start / fps;
  ['Onboarding', 'weekly reviews', 'catalog fixes', 'purchase-order', 'about a third'].forEach((p, i) => add(w0 + phraseSec(T, script, 'a3-week', p) + 0.05, i === 0 ? 'chime' : 'blip', i === 0 ? 0.55 : 0.45));
  add(an.melt - 0.1, 'whoosh', 0.45); // key transition 3: red becomes green
  const cl = sc('a3-close');
  for (let i = 0; i < 5; i++) add((cl.start + 10 + i * 6) / fps, 'pop', 0.4);
  add(an.url, 'chime', 0.6);
  add(an.url + 0.02, 'pluck', 0.4);
  return cues;
}

export function xCues() {
  const cues = [];
  const add = (t, sfx, gain = 0.5) => cues.push({ t, sfx, gain });
  [0.05, 0.4, 0.8].forEach((t) => add(t, 'tick', 0.4));
  [0.6, 1.5, 2.4].forEach((t) => add(t, 'tock', 0.35));
  add(2.0, 'ring', 0.3); add(4.5, 'thud', 0.8); add(4.55, 'whoosh', 0.45);
  [4.6, 8.8, 12.2, 15.8, 19, 23.5, 27].forEach((t) => add(t, 'tock', 0.4));
  add(5.2, 'error', 0.5); add(9.4, 'ding', 0.5); add(12.9, 'ding', 0.5); add(16.5, 'error', 0.5);
  [19.2, 20.1, 21.0, 21.9, 22.8].forEach((t) => add(t, 'blip', 0.4));
  add(24.0, 'chime', 0.7); add(27.3, 'pop', 0.5); add(28.0, 'chime', 0.6);
  return cues;
}
