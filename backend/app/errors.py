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


class PublicBudgetExhausted(CategoryOSError):
    status = 429
    code = "public_budget_exhausted"
    problem = "Public live budget used up: showing the recorded run"
    cause = "The shared public live budget, or this address's share of it, is spent"
    fix = "Rules-only and recorded runs are free and unlimited; a demo key lifts the budget"


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


class RulePathUnknown(CategoryOSError):
    status = 422
    code = "rule_path_unknown"
    problem = "That is not a playbook setting a rule can change"
    cause = "A rule written as a prompt can only set a number, a switch or a choice that already exists in the playbook"
    fix = "Pick a setting shown in the playbook, or edit it in the form below"

    def __init__(self, path: str, *, cause: str | None = None, fix: str | None = None) -> None:
        super().__init__(f"{path!r} is not a playbook setting a rule can change", cause=cause, fix=fix)
        self.path = path

    def to_dict(self, run_id: str | None = None) -> dict:  # type: ignore[override]
        return {**super().to_dict(run_id), "path": self.path}


class RuleUnavailable(CategoryOSError):
    status = 422
    code = "rule_prompt_unavailable"
    problem = "Free-form rules need a model, and none is available here"
    cause = "Only the example prompts have recorded translations in this mode, and the public live budget for rules is off or not configured"
    fix = "Click one of the examples, edit the rule in the form, or run the backend locally (mock translates simple rules without a model)"


class UnknownActor(CategoryOSError):
    status = 422
    code = "unknown_actor"
    problem = "That team member is not in the playbook"
    cause = "The X-Acting-As header names an id that is not under governance.members"
    fix = "Pick a member from the Signed in as list"

    def __init__(self, member_id: str) -> None:
        super().__init__(f"unknown team member: {member_id!r}")
        self.member_id = member_id


class ChangeRefused(CategoryOSError):
    status = 403
    code = "change_refused"
    problem = "You are not allowed to make this change"
    cause = "The playbook's governance section does not give this role the permission"
    fix = "Ask someone with a higher role, or write the rule as a request the head can approve"

    def __init__(self, problem: str | None = None, *, cause: str | None = None, fix: str | None = None, change: dict | None = None) -> None:
        super().__init__(problem, cause=cause, fix=fix)
        self.change = change

    def to_dict(self, run_id: str | None = None) -> dict:  # type: ignore[override]
        return {**super().to_dict(run_id), "change": self.change}


class ChangeNotFound(CategoryOSError):
    status = 404
    code = "change_not_found"
    problem = "No change with this id"
    cause = "The id is unknown, belongs to another session, or has expired"
    fix = "Reload the change log and use one of its ids"

    def __init__(self, change_id: str) -> None:
        super().__init__(f"unknown change: {change_id!r}")
        self.change_id = change_id


class ChangeNotPending(CategoryOSError):
    status = 409
    code = "change_wrong_state"
    problem = "This change cannot take that action now"
    cause = "The change is not in the state that action needs (a preview to apply, a request to approve, an applied change to undo)"
    fix = "Reload the change log to see its current status"


class LeverOutOfRange(CategoryOSError):
    status = 422
    code = "lever_out_of_range"
    problem = "A lever value is outside the playbook's allowed range"
    cause = "The playbook bounds the what-if levers (levers.margin_offset, levers.moq)"
    fix = "Pick a value inside the range, or widen it in the playbook"


# ---------- Run (existing vendors) ----------


class UnknownOpsVendor(CategoryOSError):
    status = 404
    code = "unknown_ops_vendor"
    cause = "The id is not one of the existing vendors in data/synthetic/ops/vendors.json"
    fix = "Use an id from GET /api/ops/review (E001 to E006 in the synthetic data)"

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"unknown existing vendor: {vendor_id!r}")
        self.vendor_id = vendor_id


class UnknownPo(CategoryOSError):
    status = 404
    code = "unknown_po"
    cause = "The PO id is not in data/synthetic/ops/purchase_orders.csv"
    fix = "Use a PO id from GET /api/ops/pos"

    def __init__(self, po_id: str) -> None:
        super().__init__(f"unknown purchase order: {po_id!r}")
        self.po_id = po_id


class UnknownDraft(CategoryOSError):
    status = 404
    code = "unknown_draft"
    cause = "The draft id is not in the outbox, or the outbox was reset"
    fix = "List the outbox with GET /api/ops/outbox and use one of its ids"

    def __init__(self, draft_id: str) -> None:
        super().__init__(f"unknown draft: {draft_id!r}")
        self.draft_id = draft_id


class DraftNotPending(CategoryOSError):
    status = 409
    code = "draft_not_pending"
    problem = "This draft was already decided"
    cause = "Only drafts waiting for approval can be approved, edited or rejected"
    fix = "Open the outbox to see its status; a decided draft cannot be changed"


class OpsDataMissing(CategoryOSError):
    status = 500
    code = "ops_data_missing"
    problem = "The operations data files are missing or unreadable"
    cause = "data/synthetic/ops was not generated"
    fix = "Run python3 data/generate_ops.py from the repo root"


class UnknownOpsMetric(CategoryOSError):
    status = 422
    code = "unknown_ops_metric"
    cause = "The metric is not registered in app/ops/claims.py"
    fix = "Use a registered ops_* metric name"

    def __init__(self, metric: str) -> None:
        super().__init__(f"unknown ops metric: {metric!r}")
        self.metric = metric

class CallNotFound(CategoryOSError):
    status = 404
    code = "call_not_found"
    problem = "No call with this id"
    cause = "The call id is unknown, the call is for another vendor, or the backend restarted (calls live in memory)"
    fix = "Start a call with POST /api/vendors/{id}/call"

    def __init__(self, call_id: str) -> None:
        super().__init__(f"unknown call: {call_id!r}")
        self.call_id = call_id


class CallEnded(CategoryOSError):
    status = 409
    code = "call_ended"
    problem = "This call has ended"
    cause = "Turns and audio are only accepted while a call is running"
    fix = "Start a new call"


class LiveCallUnavailable(CategoryOSError):
    status = 409
    code = "live_call_unavailable"
    problem = "A live microphone call needs live mode"
    cause = "The Negotiate stage is not running live (MODEL_MODE=live with a MODEL_API_KEY), so there is no voice model to listen with"
    fix = "Use Simulate call, which streams the recorded call through the same pipeline at no cost, or run the backend live with the demo key"


class NoCallScript(CategoryOSError):
    status = 422
    code = "no_call_script"
    problem = "There is no recorded call to simulate for this vendor"
    cause = "Only vendors with a canonical call transcript (V002) can be simulated"
    fix = "Pick a vendor with a call transcript, or start a live call"


class CallBudgetExceeded(CategoryOSError):
    status = 429
    code = "call_budget_exceeded"
    problem = "This call reached its spend budget"
    cause = "Transcription and extraction for this call cost as much as CALL_BUDGET_USD allows"
    fix = "End the call and review it, or raise CALL_BUDGET_USD and restart the backend"


class ChunkTooLarge(CategoryOSError):
    status = 413
    code = "chunk_too_large"
    problem = "The audio chunk is too large"
    cause = "Chunks are short push-to-talk clips of about six seconds"
    fix = "Send smaller chunks (16 kHz mono WAV)"


class UnsupportedAudio(CategoryOSError):
    status = 415
    code = "unsupported_audio"
    problem = "The audio chunk is not a WAV file"
    cause = "muse-voice-transcribe-1.0 takes WAV audio; the chunk has no RIFF/WAVE header"
    fix = "Encode the chunk as 16 kHz mono 16-bit PCM WAV before uploading"


class CallNotAccepting(CategoryOSError):
    status = 409
    code = "call_not_accepting_input"
    problem = "This call does not take typed or recorded turns"
    cause = "A simulated call plays its own recorded script"
    fix = "Start a live call to speak into the pipeline"


# ---------- Run: catalog QC (fix queue for existing listings) ----------


class CatalogDataMissing(CategoryOSError):
    status = 500
    code = "catalog_data_missing"
    problem = "The live catalog files are missing or unreadable"
    cause = "data/synthetic/ops/catalog_live.csv, vendor_price_list.csv or catalog_licences.json was not generated"
    fix = "Run python3 data/generate_catalog_live.py from the repo root"


class UnknownCatalogFix(CategoryOSError):
    status = 404
    code = "unknown_catalog_fix"
    cause = "The fix id is not in the current queue (the playbook or the data changed, or the server restarted)"
    fix = "Reload the queue with GET /api/ops/catalog and use one of its fix ids"

    def __init__(self, fix_id: str) -> None:
        super().__init__(f"unknown catalog fix: {fix_id!r}")
        self.fix_id = fix_id


class CatalogFixNotPending(CategoryOSError):
    status = 409
    code = "catalog_fix_not_pending"
    problem = "This fix was already decided"
    cause = "Only fixes waiting for a decision can be approved or rejected"
    fix = "Open the catalog update outbox to see its status; a decided fix cannot be changed"


class CatalogFixBlocked(CategoryOSError):
    status = 409
    code = "catalog_fix_unverified"
    problem = "This fix has a proposed value the verifier did not confirm"
    cause = "At least one claim behind the fix was rejected or could not be checked, so it cannot be approved as proposed"
    fix = "Reject the fix, or correct the listing by hand; a fix whose claims all verify can be approved"


class BulkLimitExceeded(CategoryOSError):
    status = 409
    code = "bulk_limit_exceeded"
    problem = "That is more fixes than one bulk approve may apply"
    cause = "The playbook caps a bulk approve (catalog_qc.bulk_approve_limit) so a person looks at the batch"
    fix = "Select fewer fixes (filter the queue by issue type or vendor), or raise the limit in the playbook"

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(f"{count} fixes selected; the bulk-approve limit is {limit}")
        self.count, self.limit = count, limit


class EmptySelection(CategoryOSError):
    status = 422
    code = "empty_selection"
    problem = "No fixes were selected"
    cause = "The request listed no fix ids"
    fix = "Select at least one fix"


class PriceRequestNotFound(CategoryOSError):
    status = 404
    code = "price_request_not_found"
    problem = "No price request with this id"
    cause = "The id is not in the inbox, or the backend restarted (submitted requests live in memory)"
    fix = "List the inbox with GET /api/price-requests and use one of its ids"

    def __init__(self, request_id: str) -> None:
        super().__init__(f"unknown price request: {request_id!r}")
        self.request_id = request_id


class PriceRequestUnreadable(CategoryOSError):
    status = 422
    code = "price_request_unreadable"
    problem = "No price line in this request could be verified"
    cause = "Every line the model read failed the quote check, or the model read none"
    fix = "Check the email and price list text, or edit the lines by hand"


class PriceRequestInvalid(CategoryOSError):
    status = 422
    code = "price_request_invalid"
    problem = "The price request cannot be accepted"
    cause = "A required field is missing or too long"
    fix = "Send a known vendor, the email text and (optionally) the price list text"


class ApprovalTierTooLow(CategoryOSError):
    status = 403
    code = "approval_tier_too_low"
    problem = "This approver cannot approve this request"
    cause = "The playbook's approval matrix asks for a more senior approver for the size or kind of this decision"
    fix = "Escalate to the approver named in the problem, or counter with a smaller increase"


class PriceRequestDecided(CategoryOSError):
    status = 409
    code = "price_request_decided"
    problem = "This request has already been decided"
    cause = "A reply was approved or the request was rejected"
    fix = "Open a new request; a decision is final in this demo"


class UnknownCatalogLabel(CategoryOSError):
    status = 404
    code = "unknown_catalog_label"
    cause = "The file is not a pack label in data/synthetic/ops/catalog_labels/manifest.json"
    fix = "Use a label url from GET /api/ops/catalog"

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown label: {name!r}")
        self.name = name


class PromoDataMissing(CategoryOSError):
    status = 500
    code = "promo_data_missing"
    problem = "The promotions data files are missing or unreadable"
    cause = "data/synthetic/ops/promo_vendor_replies.json was not generated"
    fix = "Run python3 data/generate_promotions.py from the repo root"


class UnknownPromoEvent(CategoryOSError):
    status = 404
    code = "unknown_promo_event"
    cause = "The event id is not in the playbook's promotions.events calendar"
    fix = "List the events with GET /api/ops/promotions and use one of their ids"

    def __init__(self, event_id: str) -> None:
        super().__init__(f"unknown promotion event: {event_id!r}")
        self.event_id = event_id


class PromoPlanDecided(CategoryOSError):
    status = 409
    code = "promo_plan_decided"
    problem = "This event plan was already decided"
    cause = "The plan was approved or rejected; a decision is final until the server resets"
    fix = "Open the outbox to see what was queued, or reset the demo"


class PromoPlanEmpty(CategoryOSError):
    status = 409
    code = "promo_plan_empty"
    problem = "There is nothing to approve in this event plan"
    cause = "No SKU made the plan, or none of the SKUs named is in it"
    fix = "Loosen the playbook's promotions rules, or pick SKUs that are in the plan"


class PriceWatchDataMissing(CategoryOSError):
    status = 500
    code = "price_watch_data_missing"
    problem = "The price snapshot files are missing or unreadable"
    cause = "data/synthetic/ops/price_snapshots.csv, price_watch_map.csv or price_watch_meta.json was not generated"
    fix = "Run python3 data/generate_price_watch.py from the repo root"


class UnknownPriceWatchAction(CategoryOSError):
    status = 404
    code = "unknown_price_watch_action"
    cause = "The action id is not in the current price-watch list (the playbook or the data changed, or the server restarted)"
    fix = "Reload GET /api/ops/price-watch and use one of its action ids"

    def __init__(self, action_id: str) -> None:
        super().__init__(f"unknown price-watch action: {action_id!r}")
        self.action_id = action_id


class PriceWatchActionDecided(CategoryOSError):
    status = 409
    code = "price_watch_action_decided"
    problem = "This price-watch action was already decided"
    cause = "It was approved or rejected; a decision is final until the server resets"
    fix = "Open the outbox to see what was queued, or reset the demo"


class InventoryHealthDataMissing(CategoryOSError):
    status = 500
    code = "inventory_health_data_missing"
    problem = "The inventory health data files are missing or unreadable"
    cause = "data/synthetic/ops/inventory_terms.csv, inventory_legacy.csv or inventory_health_meta.json was not generated"
    fix = "Run python3 data/generate_inventory_health.py from the repo root"


class UnknownInventoryAction(CategoryOSError):
    status = 404
    code = "unknown_inventory_action"
    cause = "The action id is not in the current inventory health list (the playbook or the data changed, or the server restarted)"
    fix = "Reload GET /api/ops/inventory-health and use one of its action ids"

    def __init__(self, action_id: str) -> None:
        super().__init__(f"unknown inventory health action: {action_id!r}")
        self.action_id = action_id


class InventoryActionDecided(CategoryOSError):
    status = 409
    code = "inventory_action_decided"
    problem = "This inventory action was already decided"
    cause = "It was approved or rejected; a decision is final until the server resets"
    fix = "Open the outbox to see what was queued, or reset the demo"
