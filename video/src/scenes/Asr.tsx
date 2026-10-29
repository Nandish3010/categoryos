import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { VoCaptions } from '../components/Captions';
import { TiltFrame } from '../components/AppParts';
import { body, C, display, E, FPS, prog, sceneOf } from '../theme';
import live from '../data/live_asr.json';

// The one live Muse Voice call in the film: a synthetic vendor voice (Kokoro) is played, and the transcript is the model's real response
// (src/data/live_asr.json, written once by scripts/live-asr.mjs). Nothing here is re-computed: the words are the recorded response.

const T_TEXT: string = (live.response as { transcript: string }).transcript;
const WORDS = T_TEXT.split(/\s+/).filter(Boolean);
const ENV: number[] = live.envelope;
const dateLabel = (iso: string) => new Date(iso + 'T12:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
export const ASR_CHIP = `Live: ${live.model} · recorded ${dateLabel(live.recorded_at)} · ${live.latency_sec} s`;
const isNum = (w: string) => /\d/.test(w);

const clipFrames = () => {
  const sc = sceneOf('m1-asr') as ReturnType<typeof sceneOf> & { clip?: { a: number; b: number } };
  const c = sc.clip ?? { a: 3, b: 10 };
  return { a: (sc.voLead + c.a) * FPS, b: (sc.voLead + c.b) * FPS };
};

const Panel: React.FC<{ lf: number }> = ({ lf }) => {
  const { a, b } = clipFrames();
  const playing = lf >= a && lf < b;
  const done = lf >= b;
  const pr = Math.max(0, Math.min(1, (lf - a) / (b - a)));
  const grow = prog(lf, 4, 30, E.out);
  // transcript reveal: word i appears when the share of characters before it has been "heard" (starts shortly after the audio starts, ends before it ends)
  const t0 = a + 14, t1 = b - 8;
  const total = WORDS.reduce((n, w) => n + w.length + 1, 0);
  let acc = 0;
  const shown = WORDS.map((w) => { const at = t0 + (acc / total) * (t1 - t0); acc += w.length + 1; return lf >= at; });
  const secNow = Math.max(0, Math.min(live.audio_sec, pr * live.audio_sec));
  const fmt = (x: number) => `0:${String(Math.floor(x)).padStart(2, '0')}`;
  const W = 1560, H = 250, n = ENV.length, bw = W / n;
  return (
    <AbsoluteFill style={{ background: 'radial-gradient(1200px 700px at 50% 20%, #1b2440 0%, #0F1117 70%)' }}>
      <div style={{ position: 'absolute', left: 180, top: 70, right: 180, display: 'flex', alignItems: 'center', gap: 22 }}>
        <div style={{ width: 76, height: 76, borderRadius: 38, background: '#1E2230', border: `3px solid ${playing ? C.green : C.dim}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 38, boxShadow: playing ? `0 0 ${24 + 10 * Math.sin(lf * 0.4)}px ${C.green}88` : undefined }}>{'☎'}</div>
        <div>
          <div style={{ fontFamily: display, fontWeight: 700, fontSize: 52, color: C.text }}>Vendor on the line</div>
          <div style={{ fontFamily: body, fontWeight: 500, fontSize: 30, color: C.dim }}>Voice: synthetic (Kokoro). Transcription: real.</div>
        </div>
        <div style={{ marginLeft: 'auto', fontFamily: display, fontWeight: 700, fontSize: 34, color: done ? C.green : playing ? C.orange : C.dim, border: `2px solid currentColor`, borderRadius: 999, padding: '4px 22px' }}>{done ? 'Transcribed' : playing ? 'Transcribing' : 'Connecting'}</div>
      </div>
      <div style={{ position: 'absolute', left: 180, top: 230, width: W, height: H, display: 'flex', alignItems: 'center' }}>
        {ENV.map((v, i) => {
          const h = Math.max(6, Math.pow(v, 0.7) * H) * (0.15 + 0.85 * grow);
          const played = i / n <= pr && lf >= a;
          return <div key={i} style={{ width: bw - 2.5, marginRight: 2.5, height: h, borderRadius: 3, background: played ? C.blue : '#3A4160', opacity: played ? 1 : 0.8 }} />;
        })}
        {playing ? <div style={{ position: 'absolute', left: pr * W, top: -10, width: 4, height: H + 20, background: C.yellow, boxShadow: `0 0 16px ${C.yellow}` }} /> : null}
      </div>
      <div style={{ position: 'absolute', left: 180, top: 490, fontFamily: body, fontWeight: 500, fontSize: 28, color: C.dim }}>{fmt(secNow)} / {fmt(live.audio_sec)}</div>
      <div style={{ position: 'absolute', left: 180, right: 180, top: 560, background: '#171A23', border: '2px solid #2b3040', borderRadius: 20, padding: '24px 40px 30px', minHeight: 270 }}>
        <div style={{ fontFamily: body, fontWeight: 700, fontSize: 28, color: C.blue, marginBottom: 14 }}>Transcript, as returned by {live.model}</div>
        <div style={{ fontFamily: display, fontWeight: 700, fontSize: 66, lineHeight: 1.18, color: C.text, display: 'flex', flexWrap: 'wrap', gap: '0 0.3em' }}>
          {WORDS.map((w, i) => (shown[i] ? <span key={i} style={{ color: isNum(w) ? C.yellow : C.text }}>{w}</span> : null))}
          {!done ? <span style={{ width: 6, height: 62, marginTop: 8, background: C.blue, opacity: Math.sin(lf * 0.5) > 0 ? 1 : 0.2 }} /> : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Chips: React.FC<{ lf: number }> = ({ lf }) => {
  const { a } = clipFrames();
  const p = prog(lf, a - 6, a + 10);
  if (p <= 0.01) return null;
  return (
    <div style={{ position: 'absolute', left: 150, top: 44, zIndex: 36, opacity: p, transform: `translateY(${(1 - p) * -14}px)` }}>
      <div style={{ background: 'rgba(15,17,23,.92)', border: `2px solid ${C.green}`, color: C.text, fontFamily: body, fontWeight: 700, fontSize: 32, padding: '8px 24px', borderRadius: 999, display: 'inline-flex', alignItems: 'center', gap: 12 }}>
        <span style={{ width: 16, height: 16, borderRadius: 8, background: C.green, boxShadow: `0 0 ${10 + 6 * Math.sin(lf * 0.3)}px ${C.green}` }} />{ASR_CHIP}
      </div>
    </div>
  );
};

export const AsrScene: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: 'radial-gradient(1300px 800px at 50% 35%, #1b2440 0%, #0F1117 62%)' }} />
      <TiltFrame lf={f} scale={0.84} enter={0} url="api.meta.ai/v1/asr/transcribe">
        <Panel lf={f} />
      </TiltFrame>
      <Chips lf={f} />
      <VoCaptions sceneId="m1-asr" accent={C.blue} bottom={52} />
    </AbsoluteFill>
  );
};
