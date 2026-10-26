# Model fixtures

`llm.call(stage, messages, task=...)` reads canned responses from here when it is not live.

```
fixtures/mock/<stage>/<task>.json     hand-written, deterministic, used in MODEL_MODE=mock
fixtures/golden/<stage>/<task>.json   recorded from a real live run (make record), used in replay
```

Replay falls back to the mock fixture (and marks the result `degraded`) when no golden file exists.
A missing mock fixture raises `FixtureMissing` with the path to create.

## File schema

```json
{
  "schema_version": 1,
  "parser_version": "1.0",
  "model": "muse-spark-1.3",
  "input_tokens": 0,
  "output_tokens": 0,
  "checksum": "sha256 of content (optional; written by make record, verified on load)",
  "content": "raw model text, or a JSON object (serialised to text on load)"
}
```

- `schema_version`: bump when this file layout changes; golden files are then re-recorded.
- `parser_version`: the `app.parsing.PARSER_VERSION` the fixture was recorded against. Golden fixtures
  recorded with a different parser version are stale and should be re-recorded.
- `stage` is one of the stage ids in `app/constants.py`; `task` is a snake_case name chosen by the caller
  (for example `extract_sheet`, `narrate_decision`).
- Golden files are written automatically on a successful live call when `RECORD=1`.

## Tool-calling fixtures (`llm.run_tools`)

Agents that use tools read fixtures whose `content` is a script instead of text:

```json
{ "content": { "steps": [ {"tool": "get_metrics", "args": {"vendor_id": "V001"}} ], "final": { } } }
```

In mock and replay mode `run_tools` EXECUTES the real tool function for every scripted step (so traces show real
tool output from `data/synthetic`), then returns `final`, validated against the stage's schema. `steps` is capped by
`max_steps`; a step naming a tool the stage did not offer fails with `llm_bad_output`. Golden recordings
(`RECORD=1`, live) use the same shape, with the tool calls the model really made.

| File | Task | Produced by |
|---|---|---|
| `mock/intake/screen_<VID>.json` | Screen, one per vendor V001..V004 | hand-written; V004 flags the injection line and fails |
| `mock/research/decide_<VID>.json` | Decide, one per vendor | hand-written prose, every number taken from the engine and the real sheet cells |

Sku codes, rows, headers and cell values in these files are the real ones from `data/synthetic/vendors/*`.
`decide_V004.json` is minimal on purpose: Screen locks V004, so Decide never runs for it in the normal flow.

### The planted verifier catch (recorded mock; will be replaced by a real live catch)

`decide_V001.json` contains exactly ONE wrong extraction, a realistic digit transposition:

- `HP-D01` cost, sheet row 2, header `Cost to Us`: the sheet says `Rs. 956.50`, the mock agent says `965.50`.

The verifier re-reads the cell, rejects the claim, and the sentence citing `₹965.50` is struck from the narrative.
All other extractions in all four fixtures are correct. This is a hand-written stand-in: the headline demo claim is a
real, unscripted catch from a live run. When one is recorded it replaces this file under `fixtures/golden/`.
