/** Audio helpers for the live call: mono Float32 samples -> 16 kHz mono 16-bit PCM WAV (what muse-voice-transcribe-1.0 takes). */

export const TARGET_RATE = 16000;

/** Linear-interpolation resample (microphone rates such as 44.1 or 48 kHz down to 16 kHz). */
export function resample(samples: Float32Array, from: number, to: number = TARGET_RATE): Float32Array {
  if (from === to || samples.length === 0) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.max(1, Math.floor(samples.length / ratio)));
  for (let i = 0; i < out.length; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, samples.length - 1);
    const frac = pos - i0;
    out[i] = samples[i0] * (1 - frac) + samples[i1] * frac;
  }
  return out;
}

/** A complete WAV file (44-byte RIFF header + little-endian 16-bit PCM). */
export function encodeWav(samples: Float32Array, sampleRate: number = TARGET_RATE): ArrayBuffer {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i));
  };
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

export function wavBlob(samples: Float32Array, fromRate: number): Blob {
  return new Blob([encodeWav(resample(samples, fromRate))], { type: "audio/wav" });
}
