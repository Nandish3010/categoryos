// Voiceover. Per scene: video/vo/<scene>.wav wins (your own recording, used as-is). Otherwise the line is synthesised
// SENTENCE BY SENTENCE (per-sentence rate and pitch, emphasis on key words, short breaths between sentences),
// joined, and lightly post-processed with ffmpeg so it sits less dry and synthetic.
//
// Voice engine (first match wins): video/vo/<scene>.wav, else video/tools/tts.sh called as `tts.sh "<scene text>" <out.wav>`
// (Kokoro-82M ships there; replace it with any TTS, no code change; script.json "voice"/"speed" go to it as KOKORO_VOICE/KOKORO_SPEED),
// else macOS `say -v Tara` sentence by sentence with prosody tweaks.
//
// Writes out/vo/<scene>.wav and src/timing.json (scene durations and per-sentence timing, driven by the VO lengths).
// Set VO_POST=0 to skip the ffmpeg polish (raw sentence concat), VO_LEGACY=1 for the old one-paragraph `say` render.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { splitSentences } from '../src/voTime.js';

const root = path.resolve(import.meta.dirname, '..');
const FFMPEG = '/opt/homebrew/bin/ffmpeg';
const FFPROBE = '/opt/homebrew/bin/ffprobe';
const FPS = 30;
const LEAD = 0.15; // seconds of music/air before the first word of a scene
const TAIL = 0.25; // seconds after the last word (scene length = VO + LEAD + TAIL, unless a scene sets tailSec)
const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));
const outDir = path.join(root, 'out/vo');
const work = path.join(root, 'out/vo/_work');
fs.mkdirSync(work, { recursive: true });
const ttsHook = path.join(root, 'tools/tts.sh');
const useHook = fs.existsSync(ttsHook) && process.env.VO_ENGINE !== "say";
if (useHook) { process.env.KOKORO_VOICE = script.voice; process.env.KOKORO_SPEED = String(script.speed ?? 1); }
const POST = process.env.VO_POST !== '0';
const LEGACY = process.env.VO_LEGACY === '1';

const ff = (args) => execFileSync(FFMPEG, ['-y', '-loglevel', 'error', ...args]);
const dur = (f) => parseFloat(execFileSync(FFPROBE, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString());

// ---- per-sentence delivery ----
const wc = (s) => s.split(/\s+/).filter(Boolean).length;

/** Words per minute for one sentence: short punchy lines a touch slower, long ones a touch quicker, plus a deterministic wobble. */
function rateFor(sentence, i, base) {
  const n = wc(sentence);
  let r = base + [0, 3, -2, 2, -3, 1][i % 6];
  if (n <= 4) r -= 8;
  else if (n <= 8) r -= 3;
  else if (n >= 20) r += 4;
  if (/\?$/.test(sentence)) r -= 4;
  return Math.max(160, Math.min(190, r));
}

/** Markup for `say`: rate, a little pitch movement on questions/exclamations, emphasis on key words, a breath mid-way in long sentences. */
function sayMarkup(sentence, i, emph, base) {
  let t = sentence;
  for (const phrase of emph) {
    const idx = t.indexOf(phrase);
    if (idx < 0) continue;
    const words = phrase.split(' ');
    const head = words.slice(0, -1).join(' ');
    const last = words[words.length - 1];
    const at = idx + (head ? head.length + 1 : 0);
    t = `${t.slice(0, at)}[[emph +]] ${last}${t.slice(at + last.length)}`;
  }
  if (wc(sentence) > 14) {
    // a short breath after the comma nearest the middle
    const commas = [...t.matchAll(/,\s/g)].map((m) => m.index + 1);
    if (commas.length) {
      const mid = t.length / 2;
      const c = commas.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a));
      t = `${t.slice(0, c)} [[slnc 70]]${t.slice(c)}`;
    }
  }
  const pitch = /\?$/.test(sentence) ? '[[pbas +3]] ' : /!$/.test(sentence) ? '[[pbas +2]] ' : i === 0 ? '[[pbas +1]] ' : '';
  return `[[rate ${rateFor(sentence, i, base)}]] ${pitch}${t}`;
}

// trim leading and trailing silence (the trailing trim runs on the reversed stream; stop_periods would cut at the first inner pause)
const trimEdges = 'silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.02,areverse,silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.05,areverse';

function synthSentence(sentence, i, emph, base, dst) {
  const aiff = path.join(work, 'raw.aiff');
  execFileSync('say', ['-v', script.sayVoice ?? 'Tara', '-o', aiff, sayMarkup(sentence, i, emph, base)]);
  ff(['-i', aiff, '-af', trimEdges, '-ar', '44100', '-ac', '1', dst]);
}

function silence(sec, dst) {
  ff(['-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', sec.toFixed(3), dst]);
}

// De-essed, gently compressed, presence-lifted, short-room-reverb polish. Everything is mild: the aim is "less dry", not "effect".
const POLISH = [
  'highpass=f=80',
  'equalizer=f=3000:t=q:w=0.9:g=2', // presence
  'equalizer=f=250:t=q:w=1:g=-1.2', // a little less boxiness
  'acompressor=threshold=-20dB:ratio=1.8:attack=12:release=140:makeup=2',
  'deesser=i=0.35:m=0.5:f=0.5',
  'apad=pad_dur=0.12',
  'aecho=0.85:0.9:23|47:0.10|0.06', // two very short early reflections (about a small room), low mix
  'loudnorm=I=-19:TP=-1.5:LRA=7',
  'aresample=44100',
].join(',');

function renderScene(s) {
  const sentences = splitSentences(s.vo);
  const parts = [];
  const timing = [];
  let t = 0;
  sentences.forEach((sent, i) => {
    const seg = path.join(work, `${s.id}.s${i}.wav`);
    synthSentence(sent, i, s.emph ?? [], script.rate, seg);
    const d = dur(seg);
    timing.push({ a: +t.toFixed(3), b: +(t + d).toFixed(3) });
    parts.push(seg);
    t += d;
    if (i < sentences.length - 1) {
      // breath between sentences (120-200 ms): a bit longer after a short sentence
      const gap = (script.breathMs ?? 160) / 1000 + (wc(sent) <= 4 ? 0.04 : 0) + (i % 3 === 1 ? -0.02 : 0);
      const g = path.join(work, `${s.id}.g${i}.wav`);
      silence(gap, g);
      parts.push(g);
      t += gap;
    }
  });
  const list = path.join(work, `${s.id}.txt`);
  fs.writeFileSync(list, parts.map((p) => `file '${p}'`).join('\n'));
  const dry = path.join(work, `${s.id}.dry.wav`);
  ff(['-f', 'concat', '-safe', '0', '-i', list, '-ar', '44100', '-ac', '1', dry]);
  return { dry, timing, voSec: dur(dry) };
}

// Light polish for a neural voice: high-pass, gentle compression, loudness. No reverb or EQ colour: it is already natural.
const POLISH_NEURAL = 'highpass=f=70,acompressor=threshold=-22dB:ratio=1.8:attack=15:release=160:makeup=1.5,loudnorm=I=-19:TP=-1.5:LRA=9,aresample=44100';

/** Sentence boundaries of a single-take VO: the (n-1) longest pauses, else a character-share estimate. */
function sentenceTiming(file, sentences, voSec) {
  const total = sentences.reduce((n, x) => n + x.length, 0);
  const share = () => { let t = 0; return sentences.map((x) => { const a = t; t += (x.length / total) * voSec; return { a: +a.toFixed(3), b: +t.toFixed(3) }; }); };
  if (sentences.length < 2) return share();
  const log = spawnSync(FFMPEG, ['-hide_banner', '-nostats', '-i', file, '-af', 'silencedetect=n=-36dB:d=0.12', '-f', 'null', '-'], { encoding: 'utf8' }).stderr || '';
  const sil = [...log.matchAll(/silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+) \| silence_duration: ([\d.]+)/g)]
    .map((m) => ({ a: +m[1], b: +m[2], d: +m[3] }))
    .filter((x) => x.a > 0.2 && x.b < voSec - 0.1);
  if (sil.length < sentences.length - 1) return share();
  // the longest n-1 pauses, in time order, approximate the sentence ends (Kokoro pauses longest at full stops)
  const cuts = [...sil].sort((x, y) => y.d - x.d).slice(0, sentences.length - 1).sort((x, y) => x.a - y.a);
  // sanity: each cut should be near its character-share position (within 35% of the scene); otherwise fall back
  const est = share();
  if (cuts.some((c, i) => Math.abs((c.a + c.b) / 2 - est[i].b) > voSec * 0.35)) return est;
  return sentences.map((_, i) => ({ a: +(i === 0 ? 0 : cuts[i - 1].b).toFixed(3), b: +(i === sentences.length - 1 ? voSec : cuts[i].a).toFixed(3) }));
}

const scenes = [];
let start = 0;
for (const s of script.scenes) {
  const custom = path.join(root, 'vo', `${s.id}.wav`);
  const dst = path.join(outDir, `${s.id}.wav`);
  let source = 'tts';
  let voSec;
  let sentTiming;
  if (fs.existsSync(custom)) {
    fs.copyFileSync(custom, dst);
    source = 'custom';
    voSec = dur(dst);
    // no sentence timing for a recording: spread by character share
    const sents = splitSentences(s.vo);
    const total = sents.reduce((n, x) => n + x.length, 0);
    let t = 0;
    sentTiming = sents.map((x) => { const a = t; t += (x.length / total) * voSec; return { a: +a.toFixed(3), b: +t.toFixed(3) }; });
  } else if (useHook && !LEGACY) {
    const raw = path.join(work, `${s.id}.neural.wav`);
    fs.rmSync(raw + '.json', { force: true });
    execFileSync('bash', [ttsHook, s.vo, raw], { stdio: ['ignore', 'inherit', 'inherit'] });
    ff(['-i', raw, '-af', POST ? POLISH_NEURAL : 'aresample=44100', '-ar', '44100', '-ac', '1', dst]);
    voSec = dur(dst);
    const sents = splitSentences(s.vo);
    // tts.sh may write <out>.json with per-sentence {a,b} (kokoro_tts.py does); otherwise estimate from pauses
    const side = raw + '.json';
    const spans = fs.existsSync(side) ? JSON.parse(fs.readFileSync(side, 'utf8')) : null;
    sentTiming = spans && spans.length === sents.length ? spans : sentenceTiming(dst, sents, voSec);
    source = 'kokoro:' + script.voice;
  } else if (LEGACY) {
    const aiff = path.join(work, 'legacy.aiff');
    execFileSync('say', ['-v', script.sayVoice ?? 'Tara', '-r', '172', '-o', aiff, s.vo]);
    ff(['-i', aiff, '-ar', '44100', '-ac', '1', dst]);
    voSec = dur(dst);
    const sents = splitSentences(s.vo);
    const total = sents.reduce((n, x) => n + x.length, 0);
    let t = 0;
    sentTiming = sents.map((x) => { const a = t; t += (x.length / total) * voSec; return { a: +a.toFixed(3), b: +t.toFixed(3) }; });
    source = 'legacy';
  } else {
    const r = renderScene(s);
    voSec = r.voSec;
    sentTiming = r.timing;
    if (POST) ff(['-i', r.dry, '-af', POLISH, '-ar', '44100', '-ac', '1', dst]);
    else fs.copyFileSync(r.dry, dst);
  }
  let clip = null;
  if (s.clip) {
    // a pre-recorded clip (the live-ASR vendor audio) follows the spoken lines inside the same scene wav; it counts as speech for ducking and gap checks
    const cw = path.join(work, `${s.id}.clip.wav`);
    ff(['-i', path.join(root, s.clip.file), '-af', 'loudnorm=I=-19:TP=-1.5:LRA=9,aresample=44100', '-ar', '44100', '-ac', '1', cw]);
    const gw = path.join(work, `${s.id}.clipgap.wav`);
    silence(s.clip.gap ?? 0.35, gw);
    const list = path.join(work, `${s.id}.cliplist.txt`);
    const base = path.join(work, `${s.id}.base.wav`);
    fs.copyFileSync(dst, base);
    fs.writeFileSync(list, [base, gw, cw].map((f) => `file '${f}'`).join('\n'));
    ff(['-f', 'concat', '-safe', '0', '-i', list, '-ar', '44100', '-ac', '1', dst]);
    const a = voSec + (s.clip.gap ?? 0.35);
    voSec = dur(dst);
    clip = { a: +a.toFixed(3), b: +voSec.toFixed(3) };
  }
  const sec = Math.max(s.minSec, voSec + LEAD + (s.tailSec ?? TAIL));
  const frames = Math.round(sec * FPS);
  scenes.push({ id: s.id, act: s.act, start, frames, voSec: +voSec.toFixed(3), voLead: LEAD, source, sentences: sentTiming, ...(clip ? { clip } : {}) });
  start += frames;
}
fs.writeFileSync(path.join(root, 'src/timing.json'), JSON.stringify({ fps: FPS, total: start, scenes }, null, 2));
console.log(`vo: ${scenes.length} scenes, ${(start / FPS).toFixed(1)}s total${useHook ? ' (tools/tts.sh)' : ''}`);
for (const s of scenes) console.log(`  ${s.id.padEnd(12)} vo ${s.voSec.toFixed(2)}s  scene ${(s.frames / FPS).toFixed(2)}s  (${s.source})`);
