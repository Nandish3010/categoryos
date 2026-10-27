// Renders both cuts with Remotion, muxes the mixed audio, and extracts review stills. Run after capture + vo + sfx + mix (see `make video`).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

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

if (!only || only === 'demo') {
  run(['render', 'src/index.ts', 'Demo', path.join(out, 'demo-silent.mp4'), '--codec=h264', '--crf=18', '--log=error']);
  execFileSync(FF, ['-y', '-loglevel', 'error', '-i', path.join(out, 'demo-silent.mp4'), '-i', path.join(out, 'audio/mix.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', path.join(out, 'categoryos-demo.mp4')]);
  // stills at the key beats
  const at = (id, frac = 0.5) => { const s = T.scenes.find((x) => x.id === id); return Math.round(s.start + s.frames * frac); };
  const stills = [['01-hook', 75], ['02-chaos', at('a1-mid', 0.55)], ['03-buried', at('a1-end', 0.7)], ['04-slam', at('a2-slam', 0.5)], ['05-call-reject', at('m1-call', 0.64)], ['06-say-next', at('m1-call', 0.92)], ['07-verifier', at('m2-verifier', 0.45)], ['08-vision', at('m3-vision', 0.5)], ['09-montage', at('m4-run', 0.55)], ['10-week', at('a3-week', 0.8)], ['11-close', at('a3-close', 0.8)]];
  for (const [n, f] of stills) run(['still', 'src/index.ts', 'Demo', path.join(out, 'stills', `${n}.png`), `--frame=${f}`, '--log=error']);
}
if (!only || only === 'x') {
  run(['render', 'src/index.ts', 'XCut', path.join(out, 'x-silent.mp4'), '--codec=h264', '--crf=18', '--log=error']);
  execFileSync(FF, ['-y', '-loglevel', 'error', '-i', path.join(out, 'x-silent.mp4'), '-i', path.join(out, 'audio/mix-x.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', path.join(out, 'categoryos-x-30s.mp4')]);
  for (const [n, f] of [['x1-hook', 60], ['x2-hero', 200], ['x3-verifier', 400], ['x4-week', 760]]) run(['still', 'src/index.ts', 'XCut', path.join(out, 'stills', `${n}.png`), `--frame=${f}`, '--log=error']);
}
console.log('rendered', fs.readdirSync(out).filter((f) => f.endsWith('.mp4')).join(' '));
