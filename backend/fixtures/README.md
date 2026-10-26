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
