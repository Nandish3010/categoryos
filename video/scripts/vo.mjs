// Voiceover: for each scene use video/vo/<scene>.wav if it exists (your own recording), otherwise draft it with macOS `say -v Tara`.
// Writes out/vo/<scene>.wav and src/timing.json (scene durations in frames, driven by the VO lengths).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = path.resolve(import.meta.dirname, '..');
const FFMPEG = '/opt/homebrew/bin/ffmpeg';
const FFPROBE = '/opt/homebrew/bin/ffprobe';
const FPS = 30;
const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));
const outDir = path.join(root, 'out/vo');
fs.mkdirSync(outDir, { recursive: true });

const dur = (f) => parseFloat(execFileSync(FFPROBE, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString());
const scenes = [];
let start = 0;
for (const s of script.scenes) {
  const custom = path.join(root, 'vo', `${s.id}.wav`);
  const dst = path.join(outDir, `${s.id}.wav`);
  let source = 'tts';
  if (fs.existsSync(custom)) {
    fs.copyFileSync(custom, dst);
    source = 'custom';
  } else {
    const aiff = path.join(outDir, `${s.id}.aiff`);
    execFileSync('say', ['-v', script.voice, '-r', String(script.rate), '-o', aiff, s.vo]);
    execFileSync(FFMPEG, ['-y', '-loglevel', 'error', '-i', aiff, '-ar', '44100', '-ac', '1', dst]);
    fs.rmSync(aiff);
  }
  const vo = dur(dst);
  const lead = 0.35; // breath before the line
  const sec = Math.max(s.minSec, vo + lead + 0.55);
  const frames = Math.round(sec * FPS);
  scenes.push({ id: s.id, act: s.act, start, frames, voSec: vo, voLead: lead, source });
  start += frames;
}
fs.mkdirSync(path.join(root, 'src'), { recursive: true });
fs.writeFileSync(path.join(root, 'src/timing.json'), JSON.stringify({ fps: FPS, total: start, scenes }, null, 2));
console.log(`vo: ${scenes.length} scenes, ${(start / FPS).toFixed(1)}s total`, scenes.map((s) => `${s.id}:${(s.frames / FPS).toFixed(1)}(${s.source})`).join(' '));
