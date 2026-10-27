import { describe, expect, it } from "vitest";
import { EMPTY_CALL, applyCallEvent, readNextAsk, stageFromState } from "./call";
import { encodeWav, resample } from "./wav";
import { readDeals } from "./deals";
import { readNegotiate } from "./stages";
import { dealsFixture } from "../test-utils/deals";

const ev = (type: string, payload: Record<string, unknown>) => ({ seq: 1, call_id: "c", type, payload });

describe("applyCallEvent", () => {
  it("builds the call up turn by turn and ignores a repeated turn", () => {
    let v = applyCallEvent(EMPTY_CALL, ev("started", { state: { gap_table: [], next_ask: { kind: "listen", line: "Ask about margin.", reason: "Nothing agreed." } } }));
    expect(v.status).toBe("running");
    expect(v.nextAsk?.line).toBe("Ask about margin.");
    v = applyCallEvent(v, ev("turn", { turn: { turn: 1, speaker: "buyer", text: "Hi", source: "simulated" } }));
    v = applyCallEvent(v, ev("turn", { turn: { turn: 1, speaker: "buyer", text: "Hi" } }));
    expect(v.turns).toHaveLength(1);
  });

  it("carries state, the next ask and what to flash from a state event", () => {
    const state = {
      gap_table: [{ term: "margin_pct", label: "Margin", unit: "pct", direction: "higher", application: 17, offered: 21, required: 35, gap: -14, status: "gap", turn: 4, quote: "q", claim_id: "c", verification: "verified" }],
      deals: dealsFixture(),
      next_ask: { kind: "reject_conditional", line: "Can you set the target at 250 units in 90 days instead?", reason: "Don't accept it.", deal_id: "t2" },
      spend_usd: 0.012,
    };
    const v = applyCallEvent({ ...EMPTY_CALL, status: "running" }, ev("state", { state, changed: { gap_terms: ["margin_pct"], deal_ids: ["t2"] }, turn: 4 }));
    expect(v.flash).toEqual({ terms: ["margin_pct"], deals: ["t2"] });
    expect(v.spendUsd).toBe(0.012);
    expect(v.nextAsk?.kind).toBe("reject_conditional");
    const stage = v.stage!;
    expect(readNegotiate(stage)?.gaps[0].offered).toBe(21);
    expect(readDeals(stage)?.assessments[0].decision).toBe("reject_structure");
  });

  it("marks the call ended and surfaces errors as typed bodies", () => {
    expect(applyCallEvent({ ...EMPTY_CALL, status: "running" }, ev("ended", { state: { gap_table: [] } })).status).toBe("ended");
    const v = applyCallEvent(EMPTY_CALL, ev("error", { code: "call_budget_exceeded", problem: "This call reached its spend budget", fix: "End the call" }));
    expect(v.error).toMatchObject({ code: "call_budget_exceeded", fix: "End the call" });
  });

  it("survives junk", () => {
    expect(applyCallEvent(EMPTY_CALL, "x")).toBe(EMPTY_CALL);
    expect(applyCallEvent(EMPTY_CALL, ev("turn", { turn: "no" }))).toEqual(EMPTY_CALL);
    expect(readNextAsk(null)).toBeNull();
    expect(stageFromState(3)).toBeNull();
  });
});

describe("wav encoding", () => {
  it("writes a 16 kHz mono 16-bit PCM RIFF header and clips samples", () => {
    const buf = encodeWav(new Float32Array([0, 1, -1, 2]), 16000);
    const v = new DataView(buf);
    const tag = (o: number) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
    expect([tag(0), tag(8), tag(36)]).toEqual(["RIFF", "WAVE", "data"]);
    expect(v.getUint16(22, true)).toBe(1);
    expect(v.getUint32(24, true)).toBe(16000);
    expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(8);
    expect(buf.byteLength).toBe(44 + 8);
    expect([v.getInt16(44, true), v.getInt16(46, true), v.getInt16(48, true), v.getInt16(50, true)]).toEqual([0, 32767, -32768, 32767]);
  });
  it("downsamples 48 kHz to 16 kHz", () => {
    const out = resample(new Float32Array(48000).fill(0.5), 48000);
    expect(out.length).toBe(16000);
    expect(out[100]).toBeCloseTo(0.5);
  });
});
