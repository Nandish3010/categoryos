# CategoryOS run API contract

Backend: FastAPI (`backend/app/main.py`). All errors share one shape, whether raised by validation,
auth or the agents: `{"code", "problem", "cause", "fix", "run_id"}` (`run_id` is null unless the request sent
`X-Run-Id`). Pydantic request validation failures are the usual FastAPI `422`.

## Stages

Eight stage ids, in order: `intake`, `research`, `shortlist`, `negotiate`, `catalog`, `marketing`, `jbp`, `po`.

| Agent | Stage id it reports on | Notes |
|---|---|---|
| Screen | `intake` | deterministic document check, then a tool-calling model pass |
| Decide | `research` | one engine run that covers research, shortlist and negotiate; `shortlist` and `negotiate` stay `pending` |

Status FSM: `pending` -> `running` -> `review` (needs a human) | `done` | `failed` | `locked`.
A passed Screen ends `done` (it needs no approval). Decide ends `review` with `needs_approval: true`;
approving it makes it `done`. If Screen fails, `intake` is `failed` and every later stage is `locked`.

### StageResult

```json
{
  "stage": "research",
  "status": "pending|running|review|done|locked|failed|degraded",
  "summary": "string",
  "data": {},
  "needs_approval": false,
  "locked_reason": null,
  "claims": [],
  "metrics_hash": null,
  "narrative_hash": null
}
```

`claims` are `Claim` objects as returned by `GET /api/vendors/{id}/claims` (`origin` is `engine` or
`model_extraction`; `status` is `verified|rejected|unverifiable`).

`intake` `data`: `{decision: "pass"|"fail", reasons[], risk_flags: [{type, quote, severity}], injection_detected,
followup_questions[], documents: {documents[], problems[], blocking}, guards[], mode}`. When it fails,
`locked_reason` is set on the stage itself and on every later stage (prefixed `Screening failed:`).

`research` `data`: `{headline, rationale_per_sku: [{code, verdict, why, edited_by_human?, original_verdict?, note?}],
counter_offer: {terms: [{term, ask, current?, fallback?, sku_code?, rationale}], email_draft},
extractions: [{sku_code, field: "cost"|"mrp", value, row, header, claim_id, status, sheet_value}],
struck: [{claim_id, sku_code, field, claimed_value, sheet_value, reason, where, sentence}],
verdict_corrections[], overrides?, lever: {target_margin_pct_offset, moq}, summary (DecideSummary),
verification: {total, verified, rejected, unverifiable}, replanned: bool, mode}`.

- `struck` lists the narrative sentences removed because a model extraction was rejected by the verifier
  (`where` is `rationale:<code>`, `headline`, `email_draft` or `term:<name>`; `sentence` is the removed text, or
  null if no sentence cited the number). Rejected claims stay in `claims`.
- `metrics_hash` is the hash of the metrics (`GET /decide/metrics`) the result was computed from.
  `narrative_hash` is the metrics hash the narrative was generated for; at creation both are equal.
  If the user moves the levers, the UI's current hash differs from `narrative_hash`: the narrative is stale and
  approval is refused until a re-plan.
- `verdict` is always the engine's verdict (a disagreeing model verdict is replaced and logged in
  `verdict_corrections`), unless a human override changed it (`edited_by_human: true`).

## TraceEvent

```json
{
  "seq": 7,
  "run_id": "run_ab12cd34ef",
  "t_rel_ms": 412.5,
  "type": "stage_started|tool_call|model_call|claim_checked|stage_result|degraded|error|done",
  "stage": "intake|...|null",
  "model": "muse-spark-1.3|null",
  "latency_ms": 12.3,
  "cost_usd": 0.0,
  "payload": {}
}
```

`seq` is 1-based, strictly increasing per run (continues across a re-plan). `t_rel_ms` is milliseconds since the run
started. Payloads:

| type | payload |
|---|---|
| `stage_started` | `{stage}` |
| `tool_call` | `{tool, args, result_summary, deterministic?}` (`deterministic: true` for engine/document steps that are not model-chosen) |
| `model_call` | `{task, mode: "mock"|"replay"|"live", input_tokens, output_tokens, tool_steps}`; `model`, `latency_ms`, `cost_usd` set on the event |
| `claim_checked` | `{claim: Claim}` with its final `status` and `reason` |
| `stage_result` | a full `StageResult` |
| `degraded` | `{reason}` (replay fell back to a mock fixture) |
| `error` | `{code, problem, cause, fix, run_id}` |
| `done` | `{}` (or `{replan: true}` after a re-plan); always the last event of a stream |

## Routes

`X-Demo-Key` is required only where noted. "When live" means at least one stage's effective mode is `live`
(`GET /api/mode` -> `stage_modes`); in `mock` and `replay` these routes are open.

### `POST /api/vendors/{id}/runs` -> `202 {"run_id": "run_..."}`
Starts Screen, then Decide if Screen passed, as a background task. Demo key when live. `404 unknown_vendor`.

### `GET /api/vendors/{id}/runs/latest` -> `{"run_id": "run_..."|null}`

### `GET /api/runs/{run_id}`
```json
{"run_id": "...", "vendor_id": "V001", "mode": "mock", "created_at": "2026-10-27T10:00:00.000+00:00",
 "stages": {"intake": StageResult, "research": StageResult, "...": "all 8 ids always present"}}
```
Untouched stages are `{"status": "pending"}` StageResults. `404 run_not_found`.

### `GET /api/runs/{run_id}/events` -> `text/event-stream`
```
id: 7
event: trace
data: {TraceEvent JSON}

: ping

```
- Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- A comment line `: ping` is sent every 15 s of silence (`SSE_HEARTBEAT_S`).
- `Last-Event-ID: n` replays stored events with `seq > n`, then continues live. A new connection without the header
  starts from seq 1, so a late subscriber gets the whole run.
- The stream ends after an event of type `done`. The browser `EventSource` cannot send headers, so clients should use
  a fetch stream; no key is needed on this route.
- After a re-plan, its events (ending in another `done`) are appended to the same run's log.

### `POST /api/runs/{run_id}/stages/{stage}/approve`  body `{"metrics_hash": "..."}`
`200` StageResult with `status: "done"`, `needs_approval: false`. `409`
`{"code": "stale_approval", "problem", "cause", "fix"}` if `metrics_hash != narrative_hash`.
`409 stage_not_reviewable` if the stage is not `review`/`done` or has no narrative (e.g. `intake`, locked stages).
`404 unknown_stage|run_not_found`.

### `POST /api/runs/{run_id}/stages/{stage}/override`  body `{"sku_code", "verdict", "note"?}`
`verdict` is `list|negotiate|reject|needs_data`. `200` StageResult; the SKU's `rationale_per_sku` entry gets
`edited_by_human: true`, `original_verdict`, `note`, and `data.overrides[sku_code]` records it. The narrative hash is
unchanged. `404 unknown_sku`, `409 stage_not_reviewable`, `422` for a bad verdict.

### `POST /api/vendors/{id}/decide/replan`  body `{"run_id", "target_margin_pct_offset" (-20..20), "moq" (0..20000)}`
Re-runs Decide for those lever values and replaces the run's `research` result. `200` StageResult with
`narrative_hash == metrics_hash ==` the hash of those levers and `data.replanned: true`. In mock/replay the fixture's
narrative is reused but verdicts, the headline and the counter-offer SKU list are recomputed from the metrics so the
text is consistent. Demo key when live. `409 stage_locked` if Screen failed, `409 stage_not_reviewable` while Decide
is running; `404 run_not_found` (also when the run belongs to another vendor).

### `POST /api/vendors/{id}/reject`  body `{"run_id", "reason"}`
`200 {"run_id", "vendor_id", "status": "rejected", "reason"}`. `research` becomes `failed` (`data.rejected: true`) and
`shortlist` .. `po` become `locked` (`locked_reason: "Vendor rejected: ..."`).

### `POST /api/admin/reset`  (demo key, always)
`200 {"ok": true}`. Empties the store and in-memory run state. Idempotent.

## Other routes (unchanged)

`GET /health`, `/api/stages`, `/api/mode`, `/api/vendors`, `/api/vendors/{id}`,
`/api/vendors/{id}/decide/metrics`, `/api/vendors/{id}/claims`, `/api/ledger` (demo key).
