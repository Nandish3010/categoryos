// Mixes VO + synthesised SFX (+ optional music with ducking) into out/audio/mix.wav (main) and mix-x.wav (30 s X cut).
// Music: drop a file at video/audio/music.mp3 and it is ducked under the VO (sidechain compression). No file = no music.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { demoCues, xCues } from '../src/cues.js';

const root = path.resolve(import.meta.dirname, '..');
const FF = '/opt/homebrew/bin/ffmpeg';
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));
const outDir = path.join(root, 'out/audio');
fs.mkdirSync(outDir, { recursive: true });
const music = path.join(root, 'audio/music.mp3');
const hasMusic = fs.existsSync(music);

function mix({ name, total, vo, cues }) {
  const inputs = [];
  const chains = [];
  const labels = [];
  const voLabels = [];
  const addIn = (file, delaySec, gain, tag, isVo) => {
    const i = inputs.length / 2;
    inputs.push('-i', file);
    const ms = Math.max(0, Math.round(delaySec * 1000));
    chains.push(`[${i}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=${gain},adelay=${ms}|${ms}[${tag}${i}]`);
    (isVo ? voLabels : labels).push(`[${tag}${i}]`);
  };
  vo.forEach((v) => addIn(v.file, v.t, 1.35, 'v', true));
  cues.forEach((c) => addIn(path.join(outDir, '..', 'sfx', `${c.sfx}.wav`), c.t, c.gain * 0.55, 's', false));
  const parts = [];
  let voBus = null;
  if (voLabels.length) {
    parts.push(`${voLabels.join('')}amix=inputs=${voLabels.length}:normalize=0:dropout_transition=0,apad=whole_dur=${total}[vobus]`);
    voBus = '[vobus]';
  }
  parts.push(`${labels.join('')}amix=inputs=${labels.length}:normalize=0:dropout_transition=0,apad=whole_dur=${total}[sfxbus]`);
  let final;
  if (hasMusic && voBus) {
    inputs.push('-stream_loop', '-1', '-i', music);
    const mi = inputs.filter((x) => x === '-i').length - 1;
    parts.push(`${voBus}asplit=2[vomix][vosc]`);
    parts.push(`[${mi}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.5[mus]`);
    parts.push(`[mus][vosc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400:makeup=1[ducked]`); // about -18 dB under speech
    parts.push(`[vomix][sfxbus][ducked]amix=inputs=3:normalize=0,atrim=0:${total}[pre]`);
  } else if (voBus) {
    parts.push(`${voBus}[sfxbus]amix=inputs=2:normalize=0,atrim=0:${total}[pre]`);
  } else {
    parts.push(`[sfxbus]atrim=0:${total}[pre]`);
  }
  parts.push(`[pre]loudnorm=I=-16:TP=-1.5:LRA=11[out]`);
  final = '[out]';
  try { execFileSync(FF, ['-y', '-loglevel', 'error', ...inputs, '-filter_complex', [...chains, ...parts].join(';'), '-map', final, '-ar', '44100', '-ac', '2', path.join(outDir, `${name}.wav`)], { maxBuffer: 1 << 28, stdio: ['ignore', 'ignore', 'pipe'] }); } catch (e) { console.error(String(e.stderr).slice(-1500)); process.exit(1); }
  console.log(`mix ${name}: ${cues.length} sfx, ${vo.length} vo, music=${hasMusic}`);
}

const total = T.total / T.fps;
mix({
  name: 'mix',
  total,
  vo: T.scenes.map((s) => ({ file: path.join(root, 'out/vo', `${s.id}.wav`), t: s.start / T.fps + s.voLead })),
  cues: demoCues(T),
});
mix({ name: 'mix-x', total: 30, vo: [], cues: xCues() });
