"""Modal deployment of the CategoryOS backend (deploy deliberately: `modal deploy backend/modal_app.py`, see scripts/deploy.md).

* Dependencies are pinned from uv.lock: ``backend/requirements.txt`` (regenerate with ``make requirements``).
* The image carries the app, ``config`` (the playbook defaults), ``data/synthetic`` and ``backend/fixtures`` (golden runs, mock fixtures); no .env is baked in.
* Secrets come from the Modal Secret ``categoryos-secrets`` (MODEL_API_KEY, BASETEN_API_KEY, DEMO_KEY).
* SQLite and the spend ledger live on the Volume ``categoryos-state`` (/state); committed after state changes.
* One container (in-process run state + SSE), scale-to-zero by default, ~10 minute idle window.

Deploy-time environment: MODEL_MODE (default replay), FRONTEND_ORIGIN (the Vercel URL, for CORS), MIN_CONTAINERS (default 0),
PUBLIC_LIVE_BUDGET_USD / PUBLIC_LIVE_PER_IP_USD / PUBLIC_LIVE_FEATURES (opt-in public live budget, see scripts/deploy.md).
"""

import os
from pathlib import Path

import modal

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent

STATE_DIR = "/state"
DATA_DIR = "/root/data/synthetic"
FIXTURES_DIR = "/root/fixtures"
CONFIG_DIR = "/root/config"
SAMPLES_DIR = "/root/samples"

image_env = {
    "MODEL_MODE": os.environ.get("MODEL_MODE", "replay"),
    "DATA_DIR": DATA_DIR,
    "FIXTURES_DIR": FIXTURES_DIR,
    "CONFIG_DIR": CONFIG_DIR,
    "POLICY_LOCAL_PATH": f"{STATE_DIR}/policy.local.yaml",  # playbook edits survive restarts on the Volume
    "DB_PATH": f"{STATE_DIR}/categoryos.db",
    "LEDGER_PATH": f"{STATE_DIR}/ledger.json",
    "STATE_DIR": f"{STATE_DIR}/sandbox",  # uploaded sandbox vendors (24 h TTL) live on the Volume, never in the image
    "SAMPLES_DIR": SAMPLES_DIR,
    "TRUST_FORWARDED_FOR": os.environ.get("TRUST_FORWARDED_FOR", "false"),  # true only once Modal's proxy is confirmed to set X-Forwarded-For (per-IP public budget)
}
if os.environ.get("FRONTEND_ORIGIN"):
    image_env["FRONTEND_ORIGIN"] = os.environ["FRONTEND_ORIGIN"]
for _name in ("PUBLIC_LIVE_BUDGET_USD", "PUBLIC_LIVE_PER_IP_USD", "PUBLIC_LIVE_FEATURES"):  # opt-in public live budget (off by default)
    if os.environ.get(_name):
        image_env[_name] = os.environ[_name]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(BACKEND_DIR / "requirements.txt"))
    .env(image_env)
    # add_local_* must come last: these are mounted at container start, not baked into the image layers
    .add_local_python_source("app")
    .add_local_dir(REPO_DIR / "data" / "synthetic", DATA_DIR)
    .add_local_dir(REPO_DIR / "data" / "samples", SAMPLES_DIR)
    .add_local_dir(REPO_DIR / "config", CONFIG_DIR, ignore=["policy.local.yaml"])
    .add_local_dir(BACKEND_DIR / "fixtures", FIXTURES_DIR, ignore=["**/__pycache__/**"])
)

state_volume = modal.Volume.from_name("categoryos-state", create_if_missing=True)

app = modal.App("categoryos-backend", image=image)


@app.function(
    secrets=[modal.Secret.from_name("categoryos-secrets")],
    volumes={STATE_DIR: state_volume},
    max_containers=1,  # run state and SSE subscribers are in-process
    min_containers=int(os.environ.get("MIN_CONTAINERS", "0")),
    scaledown_window=600,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def fastapi_app():
    from app import persist
    from app.main import app as web_app

    persist.set_hook(state_volume.commit)  # SQLite + ledger writes reach the Volume (throttled)
    return web_app
