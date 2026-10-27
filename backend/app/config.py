import tempfile
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    model_api_key: str | None = None
    model_api_base_url: str = "https://api.meta.ai/v1"
    baseten_api_key: str | None = None
    baseten_base_url: str = "https://inference.baseten.co/v1"
    demo_key: str | None = None

    model_mode: Literal["mock", "live", "replay"] = "mock"
    live_stages: str = ""
    max_spend_usd: float = 120
    record: bool = False
    ledger_path: Path = BACKEND_DIR / ".ledger.json"
    db_path: Path = BACKEND_DIR / ".categoryos.db"
    sse_heartbeat_s: float = 15.0
    demo_today: str | None = None  # ISO date; freezes the clock used by check_documents
    rate_limit_per_min: int = 20
    warn_spend_usd: float = 100

    model_text: str = "muse-spark-1.3"
    model_text_dev: str = "muse-spark-1.3-contributor"
    model_image: str = "muse-image-1.0"
    model_seg: str = "sam-3.1"
    model_voice: str = "muse-voice-transcribe-1.0"
    baseten_model: str = "meta-models/muse-spark-open"

    assets_dir: Path = BACKEND_DIR / "fixtures" / "assets"
    sam_enabled: bool = True  # SAM go/no-go: False -> cutouts are "unavailable" and the packshot is shown

    data_dir: Path = REPO_DIR / "data" / "synthetic"
    fixtures_dir: Path = BACKEND_DIR / "fixtures"
    config_dir: Path = REPO_DIR / "config"  # playbook defaults (policy.yaml)
    policy_local_path: Path | None = None  # playbook overrides; default config_dir/policy.local.yaml

    # Bring-your-own-vendor sandbox (ops limits; the business rules stay in the playbook)
    state_dir: Path = Path(tempfile.gettempdir()) / "categoryos-state"  # writable; a Volume path on Modal; never the repo
    samples_dir: Path = REPO_DIR / "data" / "samples"
    upload_ttl_hours: float = 24
    upload_max_sheet_bytes: int = 2 * 1024 * 1024
    upload_max_rows: int = 200
    upload_max_columns: int = 30
    upload_max_cell_chars: int = 2000
    upload_max_docs: int = 5
    upload_max_doc_bytes: int = 5 * 1024 * 1024
    upload_max_application_bytes: int = 64 * 1024
    upload_rate_per_hour: int = 12  # uploads per IP per hour
    upload_max_active: int = 300  # sandbox vendors alive at once, so a flood cannot fill the disk
    upload_live_budget_usd_per_ip: float = 0.50  # model spend one IP may cause on sandbox vendors without the demo key
    upload_cleanup_interval_min: float = 30

    backend_port: int = 8001
    frontend_origin: str | None = None

    @property
    def effective_mode(self) -> str:
        if self.model_mode == "live" and not self.model_api_key:
            return "mock"
        return self.model_mode


settings = Settings()
