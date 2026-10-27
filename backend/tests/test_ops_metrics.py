"""Run: deterministic metrics, anomaly detection, stock-out risk and the escalation ladder, on small hand-built data."""

from datetime import date, datetime, timedelta

import pytest

from app import policy
from app.ops import metrics as m
from app.ops import pos
from app.ops.data import Batch, OpsData, PoLine, Reply, Return, Sku, Vendor
from app.ops.dates import add_business_days, resolve_eta

AS_OF = date(2026, 10, 26)  # Monday
END = AS_OF - timedelta(days=1)


def ops():
    return policy.get().operations


def build(daily: dict[str, list[int]], **over) -> OpsData:
    """daily[sku] = units per day, oldest first, ending on END."""
    vendors = {"E001": Vendor("E001", "Acme Ltd", "Acme", "Asha", "asha@acme.example", "food", 7)}
    skus = {c: Sku(c, "E001", f"Item {c}", 100, 60, 90) for c in daily}
    sales = {c: {END - timedelta(days=len(u) - 1 - i): (n, n * 90.0) for i, n in enumerate(u)} for c, u in daily.items()}
    base = {
        "as_of": AS_OF, "data_end": END, "vendors": vendors, "skus": skus, "sales": sales, "batches": [], "po_lines": [], "returns": [], "ratings": {}, "replies": [],
        "weeks": len(next(iter(daily.values()))) // 7,
    }
    base.update(over)
    return OpsData(**base)


def flat(n_weeks: int, per_day: int) -> list[int]:
    return [per_day] * (7 * n_weeks)


def line(po="PO-E001-0001", sku="A", ordered=100, received=100, promised=AS_OF - timedelta(days=10), actual=None, status="closed") -> PoLine:
    return PoLine(po, "E001", sku, ordered, received, promised - timedelta(days=7), promised, actual if actual or status == "open" else promised, status)


# ---------- sales, growth, z-score ----------


def test_week_ranges_and_growth():
    d = build({"A": flat(3, 10)})
    assert m.week_range(d, 0) == (END - timedelta(days=6), END)
    assert m.weekly(d, ["A"], 0, "units") == 70 and m.weekly(d, ["A"], 0) == 70 * 90
    assert m.growth(105, 100) == 0.05 and m.growth(5, 0) is None


def test_zscore_needs_a_baseline_with_spread():
    assert m.zscore(10, [10, 10, 10, 10]) is None  # zero spread: undefined
    assert m.zscore(10, [1, 2]) is None  # too few weeks
    assert m.zscore(20, [10, 12, 8, 10]) == pytest.approx(6.12, abs=0.01)


def test_sales_spike_is_flagged_and_noise_is_not():
    spike = [n for w in range(6) for n in [10 + w % 3] * 7] + [20] * 7
    steady = [n for w in range(7) for n in [10 + w % 3] * 7]
    d = build({"A": spike, "B": steady})
    cards = {"E001": m.vendor_scorecard(d, ops(), "E001")}
    found = {(a["type"], a["sku_code"]) for a in m.detect_anomalies(d, ops(), cards) if a["type"].startswith("sales_")}
    assert found == {("sales_spike", "A")}


def test_small_skus_are_too_noisy_to_test():
    tiny = [1, 0, 1, 0, 1, 0, 1] * 6 + [4] * 7  # below min_weekly_units
    d = build({"A": tiny})
    cards = {"E001": m.vendor_scorecard(d, ops(), "E001")}
    assert not [a for a in m.detect_anomalies(d, ops(), cards) if a["type"] in {"sales_spike", "sales_drop"}]


# ---------- fill rate and OTIF ----------


def test_fill_rate_counts_only_lines_past_their_promised_date():
    d = build({"A": flat(13, 5)}, po_lines=[line(ordered=100, received=80), line(sku="A", ordered=100, received=100), line(promised=AS_OF + timedelta(days=3), received=0, status="open")])
    assert m.fill_rate(m.due_lines(d, "E001")) == 0.9  # the not-yet-due line is ignored


def test_otif_needs_on_time_and_in_full_with_grace_and_threshold():
    promised = AS_OF - timedelta(days=20)
    lines = [
        line(promised=promised, actual=promised),  # on time, full
        line(promised=promised, actual=promised + timedelta(days=1)),  # inside the 1 day grace
        line(promised=promised, actual=promised + timedelta(days=2)),  # late
        line(promised=promised, actual=promised, received=97),  # 97% < 98% in-full threshold
        line(promised=promised, actual=promised, received=98),  # exactly at the threshold
    ]
    d = build({"A": flat(13, 5)}, po_lines=lines)
    assert m.otif_counts(d, ops(), "E001") == (3, 5)


def test_open_lines_inside_the_grace_window_are_not_judged_but_overdue_ones_fail():
    yesterday = AS_OF - timedelta(days=1)
    old = AS_OF - timedelta(days=5)
    d = build({"A": flat(13, 5)}, po_lines=[line(promised=yesterday, received=0, status="open"), line(promised=old, received=0, status="open")])
    assert m.otif_counts(d, ops(), "E001") == (0, 1)


def test_falling_fill_rate_is_flagged_with_the_recent_and_earlier_numbers():
    early = [line(po=f"PO-E001-{i:04d}", promised=AS_OF - timedelta(days=60 + i)) for i in range(4)]
    recent = [line(po=f"PO-E001-{i + 10:04d}", received=60, promised=AS_OF - timedelta(days=5 + i), actual=AS_OF - timedelta(days=5 + i)) for i in range(3)]
    d = build({"A": flat(13, 5)}, po_lines=early + recent)
    card = m.vendor_scorecard(d, ops(), "E001")
    assert card["fill_rate_recent"] == 0.6 and card["fill_rate_prior"] == 1.0
    flagged = [a for a in m.detect_anomalies(d, ops(), {"E001": card}) if a["type"] == "fill_rate"]
    assert flagged and "60%" in flagged[0]["reason"] and "100%" in flagged[0]["reason"]


# ---------- stock cover and ageing ----------


def test_stock_cover_uses_the_demand_window():
    d = build({"A": flat(13, 10)}, batches=[Batch("A", AS_OF - timedelta(days=5), 120)])
    assert m.on_hand(d, "A") == 120 and m.daily_rate(d, ops(), "A") == 10 and m.cover_days(d, ops(), "A") == 12


def test_low_cover_and_zero_stock_raise_stockout():
    d = build({"A": flat(13, 10), "B": flat(13, 10)}, batches=[Batch("A", AS_OF, 50)])  # A: 5 days, B: nothing on hand
    cards = {"E001": m.vendor_scorecard(d, ops(), "E001")}
    stockouts = {a["sku_code"]: a for a in m.detect_anomalies(d, ops(), cards) if a["type"] == "stockout"}
    assert set(stockouts) == {"A", "B"} and stockouts["B"]["severity"] == 3 and stockouts["B"]["value"] == 0


def test_ageing_buckets_follow_the_playbook_edges():
    batches = [Batch("A", AS_OF - timedelta(days=10), 10), Batch("A", AS_OF - timedelta(days=45), 10), Batch("A", AS_OF - timedelta(days=75), 10), Batch("A", AS_OF - timedelta(days=200), 10)]
    d = build({"A": flat(13, 1)}, batches=batches)
    out = m.ageing(d, ops(), ["A"])
    assert [b["units"] for b in out["buckets"]] == [10, 10, 10, 10]
    assert [b["label"] for b in out["buckets"]] == ["0-30 days", "31-60 days", "61-90 days", "over 90 days"]
    assert out["aged_pct"] == 0.25 and out["total_value_inr"] == 2400
    policy.save_overrides({"operations": {"scorecard": {"ageing_buckets_days": [60, 120]}}})
    assert [b["units"] for b in m.ageing(d, ops(), ["A"])["buckets"]] == [20, 10, 10]


def test_bucket_edges_must_increase():
    with pytest.raises(Exception) as exc:
        policy.save_overrides({"operations": {"scorecard": {"ageing_buckets_days": [60, 30]}}})
    assert "increasing" in str(exc.value.errors) or "increasing" in str(exc.value)


# ---------- returns and ratings ----------


def test_return_rate_and_rating_change():
    ratings = {"A": [(END - timedelta(days=7 * (4 - i)), r) for i, r in enumerate([4.4, 4.3, 4.1, 3.9, 3.6])]}
    d = build({"A": flat(13, 10)}, returns=[Return(END - timedelta(days=3), "A", 14, "damaged in transit")], ratings=ratings)
    assert m.return_rate(d, ["A"]) == 0.05  # 14 of 280
    assert m.rating_change(d, "A") == -0.8 and m.rating(d, "A") == 3.6
    assert m.return_reasons(d, "A") == [("damaged in transit", 14)]


# ---------- stock-out risk ----------


def risk(cover_days: int, promised_in: int, eta: date | None = None, units_per_day=10):
    d = build({"A": flat(13, units_per_day)}, batches=[Batch("A", AS_OF, cover_days * units_per_day)])
    ln = line(promised=AS_OF + timedelta(days=promised_in), received=0, status="open")
    return pos.line_risk(d, ops(), ln, eta)


def test_stockout_risk_compares_cover_with_the_remaining_lead_time():
    safe = risk(cover_days=20, promised_in=5)
    assert (safe["risk"], safe["stockout_days"]) == ("low", 0)
    tight = risk(cover_days=6, promised_in=5)  # 1 day of margin, buffer is 2
    assert (tight["risk"], tight["stockout_days"]) == ("medium", 0)
    out = risk(cover_days=3, promised_in=5)
    assert (out["risk"], out["stockout_days"], out["lost_gmv"]) == ("high", 2, 2 * 10 * 90)
    assert risk(cover_days=1, promised_in=10)["risk"] == "critical"


def test_verified_vendor_date_overrides_the_promised_date():
    late = risk(cover_days=6, promised_in=2, eta=AS_OF + timedelta(days=9))
    assert (late["arrival_basis"], late["stockout_days"]) == ("vendor_reply", 3)


def test_overdue_po_with_no_date_assumes_the_default_lead_time():
    d = build({"A": flat(13, 10)}, batches=[Batch("A", AS_OF, 30)])
    row = pos.line_risk(d, ops(), line(promised=AS_OF - timedelta(days=4), received=0, status="open"))
    assert row["arrival_basis"] == "assumed" and row["remaining_lead_days"] == ops().po_followup.default_lead_days
    assert row["stockout_days"] == 4  # 7 days wait, 3 days of cover


def test_no_demand_means_no_stockout():
    d = build({"A": flat(13, 0)})
    row = pos.line_risk(d, ops(), line(promised=AS_OF + timedelta(days=3), received=0, status="open"))
    assert row["cover_days"] is None and row["risk"] == "low"


# ---------- ladder ----------


@pytest.mark.parametrize(("overdue", "rung"), [(-5, None), (-2, "Nudge"), (0, "Nudge"), (1, "Chase"), (3, "Chase"), (4, "Escalate"), (8, "Formal notice"), (40, "Formal notice")])
def test_ladder_picks_the_highest_rung_reached(overdue, rung):
    got = pos.rung_for(ops(), overdue, vague=False)
    assert (got["name"] if got else None) == rung


def test_a_vague_reply_moves_a_late_po_up_one_rung_but_not_beyond_the_top():
    assert pos.rung_for(ops(), 2, vague=True)["name"] == "Escalate"
    assert pos.rung_for(ops(), 2, vague=True)["bumped_by_vague_reply"] is True
    assert pos.rung_for(ops(), 10, vague=True)["name"] == "Formal notice"
    assert pos.rung_for(ops(), -1, vague=True)["name"] == "Nudge"  # not late yet: no bump
    policy.save_overrides({"operations": {"po_followup": {"vague_reply_bumps_rung": False}}})
    assert pos.rung_for(ops(), 2, vague=True)["name"] == "Chase"


def test_ladder_must_be_ordered():
    with pytest.raises(Exception) as exc:
        policy.save_overrides({"operations": {"po_followup": {"ladder": [{"name": "b", "days_overdue": 5}, {"name": "a", "days_overdue": 1}]}}})
    assert "order" in str(exc.value)


def test_tracker_orders_by_risk_then_lateness():
    d = build({"A": flat(13, 10), "B": flat(13, 10)}, batches=[Batch("A", AS_OF, 20), Batch("B", AS_OF, 500)],
              po_lines=[line(po="PO-E001-0001", sku="B", promised=AS_OF - timedelta(days=9), received=0, status="open"),
                        line(po="PO-E001-0002", sku="A", promised=AS_OF - timedelta(days=1), received=0, status="open")])
    rows = pos.tracker(d, ops())
    assert [r["po_id"] for r in rows] == ["PO-E001-0002", "PO-E001-0001"]  # A can run out; B is only late


# ---------- reading dates in vendor phrases ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We will deliver on 29th Oct as per PO", date(2026, 10, 29)),
        ("will ship the balance by 3rd Nov", date(2026, 11, 3)),
        ("ready by Nov 3", date(2026, 11, 3)),
        ("Will reach by Thursday for sure", date(2026, 10, 29)),  # received on Monday 26 Oct
        ("by Monday", date(2026, 11, 2)),  # the same weekday means next week
        ("will dispatch tomorrow", date(2026, 10, 27)),
        ("in 3 days", date(2026, 10, 29)),
        ("approx 5-6 working days from today", date(2026, 11, 3)),  # later end of the range, weekends skipped
        ("delivery 12/11", date(2026, 11, 12)),
        ("Dispatch will be done next week", None),
        ("will be sent shortly, will revert", None),
    ],
)
def test_resolve_eta(text, expected):
    assert resolve_eta(text, date(2026, 10, 26)) == expected


def test_business_days_skip_weekends():
    assert add_business_days(date(2026, 10, 22), 6) == date(2026, 10, 30)  # Thursday + 6 working days
    assert add_business_days(date(2026, 10, 23), 1) == date(2026, 10, 26)  # Friday -> Monday


def test_reply_dataclass_is_plain_data():
    r = Reply("R1", "PO-E001-0001", "E001", datetime(2026, 10, 26, 9, 0), "a@b.example", "s", "b")
    assert r.received_at.date() == AS_OF
