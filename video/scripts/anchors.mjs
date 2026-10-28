// Dev helper: print the VO-derived anchors (and fail loudly if a cue phrase is missing from the script). Usage: node scripts/anchors.mjs
import fs from 'node:fs';
import path from 'node:path';
import { anchors, demoCues } from '../src/cues.js';

const root = path.resolve(import.meta.dirname, '..');
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));
const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));
const a = anchors(T, script);
const r = (x) => (typeof x === 'number' ? +x.toFixed(2) : x);
console.log(JSON.stringify({ ...a, A: { ...Object.fromEntries(Object.entries(a.A).map(([k, v]) => [k, Array.isArray(v) ? v.map((q) => (typeof q === 'number' ? r(q) : { ...q, t: r(q.t) })) : r(v)])) } }, null, 1));
console.log('cues:', demoCues(T, script).length);
