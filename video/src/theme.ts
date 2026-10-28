import { loadFont as loadDisplay } from '@remotion/google-fonts/SpaceGrotesk';
import { loadFont as loadText } from '@remotion/google-fonts/DMSans';
import { Easing, interpolate, spring } from 'remotion';
import timing from './timing.json';
import script from '../script.json';
import { phraseSec, sentenceSec } from './voTime.js';

export const C = {
  bg: '#0F1117', surface: '#171A23', surface2: '#1E2230', text: '#EDEEF2', dim: '#A6ABB8',
  blue: '#6EA8FE', orange: '#F5A962', yellow: '#F5C542', green: '#4ADE80', red: '#F87171',
};
export const display = loadDisplay('normal', { weights: ['500', '700'], subsets: ['latin'] }).fontFamily;
export const body = loadText('normal', { weights: ['400', '500', '700'], subsets: ['latin'] }).fontFamily;

export const FPS = 30;
export const W = 1920;
export const H = 1080;
export const MARGIN_X = 96;
export const MARGIN_Y = 72;

// Consistent easing vocabulary: ease-out for entrances, ease-in for exits, in-out for travel.
export const E = {
  out: Easing.bezier(0.16, 1, 0.3, 1),
  in: Easing.bezier(0.7, 0, 0.84, 0),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
};

export type SceneT = { id: string; act: number; start: number; frames: number; voSec: number; voLead: number; source: string; sentences: { a: number; b: number }[] };
export const T = timing as { fps: number; total: number; scenes: SceneT[] };
export const sceneOf = (id: string): SceneT => {
  const s = T.scenes.find((x) => x.id === id);
  if (!s) throw new Error('no scene ' + id);
  return s;
};

/** 0..1 progress of frame f between a and b with easing */
export const prog = (f: number, a: number, b: number, ease: (t: number) => number = E.out) =>
  interpolate(f, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease });

export const pop = (f: number, at: number, fps = FPS, damping = 12, stiffness = 170, mass = 0.7) =>
  f < at ? 0 : spring({ frame: f - at, fps, config: { damping, stiffness, mass } });

export const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
export const rnd = (seed: number) => {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};


/** Local frame (inside scene `id`) at which `phrase` (spoken spelling) begins to be spoken. */
export const phraseFrame = (id: string, phrase: string, nth = 0) => Math.round(phraseSec(timing, script, id, phrase, nth) * FPS);
/** Local frame at which sentence i of scene `id` starts (or ends). */
export const sentenceFrame = (id: string, i: number, end = false) => Math.round(sentenceSec(timing, id, i, end) * FPS);
