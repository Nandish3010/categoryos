.PHONY: setup dev demo test data lint live record smoke requirements

BACKEND_PORT ?= 8001
BACKEND_URL := http://localhost:$(BACKEND_PORT)

setup:
	cd backend && uv sync
	cd frontend && npm ci

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --port $(BACKEND_PORT) --reload) & \
	(cd frontend && NEXT_PUBLIC_BACKEND_URL=$(BACKEND_URL) npm run dev) & \
	wait

# Replay the recorded golden runs: no keys, no database, deterministic. This is what the public deploy serves.
demo:
	@echo "Open http://localhost:3000/vendors/V001"
	@MODEL_MODE=replay $(MAKE) dev

test:
	cd backend && uv run pytest -q
	cd frontend && npm test -- --run

data:
	python3 data/generate.py

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

live:
	@echo "WARNING: live mode calls paid model APIs and costs credits (cap: MAX_SPEND_USD)."
	@MODEL_MODE=live $(MAKE) dev

# Re-record backend/fixtures/golden/runs/*.json from the mock pipeline (free, deterministic).
# To capture LIVE runs instead (costs credits; needs MODEL_API_KEY / BASETEN_API_KEY in .env):
#   cd backend && MODEL_MODE=live RECORD=1 uv run python -m app.record --vendor V001
record:
	cd backend && uv run python -m app.record --vendor all

# Regenerate the pinned requirements used by the Modal image (commit the result).
requirements:
	cd backend && uv export --no-dev --format requirements-txt --no-hashes --no-emit-package modal -o requirements.txt

# make smoke URL=https://<backend>.modal.run [FRONTEND_URL=https://<app>.vercel.app]
smoke:
	@test -n "$(URL)" || (echo "usage: make smoke URL=<backend url> [FRONTEND_URL=<frontend url>]" >&2; exit 2)
	scripts/smoke_deployed.sh "$(URL)" $(FRONTEND_URL)
