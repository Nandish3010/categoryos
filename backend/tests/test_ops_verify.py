"""Run: the generator, planted issues, claim verification (engine and reply extractions) and the self-correction loop."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.config import settings
from app.errors import UnknownOpsMetric, UnknownOpsVendor
from app.ops import base as ob
from app.ops import chaser, outbox, review
from app.ops import claims as oc
from app.ops.data import file_sha256, load
from app.ops.schemas import Figure
from app.ops.verify import unclaimed_numbers
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Evidence, SourceRef
from app.verify import verify_all, verify_claim

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fresh():
    outbox.reset()
    yield
    outbox.reset()


def run(coro):
    return asyncio.run(coro)


# ---------- generator and planted issues ----------


def test_generator_is_deterministic_and_matches_committed_files(tmp_path):
    spec = importlib.util.spec_from_file_location("generate_ops", ROOT / "data" / "generate_ops.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.OUT = str(tmp_path)
    gen.main()
    for f in tmp_path.iterdir():
        assert f.read_bytes() == (ROOT / "data" / "synthetic" / "ops" / f.name).read_bytes(), f"{f.name} differs from the committed file"


def test_data_shape():
    d = load()
    assert len(d.vendors) == 6 and len(d.skus) == 36
    assert d.weeks == 13 and len(d.sales["BK-01"]) == 91
    assert any(ln.status == "open" for ln in d.po_lines) and any(ln.status == "closed" for ln in d.po_lines)
    assert len(d.replies) == 7 and all(r.po_id.startswith("PO-") for r in d.replies)


def test_the_planted_issues_are_surfaced():
    b = ob.base()
    found = {a["id"] for a in b.anomalies}
    assert "fill_rate:E002" in found  # falling fill rate
    assert "stockout:NP-03" in found and "stockout:LT-05" in found and "stockout:PL-01" in found  # SKUs about to run out
    assert "ageing:E004" in found and "overstock:TW-05" in found  # ageing inventory
    assert {"returns:GW-02", "rating:GW-02", "sales_drop:GW-03"} <= found
    assert "sales_spike:BK-02" in found
    assert "E001" not in {a["vendor_id"] for a in b.anomalies if a["type"] != "sales_spike"}  # the healthy vendor stays clean
    assert b.cards["E002"]["fill_rate_recent"] < 0.6
    assert b.cards["E002"]["fill_rate_prior"] > 0.95
    assert b.actions[0]["id"] == "act:stockout:NP-03"


# ---------- engine claims ----------


def test_engine_claims_verify_and_wrong_values_are_rejected():
    ok = oc.engine_claim("ops_fill_rate_recent", "E002", "Purrline recent fill rate")
    assert verify_claim(ok).status == "verified"
    bad = oc.engine_claim("ops_fill_rate_recent", "E002", "Purrline recent fill rate", value=0.45)
    out = verify_claim(bad)
    assert out.status == "rejected" and "recomputed" in out.reason
    assert out.recomputed == oc.compute("ops_fill_rate_recent", "E002")


def test_every_registered_metric_computes_at_a_sample_key():
    keys = {"category": "category", "vendor": "E002", "sku": "E002:PL-01", "po": "PO-E002-0012", "line": "PO-E002-0012:PL-01"}
    for name, mdef in oc.METRICS.items():
        claim = oc.engine_claim(name, keys[mdef.scope], name)
        assert verify_claim(claim).status == "verified", name


def test_claims_are_checked_against_the_data_they_were_built_from(monkeypatch):
    claim = oc.engine_claim("ops_gmv", "E001", "Barkley GMV")
    stale = claim.model_copy(update={"evidence": claim.evidence.model_copy(update={"sha256": "0" * 64})})
    assert verify_claim(stale).reason.startswith("source changed")


def test_unknown_things_are_rejected_with_a_reason_not_an_exception():
    claim = oc.engine_claim("ops_gmv", "E001", "x")
    assert verify_claim(claim.model_copy(update={"source_ref": SourceRef(file="ops/secret.csv", key="E001")})).status == "rejected"
    assert verify_claim(claim.model_copy(update={"metric": "ops_nonsense"})).status == "unverifiable"
    assert "cannot recompute" in verify_claim(claim.model_copy(update={"source_ref": SourceRef(file=oc.SALES, key="E099")})).reason
    with pytest.raises(UnknownOpsVendor):
        oc.card("E099")
    with pytest.raises(UnknownOpsMetric):
        oc.compute("ops_nonsense", "E001")


def test_stockout_claims_depend_on_the_assumed_arrival_date():
    soon = oc.compute("ops_stockout_days", "PO-E003-0010:NP-03?eta=2026-10-28")
    late = oc.compute("ops_stockout_days", "PO-E003-0010:NP-03?eta=2026-11-03")
    assert soon < late == 8


# ---------- numbers written in prose ----------


def test_prose_numbers_need_a_figure_ids_dates_and_product_sizes_do_not():
    text = "PO-E002-0012 for Clumping Bentonite 5 kg is 7 days late; E002 fill is 54%. Reply by Tuesday 27 Oct. Last 4 weeks look bad."
    names = ["Clumping Bentonite 5 kg"]
    assert unclaimed_numbers(text, ["7 days", "54%"], names) == []
    assert unclaimed_numbers(text, ["54%"], names) == ["7"]
    assert unclaimed_numbers("We lost ₹3.4 lakh and 120 units", ["₹3.4 lakh"]) == ["120"]


def test_a_prose_number_that_disagrees_with_the_engine_is_what_gets_checked():
    from app.ops.figures import figure_claim

    right = Figure(metric="ops_fill_rate_recent", key="E002", value=0.5437, shown="54%", text="t")
    wrong_shown = Figure(metric="ops_fill_rate_recent", key="E002", value=0.5437, shown="45%", text="t")  # value fine, prose says 45%
    assert verify_claim(figure_claim(right, "a")).status == "verified"
    assert verify_claim(figure_claim(wrong_shown, "b")).status == "rejected"
    signed = Figure(metric="ops_sku_rating_change", key="E006:GW-02", value=-0.74, shown="0.74", text="t")  # "down 0.74 stars"
    assert verify_claim(figure_claim(signed, "c")).status == "verified"
    lakh = Figure(metric="ops_cat_gmv", key="category", value=1365809, shown="₹13.7 lakh", text="t")
    assert verify_claim(figure_claim(lakh, "d")).status == "verified"
    off = Figure(metric="ops_cat_gmv", key="category", value=1365809, shown="₹15 lakh", text="t")
    assert verify_claim(figure_claim(off, "e")).status == "rejected"
    unknown = Figure(metric="made_up", key="E001", value=1, shown="1", text="t")
    assert verify_claim(figure_claim(unknown, "f")).status == "unverifiable"


# ---------- reply extractions ----------


def reply_claim(reply_id: str, metric: str, value: float, quote: str, position: int | None = None) -> Claim:
    replies = load().replies
    pos_ = position or next(i for i, r in enumerate(replies, start=1) if r.id == reply_id)
    return Claim(
        id=f"t:{reply_id}:{metric}",
        text="t",
        value=value,
        metric=metric,
        unit="units" if metric == "reply_eta_days" else "qty",
        source_ref=SourceRef(file=oc.REPLIES, key=reply_id, column="body"),
        evidence=Evidence(row=pos_, header="body", raw_value=quote, normalized_value=value, parser_version=PARSER_VERSION, sha256=file_sha256(oc.REPLIES)),
        origin="model_extraction",
    )


def test_a_correct_quantity_and_date_verify():
    assert verify_claim(reply_claim("R003", "reply_qty", 600, "Balance 600 units is still under production")).status == "verified"
    assert verify_claim(reply_claim("R003", "reply_eta_days", 11, "We will ship the balance by 3rd Nov")).status == "verified"  # 23 Oct + 11 days
    assert verify_claim(reply_claim("R002", "reply_eta_days", 3, "Will reach by Thursday for sure")).status == "verified"


def test_a_quote_that_is_not_in_the_reply_is_rejected():
    out = verify_claim(reply_claim("R003", "reply_qty", 600, "Balance 600 units will definitely ship tomorrow"))
    assert out.status == "rejected" and "verbatim" in out.reason


def test_a_quantity_the_quote_does_not_state_is_rejected_with_what_it_does_state():
    out = verify_claim(reply_claim("R003", "reply_qty", 900, "Balance 600 units is still under production"))
    assert out.status == "rejected" and "600" in out.reason and out.recomputed == 600


def test_a_wrong_date_is_rejected_with_the_date_the_quote_resolves_to():
    out = verify_claim(reply_claim("R004", "reply_eta_days", 7, "approx 5-6 working days from today"))
    assert out.status == "rejected" and "2026-10-30" in out.reason and out.recomputed == 8  # the later end of the range


def test_a_date_claimed_from_a_vague_promise_is_rejected():
    out = verify_claim(reply_claim("R006", "reply_eta_days", 3, "will be sent shortly"))
    assert out.status == "rejected" and "no date" in out.reason
    assert verify_claim(reply_claim("R005", "reply_eta_days", 7, "Dispatch will be done next week")).status == "rejected"


def test_evidence_must_cite_the_right_reply_and_an_unchanged_file():
    assert verify_claim(reply_claim("R003", "reply_qty", 600, "Balance 600 units is still under production", position=5)).status == "rejected"
    claim = reply_claim("R003", "reply_qty", 600, "Balance 600 units is still under production")
    stale = claim.model_copy(update={"evidence": claim.evidence.model_copy(update={"sha256": "1" * 64})})
    assert verify_claim(stale).reason.startswith("source changed")
    no_quote = claim.model_copy(update={"evidence": claim.evidence.model_copy(update={"raw_value": None})})
    assert verify_claim(no_quote).status == "rejected"


def test_verify_all_routes_ops_and_onboarding_claims_separately():
    summary = verify_all([oc.engine_claim("ops_gmv", "E001", "x")])
    assert (summary.total, summary.verified) == (1, 1)


# ---------- the chaser end to end (mock fixtures) ----------


def test_chaser_verifies_every_extraction_and_self_corrects_the_planted_mistake():
    out = run(chaser.generate())
    assert out["verification"]["rejected"] == 0 and out["verification"]["unverifiable"] == 0
    assert out["corrected"] == ["reply:R004:0"] and out["unresolved"] == []
    r004 = next(r for r in out["readings"] if r["reply_id"] == "R004")
    commit = r004["commitments"][0]
    assert commit["corrected"] and commit["first_value"] == 7 and commit["resolved_eta"] == "2026-10-30"
    types = [t["type"] for t in out["trace"]]
    assert types.index("claim_rejected") < types.index("self_correction") < types.index("claim_verified")


def test_chaser_tracker_uses_only_verified_dates_and_reads_vagueness():
    rows = {r["po_id"]: r for r in run(chaser.generate())["pos"]}
    e3, e5, e2, e4 = rows["PO-E003-0010"], rows["PO-E005-0008"], rows["PO-E002-0012"], rows["PO-E004-0007"]
    assert e3["eta"] == "2026-11-03" and e3["risk"] == "critical" and e3["stockout_days"] == 8
    assert e5["eta"] is None and e5["vague_reply"] and e5["rung"]["name"] == "Formal notice" and e5["rung"]["bumped_by_vague_reply"]
    assert e2["eta"] == "2026-10-29" and e2["rung"]["name"] == "Chase" and e2["risk"] == "low"
    assert e4["rung"]["name"] == "Nudge" and e4["eta"] == "2026-10-30"
    assert rows["PO-E001-0010"]["needs_chase"] is False and rows["PO-E006-0008"]["needs_chase"] is False


def test_an_unresolved_wrong_extraction_never_reaches_the_tracker(monkeypatch):
    import app.selfcorrect as sc

    monkeypatch.setattr(sc.policy.get().verifier, "max_self_corrections", 0)
    out = run(chaser.generate())
    assert out["unresolved"] == ["reply:R004:0"]
    e4 = next(r for r in out["pos"] if r["po_id"] == "PO-E004-0007")
    assert e4["eta"] is None  # falls back to the promised date, never the unverified one
    assert e4["lines"][0]["arrival_basis"] == "promised_date"


def test_chaser_drafts_are_queued_not_sent_and_all_numbers_are_claimed():
    out = run(chaser.generate())
    assert out["unclaimed_numbers"] == []
    assert {d["po_id"] for d in out["drafts"]} == {"PO-E005-0008", "PO-E003-0010", "PO-E002-0012", "PO-E004-0007"}
    assert all(d["status"] == "pending" and d["simulated"] for d in out["drafts"])
    assert next(d for d in out["drafts"] if d["po_id"] == "PO-E002-0012")["channel"] == "whatsapp"
    assert {x["root_cause"] for x in out["ledger"]} >= {"packing", "production"}


def test_chaser_inject_is_caught():
    out = run(chaser.generate(inject=True))
    assert out["verification"]["rejected"] == 1
    assert next(c for c in out["claims"] if c["status"] == "rejected")["origin"] == "injected_test"


# ---------- the review end to end ----------


def test_review_numbers_all_verify_and_every_number_in_prose_has_a_claim():
    out = run(review.generate())
    assert out["verification"]["rejected"] == 0 and out["verification"]["total"] > 50
    assert out["unclaimed_numbers"] == []
    assert out["flagged_vendors"] == ["E002", "E003", "E004", "E005", "E006"]
    assert {d["vendor_id"] for d in out["drafts"]} == set(out["flagged_vendors"]) and all(d["source"] == "agent" for d in out["drafts"])


def test_review_actions_follow_the_agents_order_but_keep_the_deterministic_rank():
    out = run(review.generate())
    first = out["actions"][0]
    assert first["rank"] == 1 and first["deterministic_rank"] == 1 and first["rationale"]
    moved = next(a for a in out["actions"] if a["id"] == "act:stockout:PL-01")
    assert moved["rank"] == 4 and moved["deterministic_rank"] == 3 and moved["llm_rank"] == 4
    assert len(out["actions"]) == 8


def test_mis_pack_has_tables_and_the_commentary():
    md = run(review.generate())["mis_markdown"]
    for heading in ("# Category MIS", "## Category summary", "## What to do this week", "## Vendor scorecard", "## Commentary", "## Anomalies"):
        assert heading in md
    assert "| Vendor | GMV |" in md and "Purrline Foods" in md and "₹13,65,809" in md


def test_review_inject_is_caught_and_never_cached():
    out = run(review.generate(inject=True))
    bad = [c for c in out["claims"] if c["status"] == "rejected"]
    assert len(bad) == 1 and bad[0]["origin"] == "injected_test"


def test_a_missing_vendor_in_the_agent_output_gets_a_template_email(monkeypatch):
    from app import llm

    real = llm.run_tools

    async def trimmed(stage, task, *a, **kw):
        res = await real(stage, task, *a, **kw)
        if task == "review_emails":
            res.parsed.emails = [e for e in res.parsed.emails if e.vendor_id != "E006"]
        return res

    monkeypatch.setattr(llm, "run_tools", trimmed)
    out = run(review.generate())
    e6 = next(d for d in out["drafts"] if d["vendor_id"] == "E006")
    assert e6["source"] == "template" and "Deshedding Brush" in e6["body"]
    assert out["verification"]["rejected"] == 0


def test_impact_coverage_is_registered_from_the_playbook():
    out = run(review.generate())["impact_coverage"]
    assert out["registered"] and out["status"] == "shipped" and out["baseline_status"] == "research_estimate"
    assert {t["task"] for t in out["tasks"]} == {"vendor_scorecards", "reporting_mis"}
    assert out["manual_minutes_replaced"] == 240 + 6 * 75
    po = run(chaser.generate())["impact_coverage"]
    assert po["module"] == "po_followup" and po["tasks"] == [{"task": "po_replenishment", "in_scope_pct": 90.0}]
    assert po["manual_minutes_replaced"] == 4 * 15 + 6 * 45


def test_data_dir_is_the_synthetic_folder():
    assert Path(settings.data_dir).name == "synthetic" and (Path(settings.data_dir) / "ops" / "meta.json").exists()
