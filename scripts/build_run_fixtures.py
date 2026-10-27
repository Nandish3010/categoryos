#!/usr/bin/env python3
"""Rebuild the MOCK model fixtures of the promotions planner and the competitor price monitor (backend/fixtures/mock/ops).

Usage (from the repo root): cd backend && PYTHONPATH=. uv run python ../scripts/build_run_fixtures.py

The fixtures stand in for muse-spark in MODEL_MODE=mock. They are hand-shaped like the live answers, but every number in their prose is
read from the engine (so it verifies) and every quote is copied verbatim from the data files. Re-run this after changing the playbook
knobs or the data that move the numbers; the tests fail when a fixture's figure no longer verifies.

Planted: in promo_funding_replies_festive the NutriPaws share is read as 53 (a digit transposition of the 35% in the email), the verifier
rejects it, and promo_funding_replies_festive__fix1 gives the corrected 35, which verifies."""

import json
from pathlib import Path
from typing import Any

from app.ops.data import load as load_ops
from app.ops.inventory_health import agent as iag
from app.ops.inventory_health import claims as ihc
from app.ops.inventory_health import engine as ihe
from app.ops.pricewatch import claims as pwc
from app.ops.pricewatch import engine as pwe
from app.ops.promotions import agent as pag
from app.ops.promotions import claims as pc
from app.ops.promotions import data as pdata
from app.ops.promotions import engine as pe
from app.ops.runclaims import fmt_shown

OUT = Path(__file__).resolve().parent.parent / "backend" / "fixtures" / "mock" / "ops"
MODEL = "muse-spark-1.3"


def write(name: str, content: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps({"model": MODEL, "input_tokens": 0, "output_tokens": 0, "content": content}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def fig(c: Any) -> dict[str, Any]:
    return {"metric": c.metric, "key": c.source_ref.key, "value": c.value, "shown": fmt_shown(c.unit, c.value), "text": c.text}


def S(c: Any) -> str:
    return fmt_shown(c.unit, abs(c.value))


# ---------------------------------------------------------------- price watch


def price_watch() -> None:
    r = pwe.analyse()
    acts = {a["id"]: a for a in r["actions"]}
    ids = {k: a for k, a in acts.items()}
    match = next(a for a in ids.values() if a["recommendation"] == "match")
    ask = next(a for a in ids.values() if a["recommendation"] == "ask_vendor_funding")
    breach = next(a for a in ids.values() if a["recommendation"] == "flag_breach")
    blip = next(a for a in ids.values() if a["kind"] == "blip")
    trend = next(a for a in ids.values() if a["kind"] == "trend")

    def by(a: dict[str, Any]) -> dict[str, Any]:
        return {c.metric: c for c in pwc.action_claims(a)}

    m, k, b, bl, tr = by(match), by(ask), by(breach), by(blip), by(trend)
    figs = [
        m["pw_below_pct"], m["pw_streak_days"], m["pw_match_price"], m["pw_margin_after_match_pct"], m["pw_floor_pct"], m["pw_margin_impact_inr"],
        k["pw_below_pct"], k["pw_streak_days"], k["pw_margin_after_match_pct"], k["pw_floor_pct"], k["pw_protection_ask_unit_inr"],
        b["pw_vendor_price"], b["pw_parity_below_pct"], b["pw_parity_days"], b["pw_map_price"],
        bl["pw_below_pct"], bl["pw_margin_impact_inr"], tr["pw_trend_pts_per_day"],
    ]
    narrative = "\n\n".join(
        [
            f"Match: {match['name']} has been {S(m['pw_below_pct'])} under our price on {match['competitor']['marketplace']} for {S(m['pw_streak_days'])} days. Matching at "
            f"{S(m['pw_match_price'])} keeps the margin at {S(m['pw_margin_after_match_pct'])}, above the {S(m['pw_floor_pct'])} floor, and earns {S(m['pw_margin_impact_inr'])} more over the horizon than holding.",
            f"Ask the vendor: {ask['name']} has been {S(k['pw_below_pct'])} under our price on {ask['competitor']['marketplace']} for {S(k['pw_streak_days'])} days. Matching would take the margin to "
            f"{S(k['pw_margin_after_match_pct'])}, under the {S(k['pw_floor_pct'])} floor, so we ask {ask['brand']} for price protection of {S(k['pw_protection_ask_unit_inr'])} a unit instead of cutting alone.",
            f"Breach: {breach['brand']} sells {breach['name']} at {S(b['pw_vendor_price'])} on {breach['vendor']['marketplace']}, {S(b['pw_parity_below_pct'])} under our price for {S(b['pw_parity_days'])} days and under "
            f"the {S(b['pw_map_price'])} minimum advertised price. We do not follow it down; the message asks for parity.",
            f"Leave alone: {blip['name']} dipped {S(bl['pw_below_pct'])} under us on {blip['competitor']['marketplace']} for a single day. Matching that blip would have cost {S(bl['pw_margin_impact_inr'])} of margin for nothing, so we hold and re-check tomorrow. "
            f"A competitor price on {trend['name']} is falling {S(tr['pw_trend_pts_per_day'])} points a day but has not crossed the undercut threshold; we watch it.",
        ]
    )
    write(
        "pw_brief",
        {
            "steps": [{"tool": "get_price_watch_summary", "args": {}}],
            "final": {
                "headline": "Match one price, ask one vendor for protection, flag one parity breach; leave the one-day blip and the slow slide alone.",
                "narrative": narrative,
                "figures": [fig(c) for c in figs],
            },
        },
    )
    d = load_ops().vendors
    first = lambda vid: d[vid].contact_name.split()[0]  # noqa: E731
    e_breach = (
        f"Hi {first(breach['vendor_id'])},\n\nOn {breach['vendor']['marketplace']}, {breach['name']} is listed at {S(b['pw_vendor_price'])} on your own storefront, {S(b['pw_parity_below_pct'])} under our price, "
        f"for {S(b['pw_parity_days'])} days. That breaks price parity and sits under the {S(b['pw_map_price'])} minimum advertised price. Please restore parity by Friday; we will not follow the lower price down.\n\nThanks"
    )
    e_ask = (
        f"Hi {first(ask['vendor_id'])},\n\nA competitor on {ask['competitor']['marketplace']} has been {S(k['pw_below_pct'])} under our price on {ask['name']} for {S(k['pw_streak_days'])} days. "
        f"Matching would take our margin to {S(k['pw_margin_after_match_pct'])}, under the {S(k['pw_floor_pct'])} floor. Could you share price protection of {S(k['pw_protection_ask_unit_inr'])} a unit for the next period?\n\nThanks"
    )
    write(
        "pw_vendor_emails",
        {
            "steps": [{"tool": "get_price_watch_summary", "args": {}}, {"tool": "get_vendor_contacts", "args": {}}],
            "final": {
                "emails": [
                    {"vendor_id": breach["vendor_id"], "subject": f"Price parity on {breach['name']}", "body": e_breach, "figures": [fig(c) for c in (b["pw_vendor_price"], b["pw_parity_below_pct"], b["pw_parity_days"], b["pw_map_price"])]},
                    {"vendor_id": ask["vendor_id"], "subject": f"Price protection request: {ask['name']}", "body": e_ask, "figures": [fig(c) for c in (k["pw_below_pct"], k["pw_streak_days"], k["pw_margin_after_match_pct"], k["pw_floor_pct"], k["pw_protection_ask_unit_inr"])]},
                ]
            },
        },
    )


# ---------------------------------------------------------------- inventory health


def inventory_health() -> None:
    r = ihe.analyse()
    acts = r["actions"]

    def by(a: dict[str, Any]) -> dict[str, Any]:
        return {c.metric: c for c in ihc.action_claims(a)}

    def pick(rec: str) -> dict[str, Any]:
        return next(a for a in acts if a["recommendation"] == rec)

    reorder, expedite, pause, rtv, liq = pick("reorder"), pick("expedite_po"), pick("pause_po"), pick("return_to_vendor"), pick("liquidate")
    o, e, p, t, q = by(reorder), by(expedite), by(pause), by(rtv), by(liq)
    figs = [
        o["ih_run_out_day"], o["ih_reorder_qty"], o["ih_reorder_cost_inr"],
        e["ih_run_out_day"], e["ih_short_days"],
        p["ih_pause_units"], p["ih_pause_cover_without_days"],
        t["ih_clear_units"], t["ih_rtv_credit_inr"], t["ih_rtv_days_left"],
        q["ih_liq_price_inr"], q["ih_liq_recovery_inr"],
    ]
    narrative = "\n\n".join(
        [
            f"Order now: {reorder['name']} runs out in {S(o['ih_run_out_day'])} days. Order {S(o['ih_reorder_qty'])} units ({S(o['ih_reorder_cost_inr'])} at cost) so the stock lasts until the next review. "
            f"{expedite['name']} runs out in {S(e['ih_run_out_day'])} days and its PO is late, which means about {S(e['ih_short_days'])} days out of stock unless {expedite['brand']} ships it now.",
            f"Overstock: {pause['name']} already has {S(p['ih_pause_cover_without_days'])} days of cover without its open PO. Pause the {S(p['ih_pause_units'])} units on it. "
            f"{rtv['name']}: return {S(t['ih_clear_units'])} units for {S(t['ih_rtv_credit_inr'])} of credit while the window has {S(t['ih_rtv_days_left'])} days left. "
            f"{liq['name']} has no return route; clear it on a promo at {S(q['ih_liq_price_inr'])} a unit to recover {S(q['ih_liq_recovery_inr'])}.",
        ]
    )
    notes = []
    for a, m, text in (
        (reorder, o, f"Stock ends in {S(o['ih_run_out_day'])} days, inside the vendor's lead time. Raise the order for {S(o['ih_reorder_qty'])} units today."),
        (expedite, e, f"The PO is past its promised date and the stock ends in {S(e['ih_run_out_day'])} days. Chase the vendor to ship now rather than ordering more."),
        (pause, p, f"Without the open PO there are still {S(p['ih_pause_cover_without_days'])} days of cover. Hold the {S(p['ih_pause_units'])} units."),
        (rtv, t, f"The vendor takes this back under sell-or-return for {S(t['ih_rtv_credit_inr'])} of credit, with {S(t['ih_rtv_days_left'])} days left in the window."),
        (liq, q, f"No return route: promote at {S(q['ih_liq_price_inr'])} a unit to recover {S(q['ih_liq_recovery_inr'])}."),
    ):
        used = [c for c in m.values() if S(c) in text]
        notes.append({"action_id": a["id"], "rationale": text, "figures": [fig(c) for c in used]})
    write(
        "ih_brief",
        {
            "steps": [{"tool": "get_inventory_summary", "args": {}}],
            "final": {
                "headline": "Reorder two SKUs, chase two late POs, pause one overbuy, and clear the stuck stock by return or promo.",
                "narrative": narrative,
                "figures": [fig(c) for c in figs],
                "notes": notes,
            },
        },
    )
    mails = []
    for vid in iag.vendors_to_message(acts):
        d = iag.template_email(vid, acts)
        mails.append({"vendor_id": d.vendor_id, "subject": d.subject, "body": d.body, "figures": [f.model_dump() for f in d.figures]})
    write("ih_vendor_emails", {"steps": [{"tool": "get_inventory_summary", "args": {}}, {"tool": "get_vendor_contacts", "args": {}}], "final": {"emails": mails}})


# ---------------------------------------------------------------- promotions

TRUTH = {  # what each funding reply really says (the model's reading), by reply id
    "F001": dict(stance="conditional_offer", summary="Barkley funds half the markdown if we guarantee a top-3 banner and the range sells a very high target.",
                 terms=[dict(share_pct=50, scope=[], threshold_units=3400, window_days=7, banner_top_n=3,
                             quote="We can fund 50% of the markdown on the Barkley range, provided you guarantee a top-3 banner and the range sells 3,400 units between 6th and 12th Nov.")]),
    "F002": dict(stance="offer", summary="Purrline funds a flat share of the markdown on every promoted SKU.",
                 terms=[dict(share_pct=30, scope=[], quote="Purrline will fund 30% of the markdown on every Purrline SKU you put on promo.")]),
    "F003": dict(stance="conditional_offer", summary="NutriPaws supports a share of the discount if the range reaches a sales target.",
                 terms=[dict(share_pct=35, scope=[], threshold_units=1150, window_days=7,
                             quote="NutriPaws can support 35% of the discount cost across our range if the range sells 1,150 units during 6-12 Nov.")]),
    "F004": dict(stance="decline", summary="Litterly will not fund any discount this quarter.", terms=[]),
    "F005": dict(stance="conditional_offer", summary="Groomwell funds a share on two hero SKUs in return for a top-3 banner.",
                 terms=[dict(share_pct=25, scope=["GW-01", "GW-03"], banner_top_n=3,
                             quote="Groomwell will fund 25% of the markdown on GW-01 and GW-03 for the Festive Sale if you give us a top-3 banner placement.")]),
    "F006": dict(stance="offer", summary="Tailwind funds a share on two SKUs and cannot restock before the sale.",
                 lead=(14, "our lead time is 14 days"), terms=[dict(share_pct=40, scope=["TW-01", "TW-02"], quote="We can fund 40% of the markdown on TW-01 and TW-02.")]),
    "F007": dict(stance="offer", summary="Purrline funds a smaller share for the Payday Sale.", terms=[dict(share_pct=20, scope=[], quote="For the Payday Sale we can fund 20% of the markdown")]),
}


def readings_for(event_id: str, wrong: dict[str, float] | None = None) -> list[dict[str, Any]]:
    out = []
    for r in pdata.replies_for(event_id):
        t = TRUTH[r.id]
        terms = []
        for x in t["terms"]:
            x = dict(x)
            if wrong and r.id in wrong:
                x["share_pct"] = wrong[r.id]
            terms.append({"share_pct": x.get("share_pct"), "scope": x.get("scope", []), "threshold_units": x.get("threshold_units"), "window_days": x.get("window_days"),
                          "banner_top_n": x.get("banner_top_n"), "quote": x["quote"]})
        lead = t.get("lead")
        out.append({"reply_id": r.id, "stance": t["stance"], "summary": t["summary"], "lead_time_days": lead[0] if lead else None, "lead_time_quote": lead[1] if lead else "", "terms": terms})
    return out


def vendors_for(event_id: str):
    from app.ops.promotions.schemas import FundingReading

    plan = pe.plan(event_id)
    readings = [FundingReading.model_validate(x) for x in readings_for(event_id)]
    replies = {r.id: (pdata.position(r.id), r) for r in pdata.replies_for(event_id)}
    claims = {c.id: c.model_copy(update={"status": "verified"}) for c, _ in pag.build_claims(readings, replies)}
    offers, notes = pag.offers_from(readings, claims, replies)
    return plan, pag.value_vendors(event_id, plan, offers, notes)


def promotions() -> None:
    for event_id in (e.id for e in pe.events()):
        if not pdata.replies_for(event_id):
            continue
        write(
            f"promo_funding_replies_{event_id}",
            {"steps": [{"tool": "get_funding_replies", "args": {"event_id": event_id}}], "final": {"readings": readings_for(event_id, wrong={"F003": 53} if event_id == "festive" else None)}},
        )
    write("promo_funding_replies_festive__fix1", {"fixes": [{"claim_id": "promo:F003:t0:share", "value": 35}]})

    for ev in pe.events():
        plan, vendors = vendors_for(ev.id)
        write(f"promo_brief_{ev.id}", brief(ev, plan, vendors))
        write(f"promo_funding_emails_{ev.id}", emails(ev, plan, vendors))


def brief(ev: Any, plan: dict[str, Any], vendors: list[Any]) -> dict[str, Any]:
    evc = {c.metric: c for c in pc.event_claims(ev.id)}
    rows = [r for r in plan["rows"] if r["status"] == "planned"]
    figs = [evc["promo_event_planned_skus"], evc["promo_event_gmv_inr"], evc["promo_event_incremental_margin_inr"], evc["promo_event_funding_ask_inr"], evc["promo_event_margin_at_ask_pct"]]
    p1 = (
        f"We promote {S(evc['promo_event_planned_skus'])} SKUs. They sell {S(evc['promo_event_gmv_inr'])} of GMV over the event and add {S(evc['promo_event_incremental_margin_inr'])} of margin after the units pulled "
        f"forward and the sales taken from near-duplicates. Holding the promo margin floor needs {S(evc['promo_event_funding_ask_inr'])} of vendor funding, which lifts the plan's margin to {S(evc['promo_event_margin_at_ask_pct'])}."
    )
    stock = []
    capped = next((r for r in rows if r["capped_by_stock"] and r["deep_option"]), None)
    if capped is not None:
        cc = {c.metric: c for c in pc.row_claims(ev.id, capped)}
        figs += [cc["promo_deep_discount_pct"], cc["promo_deep_stockout_day"], cc["promo_discount_pct"]]
        stock.append(
            f"{capped['name']} would run out on day {S(cc['promo_deep_stockout_day'])} of the event at {S(cc['promo_deep_discount_pct'])} off, the deepest discount that pays. "
            f"Its vendor cannot land fresh stock in time, so the plan caps it at {S(cc['promo_discount_pct'])}."
        )
    restock = next((r for r in rows if r["stock_up"]), None)
    if restock is not None:
        rc = {c.metric: c for c in pc.row_claims(ev.id, restock)}
        figs += [rc["promo_stock_up_qty"], evc["promo_event_stock_up_inr"]]
        stock.append(f"{restock['name']} can be restocked in time: the plan adds a stock-up PO of {S(rc['promo_stock_up_qty'])} units. Stock-up POs for the event cost {S(evc['promo_event_stock_up_inr'])} in all.")
    p2 = " ".join(stock) or "No SKU is at risk of a stock-out at the planned depth."
    lines = []
    for block, valued in vendors:
        if valued is None:
            continue
        vc = {c.metric: c for c in pc.vendor_claims(ev.id, block, valued)}
        if valued["decision"] == "declined":
            lines.append(f"{block['brand']} declined to fund the event.")
        elif valued["decision"] == "reject_structure" and "promo_offer_probability_pct" in vc:
            figs += [vc["promo_offer_probability_pct"], vc["promo_offer_counted_inr"]]
            lines.append(
                f"{block['brand']} offers half the markdown on a sales target the range has only a {S(vc['promo_offer_probability_pct'])} chance of reaching, so the offer counts as {S(vc['promo_offer_counted_inr'])}; we counter with a longer window."
            )
        else:
            figs += [vc["promo_offer_counted_inr"], vc["promo_offer_covers_ask_pct"]]
            kind = valued["counter"]["kind"]
            ending = {"accept": "that covers our ask", "top_up": "we ask for a bigger share", "firm_up": "we ask for a softer condition"}.get(kind, "we counter")
            lines.append(f"The offer from {block['brand']} counts for {S(vc['promo_offer_counted_inr'])}, {S(vc['promo_offer_covers_ask_pct'])} of our ask on its SKUs; {ending}.")
    p3 = " ".join(lines) or "No vendor has replied about funding yet; the asks go out as drafted."
    return {
        "steps": [{"tool": "get_event_plan", "args": {"event_id": ev.id}}, {"tool": "get_stock_risks", "args": {"event_id": ev.id}}, {"tool": "get_vendor_funding", "args": {"event_id": ev.id}}],
        "final": {"headline": f"Put {S(evc['promo_event_planned_skus'])} SKUs on promo for the {ev.name}, with {S(evc['promo_event_funding_ask_inr'])} of vendor funding asked.", "brief": "\n\n".join([p1, p2, p3]), "figures": [fig(c) for c in figs]},
    }


def emails(ev: Any, plan: dict[str, Any], vendors: list[Any]) -> dict[str, Any]:
    out = []
    for block, valued in vendors:
        d = pag.template_email(ev.id, block, valued)
        out.append({"vendor_id": d.vendor_id, "subject": f"{ev.name}: funding with {block['brand']}", "body": d.body, "figures": [f.model_dump() for f in d.figures]})
    return {"steps": [{"tool": "get_vendor_funding", "args": {"event_id": ev.id}}, {"tool": "get_vendor_contacts", "args": {}}], "final": {"emails": out}}


if __name__ == "__main__":
    price_watch()
    inventory_health()
    promotions()
    print(f"wrote fixtures to {OUT}")
