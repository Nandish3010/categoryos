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

    call_budget_usd: float = 2.0  # live copilot: most one call may spend on transcription and extraction (ops: env, not playbook)
    call_chunk_max_bytes: int = 2_000_000  # largest audio chunk accepted (a 6 s 16 kHz mono WAV is about 190 KB)
    copilot_sim_speed: float = 1.0  # pacing of "Simulate call" (1 = realistic speaking speed); tests set a huge number

    backend_port: int = 8001
    frontend_origin: str | None = None

    @property
    def effective_mode(self) -> str:
        if self.model_mode == "live" and not self.model_api_key:
            return "mock"
        return self.model_mode


settings = Settings()
