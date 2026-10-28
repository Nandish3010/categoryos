// Mixes VO + synthesised SFX + music into out/audio/mix.wav (main film) and mix-x.wav (30 s X cut).
//
//  - Music: audio/music.wav (made by scripts/music.mjs) or audio/music.mp3 (your own track); .wav wins. No file = no music.
//  - The music is sidechain-ducked by the voice, about 9 dB under speech, with a slow-ish release so it breathes back in the gaps.
//  - Master: two-pass linear loudnorm to about -14 LUFS integrated, true peak -1 dBFS (the voice peaks around -1 dBFS).
//  - Also writes out/audio/music-ducked.wav (the music as heard in the mix) for level checks (scripts/audio-report.mjs).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { demoCues, xCues } from '../src/cues.js';

const root = path.resolve(import.meta.dirname, '..');
const FF = '/opt/homebrew/bin/ffmpeg';
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));
const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));
const outDir = path.join(root, 'out/audio');
fs.mkdirSync(outDir, { recursive: true });
const pick = (...names) => names.map((n) => path.join(root, 'audio', n)).find((f) => fs.existsSync(f));
const MUSIC_GAIN = 0.55; // music.wav is written at -3 dBFS peak; this is its level against the (loudness-normalised) voice
const SFX_GAIN = 0.5;
const VO_GAIN = 1.2;

const run = (args) => {
  const r = spawnSync(FF, ['-y', '-hide_banner', '-nostats', ...args], { encoding: 'utf8', maxBuffer: 1 << 28 });
  if (r.status !== 0) { console.error(r.stderr.slice(-2000)); process.exit(1); }
  return r.stderr;
};

function mix({ name, total, vo, cues, music, duck }) {
  const inputs = [];
  const chains = [];
  const sfxL = [];
  const voL = [];
  const addIn = (file, delaySec, gain, tag, isVo) => {
    const i = inputs.length / 2;
    inputs.push('-i', file);
    const ms = Math.max(0, Math.round(delaySec * 1000));
    chains.push(`[${i}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=${gain},adelay=${ms}|${ms}[${tag}${i}]`);
    (isVo ? voL : sfxL).push(`[${tag}${i}]`);
  };
  vo.forEach((v) => addIn(v.file, v.t, VO_GAIN, 'v', true));
  cues.forEach((c) => addIn(path.join(root, 'out/sfx', `${c.sfx}.wav`), c.t, c.gain * SFX_GAIN, 's', false));
  const parts = [];
  parts.push(`${sfxL.join('')}amix=inputs=${sfxL.length}:normalize=0:dropout_transition=0,apad=whole_dur=${total}[sfxbus]`);
  const mix = ['[sfxbus]'];
  if (voL.length) {
    parts.push(`${voL.join('')}amix=inputs=${voL.length}:normalize=0:dropout_transition=0,apad=whole_dur=${total}[vobus]`);
  }
  let stem = null;
  if (music) {
    inputs.push('-i', music);
    const mi = inputs.filter((x) => x === '-i').length - 1;
    parts.push(`[${mi}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=${MUSIC_GAIN},apad=whole_dur=${total},atrim=0:${total}[mus]`);
    if (voL.length && duck) {
      parts.push('[vobus]asplit=2[vomix][vosc]');
      // about 9 dB of gain reduction under speech: ratio 3 from a low threshold, quick attack, 450 ms release
      parts.push(`[mus][vosc]sidechaincompress=threshold=0.03:ratio=3:attack=25:release=450:knee=3:makeup=1[ducked]`);
      parts.push('[ducked]asplit=2[musmix][stem]');
      mix.push('[vomix]', '[musmix]');
      stem = '[stem]';
    } else {
      mix.push('[mus]');
    }
  } else if (voL.length) {
    mix.push('[vobus]');
  }
  parts.push(`${mix.join('')}amix=inputs=${mix.length}:normalize=0,atrim=0:${total}[pre]`);
  const pre = path.join(outDir, `${name}-pre.wav`);
  const maps = ['-map', '[pre]', '-c:a', 'pcm_f32le', pre];
  const stemFile = path.join(outDir, 'music-ducked.wav');
  if (stem) maps.push('-map', stem, '-c:a', 'pcm_f32le', stemFile);
  run([...inputs, '-filter_complex', [...chains, ...parts].join(';'), ...maps]);
  // two-pass linear loudnorm
  const target = 'I=-14:TP=-1:LRA=11';
  const log = run(['-i', pre, '-af', `loudnorm=${target}:print_format=json`, '-f', 'null', '-']);
  const m = JSON.parse(log.slice(log.lastIndexOf('{'), log.lastIndexOf('}') + 1));
  const lin = `loudnorm=${target}:measured_I=${m.input_i}:measured_TP=${m.input_tp}:measured_LRA=${m.input_lra}:measured_thresh=${m.input_thresh}:offset=${m.target_offset}:linear=true:print_format=summary`;
  run(['-i', pre, '-af', `${lin},alimiter=limit=0.89:level=false,aresample=44100`, '-ar', '44100', '-ac', '2', path.join(outDir, `${name}.wav`)]);
  fs.rmSync(pre, { force: true });
  fs.writeFileSync(path.join(outDir, `${name}-info.json`), JSON.stringify({ preInputLufs: +m.input_i, masterGainDb: +(-14 - m.input_i).toFixed(2), musicGain: MUSIC_GAIN }, null, 1));
  console.log(`mix ${name}: ${cues.length} sfx, ${vo.length} vo, music=${music ? path.basename(music) : 'none'}, pre-master ${m.input_i} LUFS -> -14`);
}

const total = T.total / T.fps;
mix({
  name: 'mix',
  total,
  vo: T.scenes.map((s) => ({ file: path.join(root, 'out/vo', `${s.id}.wav`), t: s.start / T.fps + s.voLead })),
  cues: demoCues(T, script),
  music: pick('music.wav', 'music.mp3'),
  duck: true,
});
mix({ name: 'mix-x', total: 30, vo: [], cues: xCues(), music: pick('music-x.wav', 'music-x.mp3'), duck: false });
