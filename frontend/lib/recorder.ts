/**
 * Push-to-talk microphone capture. MediaRecorder only produces webm/opus, which the transcription endpoint does not take,
 * so audio is captured as PCM through the Web Audio API and encoded to 16 kHz mono WAV here. While a speaker button is held
 * a chunk is flushed about every `chunkMs` (default 6 s) and once more on release.
 */
import { wavBlob } from "./wav";

export type Speaker = "buyer" | "vendor";
export type ChunkHandler = (wav: Blob, speaker: Speaker) => void | Promise<void>;

export class PushToTalk {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private buffers: Float32Array[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private speaker: Speaker | null = null;

  constructor(
    private onChunk: ChunkHandler,
    private chunkMs = 6000,
  ) {}

  static supported(): boolean {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== "undefined";
  }

  /** Open the microphone (asks permission once) and start recording for `speaker`. */
  async start(speaker: Speaker): Promise<void> {
    if (this.speaker) return;
    this.speaker = speaker;
    if (!this.ctx) {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
      this.ctx = new AudioContext();
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = this.ctx.createScriptProcessor(4096, 1, 1);
      this.node.onaudioprocess = (e) => {
        if (this.speaker) this.buffers.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      this.source.connect(this.node);
      this.node.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.buffers = [];
    this.timer = setInterval(() => void this.flush(), this.chunkMs);
  }

  /** Stop recording for the held speaker and send what is left. */
  async stop(): Promise<void> {
    if (!this.speaker) return;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    await this.flush();
    this.speaker = null;
  }

  private async flush(): Promise<void> {
    const speaker = this.speaker;
    if (!speaker || !this.ctx || !this.buffers.length) return;
    const total = this.buffers.reduce((n, b) => n + b.length, 0);
    const all = new Float32Array(total);
    let at = 0;
    for (const b of this.buffers) {
      all.set(b, at);
      at += b.length;
    }
    this.buffers = [];
    if (total < this.ctx.sampleRate * 0.3) return; // under 0.3 s: a click, not speech
    await this.onChunk(wavBlob(all, this.ctx.sampleRate), speaker);
  }

  /** Release the microphone. */
  async close(): Promise<void> {
    await this.stop();
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    this.ctx = this.stream = this.node = this.source = null;
  }
}
