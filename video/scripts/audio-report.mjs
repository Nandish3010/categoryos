// Audio checks for the finished mix. Usage: node scripts/audio-report.mjs   (after vo, sfx, music, mix)
//  - per scene: VO length vs scene length, and the longest stretch without speech
//  - loudness (ebur128) and sample/true peak of the master, VO-only peak
//  - music RMS in speech windows vs gap windows, and how far the voice ducks it
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';

const root = path.resolve(import.meta.dirname, '..');
const FF = '/opt/homebrew/bin/ffmpeg';
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));
const SR = 44100;

// ---- timing ----
console.log('scene          VO     scene   longest no-VO gap inside / at the scene end');
const speech = []; // [a,b] seconds on the final timeline
const rows = [];
for (const s of T.scenes) {
  const t0 = s.start / T.fps;
  s.sentences.forEach((x) => speech.push([t0 + s.voLead + x.a, t0 + s.voLead + x.b]));
}
let maxGap = { gap: 0, at: 0 };
const gaps = [];
for (let i = 0; i < speech.length - 1; i++) gaps.push({ gap: speech[i + 1][0] - speech[i][1], at: speech[i][1] });
gaps.sort((a, b) => b.gap - a.gap);
maxGap = gaps[0];
for (const s of T.scenes) {
  const t0 = s.start / T.fps, t1 = (s.start + s.frames) / T.fps;
  const inGaps = s.sentences.slice(1).map((x, i) => x.a - s.sentences[i].b);
  rows.push(`${s.id.padEnd(13)} ${s.voSec.toFixed(1).padStart(5)}s ${(s.frames / T.fps).toFixed(1).padStart(6)}s   inner ${Math.max(0, ...inGaps).toFixed(2)}s   tail+lead ${(t1 - (t0 + s.voLead + s.sentences[s.sentences.length - 1].b)).toFixed(2)}s`);
}
console.log(rows.join('\n'));
console.log(`total ${(T.total / T.fps).toFixed(1)}s; VO covers ${speech.reduce((n, [a, b]) => n + b - a, 0).toFixed(1)}s`);
console.log('largest gaps without VO (s):', gaps.slice(0, 5).map((g) => `${g.gap.toFixed(2)}@${g.at.toFixed(1)}`).join('  '));

// ---- levels ----
const pcm = (file) => execFileSync(FF, ['-v', 'error', '-i', file, '-af', 'pan=mono|c0=0.5*c0+0.5*c1', '-f', 'f32le', '-ar', String(SR), '-'], { maxBuffer: 1 << 30 });
const asF32 = (b) => new Float32Array(b.buffer, b.byteOffset, Math.floor(b.length / 4));
const rms = (x, a, b) => { let s = 0, n = 0; for (let i = Math.max(0, Math.round(a * SR)); i < Math.min(x.length, Math.round(b * SR)); i++) { s += x[i] * x[i]; n++; } return n ? 20 * Math.log10(Math.sqrt(s / n) + 1e-9) : -99; };
const meanDb = (arr) => 10 * Math.log10(arr.reduce((n, d) => n + Math.pow(10, d / 10), 0) / arr.length);

const mixFile = path.join(root, 'out/audio/mix.wav');
const ebur = spawnSync(FF, ['-hide_banner', '-nostats', '-i', mixFile, '-af', 'ebur128=peak=true', '-f', 'null', '-'], { encoding: 'utf8' }).stderr;
const sum = ebur.slice(ebur.lastIndexOf('Summary'));
console.log('master:', ((sum.match(/I:\s+(\S+) LUFS/) || [])[1] ?? '?') + ' LUFS integrated,', ((sum.match(/LRA:\s+(\S+) LU/) || [])[1] ?? '?') + ' LU range, true peak', (sum.match(/Peak:\s+(\S+) dBFS/) || [])[1] ?? '?', 'dBFS');

const info = JSON.parse(fs.readFileSync(path.join(root, 'out/audio/mix-info.json'), 'utf8'));
const mix = asF32(pcm(mixFile));
let vp = 0;
for (const f of T.scenes.map((s) => path.join(root, 'out/vo', `${s.id}.wav`))) { const x = asF32(pcm(f)); for (let i = 0; i < x.length; i++) vp = Math.max(vp, Math.abs(x[i])); }
// VO gain in the mix = 1.2 (VO_GAIN) then the master gain
const voPeakDb = 20 * Math.log10(vp * 1.2) + info.masterGainDb;
console.log(`voice sample peak in the final mix: ${voPeakDb.toFixed(1)} dBFS (loudest scene)`);
console.log(`peak of the whole mix during speech: ${(20 * Math.log10(Math.max(...speech.flatMap(([a, b]) => { let m = 0; for (let i = Math.round(a * SR); i < Math.min(mix.length, Math.round(b * SR)); i++) m = Math.max(m, Math.abs(mix[i])); return [m]; })))).toFixed(1)} dBFS`);

const musicFile = fs.existsSync(path.join(root, 'audio/music.wav')) ? path.join(root, 'audio/music.wav') : null;
const stemFile = path.join(root, 'out/audio/music-ducked.wav');
if (musicFile && fs.existsSync(stemFile)) {
  const raw = asF32(pcm(musicFile)), duck = asF32(pcm(stemFile));
  const dB = info.masterGainDb + 20 * Math.log10(info.musicGain);
  const inSp = [], outSp = [], rawSp = [], rawOut = [];
  for (const [a, b] of speech) if (b - a > 0.8) { inSp.push(rms(duck, a + 0.3, b - 0.1) + info.masterGainDb); rawSp.push(rms(raw, a + 0.3, b - 0.1) + dB); }
  // gap windows: the real gaps in the VO that are at least 0.5 s wide (the buried freeze and the slam)
  for (let i = 0; i < speech.length - 1; i++) { const a = speech[i][1] + 0.1, b = speech[i + 1][0] - 0.05; if (b - a >= 0.25) { outSp.push(rms(duck, a + 0.1, b) + info.masterGainDb); rawOut.push(rms(raw, a + 0.1, b) + dB); } }
  const tail = T.total / T.fps;
  console.log(`music RMS as heard in the final mix: with speech ${meanDb(inSp).toFixed(1)} dBFS (un-ducked would be ${meanDb(rawSp).toFixed(1)}, so the voice ducks it ${(meanDb(rawSp) - meanDb(inSp)).toFixed(1)} dB)`);
  console.log(`                                   without speech (gaps >= 0.25 s) ${meanDb(outSp).toFixed(1)} dBFS, over the whole film ${(rms(duck, 0, tail) + info.masterGainDb).toFixed(1)} dBFS`);
}
