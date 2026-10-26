#!/usr/bin/env bash
# Smoke test a deployed (or local) CategoryOS backend, optionally with its frontend.
#   scripts/smoke_deployed.sh BACKEND_URL [FRONTEND_URL]
# e.g. scripts/smoke_deployed.sh http://localhost:8001
#      scripts/smoke_deployed.sh https://you--categoryos-backend-fastapi-app.modal.run https://categoryos.vercel.app
# Exits non-zero on the first failed check. Uses replay mode only: no model calls, no keys.
set -uo pipefail

BACKEND="${1:-}"
FRONTEND="${2:-}"
if [[ -z "$BACKEND" ]]; then
  echo "usage: $0 BACKEND_URL [FRONTEND_URL]" >&2
  exit 2
fi
BACKEND="${BACKEND%/}"
FRONTEND="${FRONTEND%/}"
SSE_TIMEOUT="${SSE_TIMEOUT:-120}"   # seconds to wait for the replay run to reach `done`
COLD_START="${COLD_START:-90}"      # seconds to wait for a scaled-to-zero backend to wake up

PASS=0
FAIL=0
pass() { echo "  ok    $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1" >&2; FAIL=$((FAIL + 1)); }
check() { # check "label" <command...>
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}

get() { curl -fsS --max-time 30 "$BACKEND$1"; }
# json_ok PATH 'python expression over d' : GET PATH, parse JSON as d, require the expression to be truthy
json_ok() {
  local path="$1" expr="$2"
  get "$path" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if ($expr) else 1)"
}

echo "Smoke: $BACKEND${FRONTEND:+  (frontend $FRONTEND)}"

echo "waking the backend (cold start can take a while)..."
deadline=$((SECONDS + COLD_START))
until curl -fsS --max-time 20 "$BACKEND/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then fail "/health did not answer within ${COLD_START}s"; echo "$PASS passed, $FAIL failed"; exit 1; fi
  sleep 3
done

check "/health is ok"                   json_ok /health "d.get('status') == 'ok'"
check "/api/stages lists 8 stages"      json_ok /api/stages "len(d) == 8"
check "/api/mode is replay"             json_ok /api/mode "d.get('mode') == 'replay' and not d.get('degraded')"
check "/api/vendors lists 4 vendors"    json_ok /api/vendors "len(d) == 4"
check "lever endpoint answers"          json_ok "/api/vendors/V001/decide/metrics?target_margin_pct_offset=2" "d.get('metrics_hash') and d.get('skus') is not None"
check "claims endpoint answers"         json_ok /api/vendors/V001/claims "isinstance(d, dict) and len(d) > 0"

# --- a replay run, streamed to `done` ---
RUN_ID="$(curl -fsS --max-time 30 -X POST "$BACKEND/api/vendors/V001/runs" | python3 -c "import json,sys; print(json.load(sys.stdin)['run_id'])" 2>/dev/null)"
if [[ -z "$RUN_ID" ]]; then
  fail "POST /api/vendors/V001/runs returned no run_id"
else
  pass "run started ($RUN_ID)"
  if python3 - "$BACKEND" "$RUN_ID" "$SSE_TIMEOUT" <<'PY'
import json, sys, time, urllib.request

backend, run_id, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
deadline = time.time() + timeout
seen = 0
with urllib.request.urlopen(f"{backend}/api/runs/{run_id}/events", timeout=timeout) as res:
    for raw in res:
        if time.time() > deadline:
            sys.exit("timed out before `done`")
        line = raw.decode().strip()
        if line.startswith("data: "):
            event = json.loads(line[6:])
            seen += 1
            if event["type"] == "done":
                sys.exit(0 if seen > 5 else f"stream ended after only {seen} events")
sys.exit("stream closed without `done`")
PY
  then pass "SSE stream reached done"; else fail "SSE stream did not reach done"; fi
  check "run view has 8 stages" json_ok "/api/runs/$RUN_ID" "len(d['stages']) == 8 and d['stages']['research']['status'] == 'review'"
fi

check "asset route serves a PNG" bash -c "curl -fsS --max-time 30 -o /dev/null -w '%{content_type}' '$BACKEND/api/assets/V001/campaign.png' | grep -q image/png"

# --- frontend: reachable, and no secret names in the shipped JS ---
if [[ -n "$FRONTEND" ]]; then
  HTML="$(curl -fsS --max-time 30 "$FRONTEND/" 2>/dev/null)"
  if [[ -z "$HTML" ]]; then
    fail "frontend $FRONTEND is not reachable"
  else
    pass "frontend is reachable"
    leaked=0
    scripts="$(printf '%s' "$HTML" | grep -oE '/_next/static/[^"]+\.js' | sort -u)"
    count=0
    for src in $scripts; do
      count=$((count + 1))
      if curl -fsS --max-time 30 "$FRONTEND$src" 2>/dev/null | grep -qE 'DEMO_KEY|MODEL_API_KEY|BASETEN_API_KEY'; then
        fail "secret name found in $src"
        leaked=1
      fi
    done
    if (( count == 0 )); then fail "no JS bundles found on the frontend home page"
    elif (( leaked == 0 )); then pass "no DEMO_KEY / MODEL_API_KEY in $count JS bundles"; fi
  fi
fi

echo "$PASS passed, $FAIL failed"
exit $(( FAIL > 0 ? 1 : 0 ))
