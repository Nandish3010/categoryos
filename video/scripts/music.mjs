// Original music bed, composed in code (no samples, no packages): writes audio/music.wav (main film) and audio/music-x.wav (30 s cut).
//
//   ~110 BPM, C major / A minor. Everything is additive sines with fast attack and exponential decay (electric piano, pluck, lead, sub bass),
//   a synthesised kick, a short tight clap and decaying filtered-noise hats. No pads, no noise beds, no reverb wash.
//
// Arrangement follows the colour script and the scene timing in src/timing.json:
//   Act 1  busier and tense: A minor (Am F Dm E), 16th hats, pulsing bass and a plucked arpeggio
//   buried the music drops out to a hush (held bass, a heartbeat kick, a soft tick)
//   riser  two bars of tonal rise and an accelerating clap roll, one beat of air, then
//   slam   the drop: kick, sub boom, bright chord stab into the main groove (C G Am F = the vi-IV-I-V loop, rotated to start on I)
//   Act 2  driving but sparse under dense VO (four on the floor, offbeat hats, syncopated bass, EP comping), denser for the Run montage,
//          and a simple lead motif on the hero moments
//   Act 3  warm resolve (soft kick, rolling EP, round bass, lead), and a final hit on the URL that rings out
//
// Usage: node scripts/music.mjs   (needs src/timing.json from scripts/vo.mjs)
import fs from 'node:fs';
import path from 'node:path';
import { anchors } from '../src/cues.js';

const root = path.resolve(import.meta.dirname, '..');
const SR = 44100;
const T = JSON.parse(fs.readFileSync(path.join(root, 'src/timing.json'), 'utf8'));
const script = JSON.parse(fs.readFileSync(path.join(root, 'script.json'), 'utf8'));

// ---------- small DSP kit ----------
const TAU = Math.PI * 2;
const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

/** RBJ biquad over a Float32Array, in place. type: 'lp' | 'hp' | 'bp' */
function biquad(buf, type, f, q = 0.707) {
  const w = (TAU * f) / SR, c = Math.cos(w), al = Math.sin(w) / (2 * q);
  let b0, b1, b2;
  if (type === 'lp') { b0 = (1 - c) / 2; b1 = 1 - c; b2 = (1 - c) / 2; }
  else if (type === 'hp') { b0 = (1 + c) / 2; b1 = -(1 + c); b2 = (1 + c) / 2; }
  else { b0 = al; b1 = 0; b2 = -al; }
  const a0 = 1 + al, a1 = (-2 * c) / a0, a2 = (1 - al) / a0;
  b0 /= a0; b1 /= a0; b2 /= a0;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < buf.length; i++) {
    const x = buf[i];
    const y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x; y2 = y1; y1 = y; buf[i] = y;
  }
  return buf;
}

function render({ total, A, name }) {
  const N = Math.ceil(total * SR);
  const bus = () => ({ L: new Float32Array(N), R: new Float32Array(N) });
  const B = { kick: bus(), clap: bus(), hat: bus(), bass: bus(), ep: bus(), pluck: bus(), lead: bus(), fx: bus() };
  const pump = new Float32Array(N).fill(1); // sidechain-style duck of the harmonic buses from the kick
  const rand = rng(1234);

  const put = (b, i, v, pan = 0) => { if (i < 0 || i >= N) return; b.L[i] += v * (1 - Math.max(0, pan)); b.R[i] += v * (1 + Math.min(0, pan)); };

  // ----- voices -----
  function kick(t, vel = 1, depth = 0.5) {
    const i0 = Math.round(t * SR), n = Math.round(0.4 * SR);
    let ph = 0;
    for (let k = 0; k < n; k++) {
      const tt = k / SR;
      ph += (TAU * (46 + 120 * Math.exp(-tt * 30))) / SR;
      const s = (Math.sin(ph) * Math.exp(-tt * 8) + 0.28 * Math.sin(TAU * 1700 * tt) * Math.exp(-tt * 320)) * vel * 0.95;
      put(B.kick, i0 + k, s);
    }
    const pn = Math.round(0.28 * SR);
    for (let k = 0; k < pn; k++) { const i = i0 + k; if (i < N) pump[i] = Math.min(pump[i], 1 - depth * vel * Math.exp(-(k / SR) / 0.085)); }
  }
  function clap(t, vel = 1) {
    const n = Math.round(0.2 * SR), tmp = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      const tt = k / SR;
      let e = Math.exp(-tt * 30) * (tt > 0.027 ? 1 : 0);
      for (const o of [0, 0.009, 0.018]) if (tt >= o && tt < o + 0.009) e = Math.max(e, Math.exp(-(tt - o) * 150));
      tmp[k] = (rand() * 2 - 1) * e;
    }
    biquad(tmp, 'bp', 1700, 1.1); biquad(tmp, 'hp', 600);
    const i0 = Math.round(t * SR);
    for (let k = 0; k < n; k++) put(B.clap, i0 + k, tmp[k] * vel * 1.8, 0.1);
  }
  function hat(t, vel = 1, open = false) {
    const n = Math.round((open ? 0.2 : 0.05) * SR), tmp = new Float32Array(n);
    for (let k = 0; k < n; k++) tmp[k] = (rand() * 2 - 1) * Math.exp(-(k / SR) * (open ? 20 : 75));
    biquad(tmp, 'hp', 7500); biquad(tmp, 'hp', 7500);
    const i0 = Math.round(t * SR);
    for (let k = 0; k < n; k++) put(B.hat, i0 + k, tmp[k] * vel * 0.9, 0.25);
  }
  /** sine-additive note into a bus. parts = [[harmonic, weight, decayRate]] */
  function tone(bus, t, midi, len, vel, parts, { att = 0.004, rel = 40, pan = 0, tail = 0.35, fm = 0 } = {}) {
    const f = mtof(midi), i0 = Math.round(t * SR), n = Math.round((len + tail) * SR);
    for (let k = 0; k < n; k++) {
      const tt = k / SR;
      let s = 0;
      for (const [h, w, d] of parts) s += w * Math.sin(TAU * f * h * tt + (fm ? fm * Math.sin(TAU * f * tt) * Math.exp(-tt * 30) : 0)) * Math.exp(-tt * d);
      const env = Math.min(1, tt / att) * (tt < len ? 1 : Math.exp(-(tt - len) * rel));
      put(bus, i0 + k, s * env * vel, pan);
    }
  }
  const EP = [[1, 1, 2.6], [2, 0.34, 3.6], [3, 0.12, 5.2], [4, 0.05, 7], [4.02, 0.045, 14]];
  const ep = (t, midi, len, vel, pan) => tone(B.ep, t, midi, len, vel * 0.55, EP, { att: 0.003, pan, fm: 0.35 });
  const PLUCK = [[1, 1, 11], [2, 0.5, 14], [3, 0.22, 20]];
  const pluck = (t, midi, vel, pan = 0) => tone(B.pluck, t, midi, 0.1, vel * 0.5, PLUCK, { att: 0.002, pan, tail: 0.25, rel: 30 });
  const LEAD = [[1, 1, 3.2], [2, 0.3, 4.5], [3, 0.14, 6]];
  const lead = (t, midi, len, vel) => tone(B.lead, t, midi, len, vel * 0.5, LEAD, { att: 0.006, rel: 22, pan: 0.05 });
  function bass(t, midi, len, vel) {
    const f = mtof(midi), i0 = Math.round(t * SR), n = Math.round((len + 0.12) * SR);
    for (let k = 0; k < n; k++) {
      const tt = k / SR, ph = TAU * f * tt;
      const env = Math.min(1, tt / 0.008) * Math.exp(-tt * 1.6) * (tt < len ? 1 : Math.exp(-(tt - len) * 45));
      put(B.bass, i0 + k, Math.tanh(1.4 * (Math.sin(ph) + 0.38 * Math.sin(2 * ph) + 0.12 * Math.sin(3 * ph))) * 0.7 * env * vel);
    }
  }
  function subBoom(t, vel = 1) {
    const i0 = Math.round(t * SR), n = Math.round(1.1 * SR);
    let ph = 0;
    for (let k = 0; k < n; k++) { const tt = k / SR; ph += (TAU * (38 + 90 * Math.exp(-tt * 7))) / SR; put(B.fx, i0 + k, Math.sin(ph) * Math.exp(-tt * 3.2) * vel * 0.9); }
  }
  function riser(t0, t1) {
    const i0 = Math.round(t0 * SR), n = Math.round((t1 - t0) * SR);
    let ph = 0, ph2 = 0;
    for (let k = 0; k < n; k++) {
      const u = k / n;
      const f = 180 * Math.exp(Math.log(2600 / 180) * Math.pow(u, 1.4));
      ph += (TAU * f) / SR; ph2 += (TAU * f * 1.4983) / SR; // a fifth above
      const trem = 0.65 + 0.35 * Math.sin(TAU * (4 + 20 * u * u) * (k / SR));
      put(B.fx, i0 + k, (Math.sin(ph) + 0.4 * Math.sin(ph2)) * Math.pow(u, 1.6) * trem * 0.32);
    }
  }
  // ----- harmony -----
  const CH = {
    Am: { v: [57, 60, 64, 67], r: 33, arp: [57, 60, 64, 67] }, F: { v: [57, 60, 65, 69], r: 29, arp: [60, 65, 69, 72] },
    Dm: { v: [57, 62, 65, 69], r: 38, arp: [62, 65, 69, 74] }, E: { v: [56, 59, 62, 64], r: 28, arp: [56, 59, 64, 68] },
    C: { v: [60, 64, 67, 71], r: 36, arp: [60, 64, 67, 72] }, G: { v: [59, 62, 67, 69], r: 31, arp: [59, 62, 67, 74] },
  };
  const PROG1 = ['Am', 'F', 'Dm', 'E']; // Act 1: minor-leaning, ends on the dominant
  const PROG2 = ['C', 'G', 'Am', 'F']; // from the slam: I V vi IV, i.e. the vi-IV-I-V loop starting on I
  const RISE = ['Dm', 'G'];
  // lead motif over two bars (beat, midi, length in beats): C major pentatonic fits every chord of the loop
  const MOTIF = [[0, 76, 0.75], [1, 79, 0.5], [1.5, 81, 0.5], [2, 79, 1], [3.5, 76, 0.5], [4, 74, 0.75], [5, 76, 0.5], [5.5, 79, 0.5], [6, 76, 1.5]];

  // ----- grid: bars anchored on the slam, tempo nudged so the URL hit also lands on a downbeat -----
  const slam = A.slam, url = A.url;
  const bars = Math.max(1, Math.round((url - slam) / (4 * (60 / 110))));
  const beat = (url - slam) / (4 * bars);
  const bar = beat * 4;
  const tb = (k) => slam + k * beat; // beat k (k=0 is the slam)
  const riserBars = A.riserBars ?? 2;
  const riserStart = slam - riserBars * bar;
  const hushStart = A.buried ?? Infinity; // exact time the avalanche lands
  const hushEnd = riserStart;
  const weekStart = A.weekStart;
  const m4 = A.m4, m4End = A.m4 + (A.m4Len ?? 23);
  const sec = (t) => (t >= url - 1e-6 ? 'ring' : t >= weekStart ? 'week' : t >= slam - 1e-6 ? 'groove' : t >= riserStart - 1e-6 ? 'riser' : t >= hushStart ? 'hush' : 'act1');
  const chordAt = (k, s) => { const j = Math.floor(k / 4); const m = ((j % 4) + 4) % 4; return CH[s === 'act1' || s === 'hush' ? PROG1[m] : s === 'riser' ? RISE[((j % 2) + 2) % 2] : PROG2[m]]; };
  const heroAt = (t) => (A.hero || []).some(([a, b]) => t >= a && t < b);
  const limit = (t, len) => { // clamp note lengths at section edges so nothing rings across a hard cut
    for (const e of [hushStart, slam, url, riserStart]) if (e > t + 1e-6 && e < t + len) len = e - t - 0.01;
    return Math.max(0.05, len);
  };

  const kStart = Math.floor((0 - slam) / beat) - 1, kEnd = Math.ceil((total - slam) / beat) + 1;
  for (let step = kStart * 4; step <= kEnd * 4; step++) {
    const k = step / 4; // beat position (quarter-beat resolution)
    const t = tb(k);
    if (t < 0 || t >= total) continue;
    const s = sec(t);
    const beatInBar = ((k % 4) + 4) % 4;
    const barIdx = Math.floor(k / 4);
    const isBeat = Number.isInteger(k);
    const e8 = ((Math.floor(k * 2) % 8) + 8) % 8; // 8th-note index inside two beats-of-four, always >= 0
    const s4 = ((step % 4) + 4) % 4;
    const eighth = Number.isInteger(k * 2);
    const ch = chordAt(k, s);
    const dense = s === 'groove' && (t < slam + 4 * bar || (t >= m4 && t < m4End)); // right after the drop, and the Run montage
    const sparse = s === 'groove' && !dense;
    const preRise = s === 'groove' || s === 'week';

    if (s === 'act1') {
      // tense, busy: soft kick on 1 and 3 with a pushed last 8th, 16th hats, 8th bass pulse, plucked arpeggio
      if (beatInBar === 0 || beatInBar === 2) kick(t, 0.62, 0.35);
      if (beatInBar === 3.5) kick(t, 0.4, 0.25);
      hat(t, [0.55, 0.22, 0.36, 0.22][s4] * (t > A.act1Mid ? 1.15 : 0.9));
      if (eighth) bass(t, ch.r + (beatInBar === 3.5 ? 12 : 0), 0.22, 0.62);
      if (eighth) pluck(t, ch.arp[e8 % 4] + (e8 > 3 ? 12 : 0), t > A.act1Mid ? 0.46 : 0.34, -0.15);
      if (beatInBar === 0) ep(t, ch.v[0] + 12, limit(t, bar * 0.9), 0.3, -0.2);
      if (beatInBar === 3 && barIdx % 2 === 1 && t > A.act1Mid) clap(t, 0.35);
    } else if (s === 'hush') {
      // the buried freeze: held bass, a heartbeat, one soft EP note per bar
      if (beatInBar === 0 && t > hushStart + 0.15) { bass(t, ch.r, limit(t, bar * 0.95), 0.55); ep(t, ch.v[2] + 12, limit(t, bar), 0.34, 0.1); }
      if ((beatInBar === 0 || beatInBar === 2.5) && t > hushStart + 0.15) kick(t, 0.38, 0.2);
      if (isBeat && t > hushStart + 0.5) hat(t + 0.001, 0.12);
    } else if (s === 'riser') {
      if (isBeat && t < slam - beat * 0.99) { bass(t, ch.r, beat * 0.9, 0.5); }
      if (beatInBar === 0) ep(t, ch.v[1] + 12, limit(t, bar), 0.32, 0.1);
      // clap roll: 8ths, then 16ths, then 32nds, a beat of air before the drop
      const u = (t - riserStart) / (slam - riserStart);
      if (u > 0.3 && u < 0.62 && eighth) clap(t, 0.25 + u * 0.4);
      if (u >= 0.62 && u < 0.9) clap(t, 0.25 + u * 0.45);
      if (u >= 0.82 && u < 0.97) clap(t + beat / 8, 0.4 + u * 0.4);
    } else if (preRise && s === 'groove') {
      // main groove
      const full = dense;
      if (isBeat) kick(t, full ? 1 : 0.85, 0.5);
      if (beatInBar === 1 || beatInBar === 3) clap(t, full ? 0.85 : 0.62);
      if (k * 2 % 2 === 1) hat(t, full ? 0.7 : 0.5); // offbeat 8ths
      if (full && s4 === 3 && ((step % 8) + 8) % 8 !== 7) hat(t, 0.22);
      if (beatInBar === 3.5 && barIdx % 2 === 1) hat(t, 0.55, true);
      // bass: syncopated when dense, two long notes when sparse under the voice
      const bp = full ? [[0, 0.7, 1], [1.5, 0.35, 0.8, 12], [2, 0.7, 1], [3.5, 0.3, 0.8, 12]] : [[0, 1.4, 0.95], [2.5, 1.1, 0.85]];
      for (const [b0, bl, bv, oct = 0] of bp) if (beatInBar === b0) bass(t, ch.r + oct, bl * beat, bv);
      // EP comping
      const cp = full ? [[0, 1.2, 1], [1.5, 0.45, 0.7], [2.5, 1, 0.85]] : [[0, 1.6, 0.85], [2.5, 1.1, 0.6]];
      for (const [b0, bl, bv] of cp) if (beatInBar === b0) ch.v.forEach((m, i) => ep(t + i * 0.006, m, limit(t, bl * beat), bv * 0.85, (i - 1.5) * 0.12));
      // plucked arpeggio only in the dense passages
      if (full && eighth && beatInBar % 1 !== 0) pluck(t, ch.arp[e8 % 4] + 12, 0.3, 0.2);
    } else if (s === 'week') {
      // warm resolve: soft kick on 1 and 3, thin hats, rolling EP, round bass
      if (beatInBar === 0 || beatInBar === 2) kick(t, 0.55, 0.35);
      if (eighth && beatInBar % 1 !== 0) hat(t, 0.28);
      if (beatInBar === 0 || beatInBar === 2.5) bass(t, ch.r, (beatInBar === 0 ? 2.4 : 1.2) * beat, 0.8);
      if (eighth) ep(t, ch.arp[e8 % 4], limit(t, beat * 0.9), 0.42, ((e8 % 4) - 1.5) * 0.12);
      if (beatInBar === 0) ch.v.forEach((m, i) => ep(t + i * 0.01, m - 12, limit(t, bar), 0.34, 0));
    }
    // lead motif on the hero moments (two-bar phrase; plays whenever the phrase start falls inside a hero window)
    if (s === 'groove' || s === 'week') {
      const posIn2 = (((k % 8) + 8) % 8);
      for (const [b0, m, l] of MOTIF) if (Math.abs(posIn2 - b0) < 1e-6 && heroAt(t)) lead(t, m + (s === 'week' ? 0 : 0), limit(t, l * beat), s === 'week' ? 0.6 : 0.52);
    }
  }

  // ----- the key one-off events -----
  // slam: kick, sub boom, bright chord stab (Cmaj9) and a bell
  kick(slam, 1.15, 0.7); subBoom(slam, 1);
  [48, 60, 64, 67, 71, 74].forEach((m, i) => ep(slam + i * 0.004, m, 1.4 * beat, 1.0, (i - 2.5) * 0.12));
  tone(B.fx, slam, 88, 0.2, 0.18, [[1, 1, 3], [2.76, 0.4, 5], [5.4, 0.2, 9]], { att: 0.002, tail: 0.8 });
  riser(riserStart, slam - beat * 0.5);
  // the avalanche hit (kills the busy section): low thud plus a short falling tone
  if (Number.isFinite(hushStart)) { subBoom(hushStart, 0.8); tone(B.fx, hushStart, 57, 0.2, 0.18, [[1, 1, 6], [1.5, 0.4, 8]], { att: 0.003, tail: 0.5 }); }
  // URL: final hit and a ring-out, nothing else after it
  kick(url, 1.0, 0.6); subBoom(url, 0.8);
  [36, 48, 55, 64, 67, 71, 74].forEach((m, i) => ep(url + i * 0.012, m, 2.4, 0.95, (i - 3) * 0.1));
  [76, 79, 83, 88, 91].forEach((m, i) => pluck(url + 0.05 + i * 0.08, m, 0.5, (i - 2) * 0.15));
  tone(B.fx, url, 84, 0.3, 0.14, [[1, 1, 2.2], [2.76, 0.35, 4]], { att: 0.002, tail: 2.4 });

  // ----- master -----
  // soft low-pass on the harmonic instruments (warmth), then mix with the duck from the kick
  for (const k of ['ep', 'pluck', 'lead']) { biquad(B[k].L, 'lp', k === 'pluck' ? 5200 : 3400, 0.6); biquad(B[k].R, 'lp', k === 'pluck' ? 5200 : 3400, 0.6); }
  if (process.env.MUSIC_DEBUG) for (const [k, b] of Object.entries(B)) { let pk = 0, nan = 0; for (let i = 0; i < N; i++) { const v = b.L[i]; if (Number.isNaN(v)) nan++; else pk = Math.max(pk, Math.abs(v)); } console.log(k, 'NaN', nan, 'peak', pk.toFixed(2)); }
  const G = { kick: 0.95, clap: 0.5, hat: 0.2, bass: 0.62, ep: 0.34, pluck: 0.26, lead: 0.3, fx: 0.55 };
  const duck = new Set(['bass', 'ep', 'pluck', 'lead']);
  const out = new Float32Array(N * 2);
  let peak = 0;
  for (let i = 0; i < N; i++) {
    let l = 0, r = 0;
    for (const [key, b] of Object.entries(B)) { const g = G[key] * (duck.has(key) ? pump[i] : 1); l += b.L[i] * g; r += b.R[i] * g; }
    l = Math.tanh(l * 1.1); r = Math.tanh(r * 1.1);
    out[2 * i] = l; out[2 * i + 1] = r;
    peak = Math.max(peak, Math.abs(l), Math.abs(r));
  }
  const gain = Math.pow(10, -3 / 20) / peak; // peak at -3 dBFS; mix.mjs sets the level against the voice
  const fade = Math.round(0.02 * SR);
  const pcm = Buffer.alloc(N * 4);
  for (let i = 0; i < N * 2; i++) {
    const ii = i >> 1;
    const f = Math.min(1, ii / fade, (N - ii) / (SR * 0.1));
    pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(out[i] * gain * f * 32767))), i * 2);
  }
  const hdr = Buffer.alloc(44);
  hdr.write('RIFF', 0); hdr.writeUInt32LE(36 + pcm.length, 4); hdr.write('WAVEfmt ', 8); hdr.writeUInt32LE(16, 16); hdr.writeUInt16LE(1, 20); hdr.writeUInt16LE(2, 22);
  hdr.writeUInt32LE(SR, 24); hdr.writeUInt32LE(SR * 4, 28); hdr.writeUInt16LE(4, 32); hdr.writeUInt16LE(16, 34); hdr.write('data', 36); hdr.writeUInt32LE(pcm.length, 40);
  fs.mkdirSync(path.join(root, 'audio'), { recursive: true });
  fs.writeFileSync(path.join(root, 'audio', name), Buffer.concat([hdr, pcm]));
  console.log(`music: ${name} ${total.toFixed(1)}s, tempo ${(60 / beat).toFixed(1)} BPM, slam ${slam.toFixed(2)}s, url hit ${url.toFixed(2)}s (${bars} bars after the drop)`);
}

// ----- main film: anchors come from the VO timing -----
const an = anchors(T, script);
render({ total: T.total / T.fps, name: 'music.wav', A: { ...an, m4Len: T.scenes.find((s) => s.id === 'm4-run').frames / T.fps } });
// ----- 30 s X cut: a short tense run-up, the drop at 4.6 s, groove, resolve and the hit on the URL card at 28 s -----
render({ total: 30, name: 'music-x.wav', A: { slam: 4.6, url: 28.0, riserBars: 1, buried: undefined, act1Mid: 0, weekStart: 23.5, m4: 19, m4Len: 4.5, hero: [[8.8, 12.2], [15.8, 19], [23.5, 28]] } });
