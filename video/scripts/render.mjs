// Usage: node scripts/render.mjs [demo|x|stills]  (stills = only the review stills of the main film)
// Renders both cuts with Remotion, muxes the mixed audio, and extracts review stills. Run after capture + vo + sfx + mix (see `make video`).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { phraseSec, slamLocalFrame } from '../src/voTime.js';
import { act1Times } from '../src/act1Timing.js';

const root = path.resolve(import.meta.dirname, '..');
const out = path.join(root, 'out');
const FF = '/opt/homebrew/bin/ffmpeg';
fs.mkdirSync(path.join(out, 'stills'), { recursive: true });

// Remotion serves static files from public/: link the generated assets there.
const pub = path.join(root, 'public');
fs.mkdirSync(pub, { recursive: true });
for (const [name, target] of [['meera', '../assets/meera'], ['captures', '../captures']]) {
  const link = path.join(pub, name);
  fs.rmSync(link, { recursive: true, force: true });
  fs.symlinkSync(target, link);
}

const run = (args) => execFileSync('npx', ['remotion', ...args], { cwd: root, stdio: 'inherit' });
const only = process.argv[2]; // 'demo' | 'x' | undefined
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));

if (!only || only === 'demo' || only === 'stills') {
  if (only !== 'stills') run(['render', 'src/index.ts', 'Demo', path.join(out, 'demo-silent.mp4'), '--codec=h264', '--crf=18', '--log=error']);
  if (only !== 'stills') execFileSync(FF, ['-y', '-loglevel', 'error', '-i', path.join(out, 'demo-silent.mp4'), '-i', path.join(out, 'audio/mix.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', path.join(out, 'categoryos-demo.mp4')]);
  // stills at the key beats
  // stills land on the words: scene start + the frame at which a phrase is spoken (+ a few frames for the animation to settle)
  const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));
  const ph = (id, phrase, plus = 30) => { const s = T.scenes.find((x) => x.id === id); return s.start + Math.round(phraseSec(T, script, id, phrase) * T.fps) + plus; };
  const stills = [['01-hook', 75], ['02-chaos', ph('a1-mid', 'A vendor is on the phone', 100)], ['03-buried', Math.round(act1Times(T, script).freeze * T.fps) + 24], ['04-slam', T.scenes.find((x) => x.id === 'a2-slam').start + slamLocalFrame(T, script) + 6],
    ['05-call-reject', ph('m1-call', 'under a tenth', 40)], ['06-say-next', ph('m1-call', 'set the target', 50)], ['07-verifier', ph('m2-verifier', 'two different dates', 40)], ['07b-198', ph('m2-verifier', 'one hundred and ninety-eight', 40)],
    ['08-vision', ph('m3-vision', 'thirtieth', 45)], ['08b-label', ph('m3-vision', 'thirty percent', 45)], ['08c-price', ph('m3-vision', 'It even catches', 50)],
    ['09-run-weekly', ph('m4-run', 'It drafts my weekly', 45)], ['09b-po', ph('m4-run', 'chases late', 45)], ['09c-catalog', ph('m4-run', 'queues catalog', 45)], ['09d-inventory', ph('m4-run', 'and flags stock', 45)],
    ['10-week', ph('a3-week', 'about a third', 120)], ['11-close', ph('a3-close', 'Try it', 40)]];
  for (const [n, f] of stills) run(['still', 'src/index.ts', 'Demo', path.join(out, 'stills', `${n}.png`), `--frame=${f}`, '--log=error']);
}
if (!only || only === 'x') {
  run(['render', 'src/index.ts', 'XCut', path.join(out, 'x-silent.mp4'), '--codec=h264', '--crf=18', '--log=error']);
  execFileSync(FF, ['-y', '-loglevel', 'error', '-i', path.join(out, 'x-silent.mp4'), '-i', path.join(out, 'audio/mix-x.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', path.join(out, 'categoryos-x-30s.mp4')]);
  for (const [n, f] of [['x1-hook', 60], ['x2-hero', 200], ['x3-verifier', 400], ['x4-week', 760]]) run(['still', 'src/index.ts', 'XCut', path.join(out, 'stills', `${n}.png`), `--frame=${f}`, '--log=error']);
}
console.log('rendered', fs.readdirSync(out).filter((f) => f.endsWith('.mp4')).join(' '));
