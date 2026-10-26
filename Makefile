.PHONY: setup dev demo test data lint live smoke

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

demo:
	@echo "Open http://localhost:3000/vendors/V001"
	@MODEL_MODE=replay $(MAKE) dev

test:
	cd backend && uv run pytest -q

data:
	python3 data/generate.py

lint:
	cd backend && uv run ruff check .

live:
	@echo "WARNING: live mode calls paid model APIs and costs credits (cap: MAX_SPEND_USD)."
	@MODEL_MODE=live $(MAKE) dev

smoke:
	@echo "TODO: smoke test against URL=$(URL)"
