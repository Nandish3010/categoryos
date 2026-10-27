"use client";

/**
 * Live negotiation copilot client (shapes: docs/api-contract.md, "Live call"). `state` has the same shape as the Negotiate
 * stage's `data`, so the Negotiate readers and views render it unchanged.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, BACKEND_URL, parseErrorBody, post, type ApiErrorBody } from "./api";
import { getDemoKey } from "./demoKey";
import type { StageResult } from "./runs";
import { streamSse } from "./sse";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

export type CallMode = "simulate" | "live";
export type CallTurn = { turn: number; speaker: string; text: string; source?: string };
export type NextAsk = { kind: string; line: string; reason: string; term: string | null; dealId?: string | null };
export type CallStatus = "idle" | "starting" | "running" | "ended" | "error";

export type CallView = {
  callId: string | null;
  mode: CallMode | null;
  status: CallStatus;
  turns: CallTurn[];
  /** The latest call state as a Negotiate-stage-shaped result (render with readNegotiate / readDeals). */
  stage: StageResult | null;
  nextAsk: NextAsk | null;
  /** Gap-table terms and deal ids that changed on the latest turn (flash them). */
  flash: { terms: string[]; deals: string[] };
  error: ApiErrorBody | null;
  spendUsd: number;
  busy: boolean;
};

export const EMPTY_CALL: CallView = {
  callId: null,
  mode: null,
  status: "idle",
  turns: [],
  stage: null,
  nextAsk: null,
  flash: { terms: [], deals: [] },
  error: null,
  spendUsd: 0,
  busy: false,
};

export function readNextAsk(v: unknown): NextAsk | null {
  if (!isObj(v)) return null;
  return {
    kind: str(v.kind) ?? "listen",
    line: str(v.line) ?? "",
    reason: str(v.reason) ?? "",
    term: str(v.term),
    dealId: str(v.deal_id),
  };
}

/** Wrap a call state the way a StageResult carries Negotiate data. */
export function stageFromState(state: unknown): StageResult | null {
  if (!isObj(state)) return null;
  return {
    stage: "negotiate",
    status: "running",
    mode: "live",
    summary: "Live call",
    data: state,
    claims: [],
    metrics_hash: null,
    narrative_hash: null,
    needs_approval: false,
    locked_reason: null,
    error: null,
  };
}

const vid = (id: string) => encodeURIComponent(id);

export const startCall = (vendorId: string, mode: CallMode, speed = 1) =>
  post<{ call_id: string; mode: CallMode }>(`/api/vendors/${vid(vendorId)}/call`, { mode, speed });
export const endCall = (vendorId: string, callId: string) => post<unknown>(`/api/vendors/${vid(vendorId)}/call/end`, { call_id: callId });
export const sendTurn = (vendorId: string, callId: string, speaker: "buyer" | "vendor" | "auto", text: string) =>
  post<unknown>(`/api/vendors/${vid(vendorId)}/call/turns`, { call_id: callId, speaker, text });

/** One recorded clip (WAV). Multipart, so it cannot go through the JSON `post` helper. */
export async function sendChunk(vendorId: string, callId: string, speaker: "buyer" | "vendor", wav: Blob): Promise<unknown> {
  const form = new FormData();
  form.set("call_id", callId);
  form.set("speaker", speaker);
  form.set("audio", wav, "chunk.wav");
  const headers: Record<string, string> = {};
  const key = getDemoKey();
  if (key) headers["X-Demo-Key"] = key;
  const res = await fetch(`${BACKEND_URL}/api/vendors/${vid(vendorId)}/call/chunks`, { method: "POST", body: form, headers });
  if (!res.ok) {
    let raw: unknown = null;
    try {
      raw = await res.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, parseErrorBody(res.status, raw));
  }
  return res.json();
}

/** Fold one SSE `call` event into the view. Pure, so it can be tested without a network. */
export function applyCallEvent(view: CallView, ev: unknown): CallView {
  if (!isObj(ev) || !isObj(ev.payload)) return view;
  const p = ev.payload;
  switch (ev.type) {
    case "started":
      return { ...view, status: "running", stage: stageFromState(p.state) ?? view.stage, nextAsk: readNextAsk(isObj(p.state) ? p.state.next_ask : null) ?? view.nextAsk };
    case "turn": {
      const t = isObj(p.turn) ? p.turn : null;
      if (!t || typeof t.turn !== "number") return view;
      if (view.turns.some((x) => x.turn === t.turn)) return view;
      return { ...view, turns: [...view.turns, { turn: t.turn, speaker: str(t.speaker) ?? "speaker", text: str(t.text) ?? "", source: str(t.source) ?? undefined }] };
    }
    case "state":
    case "ended": {
      const st = isObj(p.state) ? p.state : null;
      const ch = isObj(p.changed) ? p.changed : {};
      const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
      return {
        ...view,
        status: ev.type === "ended" ? "ended" : view.status,
        stage: stageFromState(st) ?? view.stage,
        nextAsk: readNextAsk(st?.next_ask) ?? view.nextAsk,
        spendUsd: typeof st?.spend_usd === "number" ? st.spend_usd : view.spendUsd,
        flash: { terms: list(ch.gap_terms), deals: list(ch.deal_ids) },
      };
    }
    case "error":
      return { ...view, error: { code: str(p.code) ?? "error", problem: str(p.problem) ?? "The call hit an error", cause: str(p.cause) ?? undefined, fix: str(p.fix) ?? undefined } };
    default:
      return view;
  }
}

export function useCall(vendorId: string) {
  const [view, setView] = useState<CallView>(EMPTY_CALL);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const follow = useCallback(
    (callId: string) => {
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      const headers: Record<string, string> = {};
      void streamSse({
        url: `${BACKEND_URL}/api/vendors/${vid(vendorId)}/call/${callId}/events`,
        headers,
        signal: ctl.signal,
        isDone: (f) => {
          try {
            return (JSON.parse(f.data) as Obj).type === "ended";
          } catch {
            return false;
          }
        },
        onFrame: (f) => {
          try {
            const ev = JSON.parse(f.data);
            setView((v) => applyCallEvent(v, ev));
          } catch {
            /* malformed frame */
          }
        },
      });
    },
    [vendorId],
  );

  const start = useCallback(
    async (mode: CallMode, speed = 1) => {
      setView({ ...EMPTY_CALL, status: "starting", mode });
      try {
        const res = await startCall(vendorId, mode, speed);
        setView((v) => ({ ...v, callId: res.call_id, mode: res.mode }));
        follow(res.call_id);
      } catch (e) {
        setView({ ...EMPTY_CALL, status: "error", error: e instanceof ApiError ? e.body : { code: "error", problem: "Could not start the call" } });
      }
    },
    [vendorId, follow],
  );

  const guard = useCallback(async (fn: () => Promise<unknown>) => {
    setView((v) => ({ ...v, busy: true }));
    try {
      await fn();
      setView((v) => ({ ...v, busy: false }));
    } catch (e) {
      setView((v) => ({ ...v, busy: false, error: e instanceof ApiError ? e.body : { code: "error", problem: "The request failed" } }));
    }
  }, []);

  const end = useCallback(() => (view.callId ? guard(() => endCall(vendorId, view.callId!)) : Promise.resolve()), [vendorId, view.callId, guard]);
  const say = useCallback(
    (speaker: "buyer" | "vendor", text: string) => (view.callId ? guard(() => sendTurn(vendorId, view.callId!, speaker, text)) : Promise.resolve()),
    [vendorId, view.callId, guard],
  );
  const chunk = useCallback(
    (wav: Blob, speaker: "buyer" | "vendor") => (view.callId ? guard(() => sendChunk(vendorId, view.callId!, speaker, wav)) : Promise.resolve()),
    [vendorId, view.callId, guard],
  );
  const reset = useCallback(() => {
    abort.current?.abort();
    setView(EMPTY_CALL);
  }, []);

  return { view, start, end, say, chunk, reset };
}
