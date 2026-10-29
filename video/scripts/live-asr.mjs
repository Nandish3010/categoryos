// ONE live call to muse-voice-transcribe-1.0 (same request shape as backend/app/media.py:transcribe), saved as src/data/live_asr.json.
// The vendor voice (assets/live/vendor-offer.wav) is synthetic (Kokoro am_michael); the transcription in the fixture is the model's real response.
// Usage: (set -a; . ../.env; set +a; node scripts/live-asr.mjs)      Refuses to run twice unless FORCE=1 (it costs a fraction of a cent).
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const out = path.join(root, 'src/data/live_asr.json');
if (fs.existsSync(out) && process.env.FORCE !== '1') { console.log('live_asr.json exists; set FORCE=1 to call again'); process.exit(0); }
const key = process.env.MODEL_API_KEY;
if (!key) { console.error('MODEL_API_KEY not set'); process.exit(1); }
const base = (process.env.MODEL_API_BASE_URL || 'https://api.meta.ai/v1').replace(/\/$/, '');
const model = 'muse-voice-transcribe-1.0';
const wav = fs.readFileSync(path.join(root, 'assets/live/vendor-offer.wav'));
const form = new FormData();
form.append('request', new Blob([JSON.stringify({ model, audioEncoding: 'WAV', mode: 'PUSH_TO_TALK' })], { type: 'application/json' }));
form.append('audio', new Blob([wav], { type: 'audio/wav' }), 'call.wav');
const t0 = performance.now();
const resp = await fetch(`${base}/asr/transcribe`, { method: 'POST', headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' }, body: form });
const latencySec = +((performance.now() - t0) / 1000).toFixed(2);
const text = await resp.text();
let body; try { body = JSON.parse(text); } catch { body = text.slice(0, 500); }
if (!resp.ok) { console.error('HTTP', resp.status, JSON.stringify(body).slice(0, 300)); process.exit(1); }
// peak envelope of the clip (for the waveform drawn in the film): 16-bit mono PCM after the 44-byte header
const pcm = new Int16Array(wav.buffer.slice(wav.byteOffset + 44, wav.byteOffset + wav.length - ((wav.length - 44) % 2)));
const N = 240, step = Math.floor(pcm.length / N);
const envelope = Array.from({ length: N }, (_, i) => { let m = 0; for (let j = i * step; j < (i + 1) * step; j++) m = Math.max(m, Math.abs(pcm[j])); return +(m / 32768).toFixed(3); });
const fixture = {
  model, endpoint: `${base}/asr/transcribe`, recorded_at: new Date().toISOString().slice(0, 10), latency_sec: latencySec, http_status: resp.status,
  note: 'Vendor voice is synthetic (Kokoro-82M am_michael); the transcription below is the live response of the model, unedited.',
  audio_sec: +(pcm.length / 16000).toFixed(3), spoken_text: 'Fifteen percent margin, plus twenty percent marketing support if you sell two thousand units in ninety days.',
  response: body, envelope,
};
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(fixture, null, 2));
console.log('status', resp.status, 'latency', latencySec, 's\ntranscript:', body.transcript);
