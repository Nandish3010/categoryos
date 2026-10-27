"""Typed errors. Every error carries code, problem, cause and fix: the same text goes to the
API response, the UI banner and the log line."""


class CategoryOSError(Exception):
    status = 500
    code = "internal_error"
    problem = "Something went wrong"
    cause = "An unexpected error occurred"
    fix = "Check the backend log for the run id and retry"

    def __init__(
        self,
        problem: str | None = None,
        *,
        cause: str | None = None,
        fix: str | None = None,
        code: str | None = None,
    ) -> None:
        self.problem = problem or self.problem
        self.cause = cause or self.cause
        self.fix = fix or self.fix
        self.code = code or self.code
        super().__init__(self.problem)

    def to_dict(self, run_id: str | None = None) -> dict[str, str | None]:
        return {
            "code": self.code,
            "problem": self.problem,
            "cause": self.cause,
            "fix": self.fix,
            "run_id": run_id,
        }


class UnknownVendor(CategoryOSError):
    status = 404
    code = "unknown_vendor"
    cause = "Only vendors V001 to V004 exist in the synthetic data"
    fix = "Use one of V001, V002, V003, V004"

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"unknown vendor: {vendor_id!r}")
        self.vendor_id = vendor_id


class UnknownMetric(CategoryOSError):
    status = 422
    code = "unknown_metric"
    cause = "The metric is not in metrics.METRIC_UNITS"
    fix = "Use a registered metric name, or add it to METRIC_UNITS in app/metrics.py"

    def __init__(self, metric: str) -> None:
        super().__init__(f"unknown metric: {metric!r}")
        self.metric = metric


class UnknownSource(CategoryOSError):
    status = 422
    code = "unknown_source"
    cause = "The source file is not on the verifier allowlist of real data files"
    fix = "Point source_ref.file at a file under data/synthetic (see verify.allowed_sources)"

    def __init__(self, source: str) -> None:
        super().__init__(f"unknown source: {source!r}")
        self.source = source


class MissingInput(CategoryOSError):
    status = 422
    code = "missing_input"
    cause = "A value needed for the computation is absent from the data"
    fix = "Check the vendor sheet for the SKU or field named in the problem"


class SpendCapExceeded(CategoryOSError):
    status = 429
    code = "spend_cap_exceeded"
    problem = "Live model calls are disabled: the spend cap was reached"
    cause = "Recorded spend is at or above MAX_SPEND_USD"
    fix = "Serve replay (MODEL_MODE=replay) or raise MAX_SPEND_USD and restart"


class MissingKey(CategoryOSError):
    status = 503
    code = "missing_key"
    problem = "Live mode needs an API key that is not set"
    cause = "MODEL_API_KEY (Meta) or BASETEN_API_KEY (Baseten) is empty"
    fix = "Set the key in the root .env, or run with MODEL_MODE=mock"


class CreditsUnavailable(CategoryOSError):
    status = 402
    code = "credits_unavailable"
    problem = "The model provider rejected the call (402/403)"
    cause = "Credits have not landed, are exhausted, or the key lacks access to this model"
    fix = "Check the provider dashboard, then retry; replay mode keeps the demo running"


class LlmUnavailable(CategoryOSError):
    status = 503
    code = "llm_unavailable"
    problem = "The model provider is unavailable"
    cause = "Timeouts or rate limits persisted after retries"
    fix = "Retry shortly, or switch to replay (MODEL_MODE=replay)"


class LlmBadOutput(CategoryOSError):
    status = 502
    code = "llm_bad_output"
    problem = "The model returned output that could not be used"
    cause = "Empty, refused, or schema-invalid response after one repair attempt"
    fix = "Retry, simplify the prompt, or re-record the fixture with make record"


class FixtureMissing(CategoryOSError):
    status = 500
    code = "fixture_missing"
    problem = "No fixture exists for this model call"
    cause = "Mock and replay modes read canned responses from backend/fixtures"
    fix = "Run make record (needs live credits) or add the fixture file named in the problem"


class DemoKeyRequired(CategoryOSError):
    status = 403
    code = "demo_key_required"
    problem = "This route needs the demo key"
    cause = "The X-Demo-Key header is missing or wrong"
    fix = "Send X-Demo-Key with the value of DEMO_KEY"


class RateLimited(CategoryOSError):
    status = 429
    code = "rate_limited"
    problem = "Too many requests from this address"
    cause = "The per-IP limit for keyed routes was exceeded"
    fix = "Wait a minute and retry"


class RunNotFound(CategoryOSError):
    status = 404
    code = "run_not_found"
    problem = "No run with this id"
    cause = "The run id is unknown, or the store was reset"
    fix = "Start a run with POST /api/vendors/{id}/runs, or read the id from runs/latest"

    def __init__(self, run_id: str) -> None:
        super().__init__(f"unknown run: {run_id!r}")
        self.run_id = run_id


class UnknownStage(CategoryOSError):
    status = 404
    code = "unknown_stage"
    cause = "The stage id is not one of the eight pipeline stages"
    fix = "Use one of intake, research, shortlist, negotiate, catalog, marketing, jbp, po"

    def __init__(self, stage: str) -> None:
        super().__init__(f"unknown stage: {stage!r}")
        self.stage = stage


class UnknownSku(CategoryOSError):
    status = 404
    code = "unknown_sku"
    cause = "The SKU code is not part of this stage's narrative"
    fix = "Use a code from data.rationale_per_sku of the stage result"

    def __init__(self, sku_code: str) -> None:
        super().__init__(f"unknown sku: {sku_code!r}")
        self.sku_code = sku_code


class StaleApproval(CategoryOSError):
    status = 409
    code = "stale_approval"
    problem = "The approval was for different numbers than the narrative describes"
    cause = "The metrics hash sent with the approval differs from the hash the narrative was generated for"
    fix = "Click Re-plan with agent so the narrative matches the current levers, then approve again"


class StageNotReviewable(CategoryOSError):
    status = 409
    code = "stage_not_reviewable"
    problem = "This stage cannot be approved, overridden or re-planned right now"
    cause = "The stage is not in review or done state"
    fix = "Wait for the stage to finish, or start a new run"


class StageLocked(CategoryOSError):
    status = 409
    code = "stage_locked"
    problem = "This stage is locked"
    cause = "An earlier stage failed, so later stages cannot run"
    fix = "Resolve the failure in the earlier stage and start a new run"


class AssetNotFound(CategoryOSError):
    status = 404
    code = "asset_not_found"
    problem = "No such asset"
    cause = "The file name is not a catalog image the pipeline produces, or it has not been generated yet"
    fix = "Run the catalog stage for this vendor, then use an image url from data.skus[].images"


class NarrativeUnavailable(CategoryOSError):
    status = 422
    code = "narrative_unavailable"
    problem = "Narrative available in live mode"
    cause = "Replay mode only holds recorded narratives for the preset margin offsets (0, +2, +4) at the vendor's default MOQ"
    fix = "Use a preset (0, +2, +4) or run live"


class PolicyInvalid(CategoryOSError):
    status = 422
    code = "policy_invalid"
    problem = "The playbook is invalid"
    cause = "A value in the playbook failed validation"
    fix = "Correct the field shown and save again"

    def __init__(self, problem: str | None = None, *, cause: str | None = None, fix: str | None = None, code: str | None = None, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(problem, cause=cause, fix=fix, code=code)
        self.errors = errors or []

    def to_dict(self, run_id: str | None = None) -> dict:  # type: ignore[override]
        first = self.errors[0]["path"] if self.errors else None
        return {**super().to_dict(run_id), "path": first, "errors": self.errors}


class PolicyReadOnly(CategoryOSError):
    status = 403
    code = "policy_read_only"
    problem = "The playbook is read-only in this mode"
    cause = "Replay mode serves recorded runs, which were made under the default playbook"
    fix = "Run the backend locally (MODEL_MODE=mock or live) to edit the playbook"


class LeverOutOfRange(CategoryOSError):
    status = 422
    code = "lever_out_of_range"
    problem = "A lever value is outside the playbook's allowed range"
    cause = "The playbook bounds the what-if levers (levers.margin_offset, levers.moq)"
    fix = "Pick a value inside the range, or widen it in the playbook"
