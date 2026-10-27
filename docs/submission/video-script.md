# CategoryOS - 3:00 demo video script

Live: https://categoryos.vercel.app . All data is synthetic. Fill every `{{BASELINE_*}}` from `baseline-timing-kit.md`. Do not say a number you have not measured; if a placeholder is empty, cut the line.

Arc: (1) onboarding one vendor eats a week of a category manager's time; (2) three moments where the agent protects the margin and the numbers (live-call deal evaluator, verifier self-correct, document vision); (3) the rest of the job, configurable and portable, ending on the impact meter.

| Time | Beat |
|---|---|
| 0:00-0:20 | Cold open |
| 0:20-1:00 | Hero 1: deal evaluator on a live call |
| 1:00-1:35 | Hero 2: verifier catches and self-corrects |
| 1:35-2:10 | Hero 3: document vision |
| 2:10-2:40 | Montage: Run ops, playbook, BYO |
| 2:40-3:00 | Close: impact meter, Meta models, URL |

## 0:00-0:20 Cold open
1. **Screen:** black, then a spreadsheet-and-email collage (static slide; make it from your own mock screenshots). Big counter overlay counting up to `{{BASELINE_HOURS_PER_VENDOR}}` h.
   **VO:** "A category manager onboarding one new vendor spends about {{BASELINE_HOURS_PER_VENDOR}} hours: screening documents, researching twelve SKUs, negotiating, building the catalog."
   **Caption:** `One vendor = {{BASELINE_HOURS_PER_VENDOR}} h by hand (measured)`
2. **Screen:** cut to https://categoryos.vercel.app/vendors/V001, stage rail visible.
   **VO:** "I'm a category manager. So I built the agent I wanted. Same vendor: {{BASELINE_MINUTES_WITH_COS}} minutes of review."
   **Caption:** `{{BASELINE_MINUTES_WITH_COS}} min with CategoryOS (measured)`

## 0:20-1:00 Hero 1: the deal evaluator rejects the offer on the call
1. **Screen:** `/vendors/V002` (Mewsli, litter) -> Negotiate stage -> click **Live call** (use **Simulate call** if the mic is flaky; say nothing different). Transcript streams; gap table fills row by row.
   **VO:** "Live vendor call. The agent transcribes it and fills the gap table as the vendor talks."
   **Caption:** `muse-voice-transcribe-1.0 + muse-spark-1.3`
2. **Screen:** vendor line lands: "15% base, plus 20% marketing support if you sell 2,000 units in 90 days." Hold on the red "Don't accept" chip (P(hit) below 0.1%).
   **VO:** "Fifteen percent base, twenty more if I hit an impossible target. Python simulates the demand: under a tenth of a percent chance. Don't accept."
   **Caption:** `P(hit target) < 0.1% -> reject the structure`
3. **Screen:** **Say next** card. Click it open to show the counter: 250 units, or a guaranteed 22%.
   **VO:** "And it hands me my next line: a target we can reach at 250 units, or a guaranteed twenty-two."
   **Caption:** `Say next: counter at 250 units or guaranteed 22%`

## 1:00-1:35 Hero 2: the verifier catches a wrong number
1. **Screen:** `/vendors/V001` -> Decide stage. Open the verifier card on the HP-D01 cost claim.
   **VO:** "Every number the agent states cites a source cell, and Python re-checks it."
   **Caption:** `Every claim cites a cell; Python re-checks it`
2. **Screen:** zoom on "Caught -> corrected": agent said Rs 965.50, sheet says Rs 956.50, attempt 2 correct.
   **VO:** "Here the model read nine sixty-five fifty. The sheet says nine fifty-six fifty. The verifier tells it the source, it corrects itself. A claim that never gets right never reaches the page."
   **Caption:** `Rs 965.50 -> caught -> Rs 956.50`
3. **Screen:** drag the target-margin lever; shortlist re-scores.
   **VO:** "And the levers are plain Python, so the what-if is instant."
   **Caption:** `Margin lever: deterministic, instant`

## 1:35-2:10 Hero 3: document vision
1. **Screen:** `/vendors/V002` -> Intake -> FSSAI certificate scan with the bounding box on the expiry date.
   **VO:** "Vendors send scans. The model reads the certificate: valid until 30 November. That's about a month away, and the application said 2027."
   **Caption:** `muse-spark-1.3 vision: licence expires soon`
2. **Screen:** `/vendors/V001` -> label panel; SAM crop of the nutrition panel; mismatch row: label 30% protein vs sheet 32%.
   **VO:** "SAM 3.1 cuts out the label panel, the crop is read again, and the label says thirty percent protein. The sheet claims thirty-two."
   **Caption:** `sam-3.1 crop -> re-read: 30% vs 32%`
3. **Screen:** price-list mismatch row (HP-D06 Rs 3,325 vs Rs 3,352).
   **VO:** "It also checks the price list against the sheet. Three mismatches I'd have found after listing, not before."
   **Caption:** `Caught before listing, not after`

## 2:10-2:40 Montage (about 5 s per shot, fast cuts, music up)
1. `/run` overview: "Run the category, not just onboard it."  Caption: `Category MIS`
2. `/run/price-requests`: vendor wants +8-12%, per-SKU accept/counter/delist.  Caption: `Price requests`
3. `/run/catalog` QC queue, `/run/promotions` plan, `/run/price-watch` undercut vs blip.  Caption: `Catalog QC, promotions, price watch`
4. `/rules`: edit a margin, show hash change.  VO: "Every rule is in a playbook I can edit."  Caption: `Playbook: every rule configurable`
5. `/try`: upload `data/samples` beauty sheet, then electronics.  VO: "Bring your own vendor, in pet, beauty or electronics."  Caption: `Bring your own vendor: pet, beauty, electronics`
   **VO over the whole montage:** "It then runs the category: price requests, catalog fixes, promotions, price watch. Inventory health is next."

## 2:40-3:00 Close
1. **Screen:** vendors board -> impact meter team projection (labelled estimate/measured per `impact.baseline_status`).
   **VO:** "Modelled across a real team's week, that's about a third less workload. {{BASELINE_MEASURED_CLAIM}}"
   **Caption:** `~33% modelled team workload reduction`
2. **Screen:** end card with model list.
   **VO:** "Built on Meta: Muse Spark for reasoning and vision, SAM 3.1, Muse Image, Muse Voice, and Muse Spark Open on Baseten."
   **Caption:** `muse-spark-1.3 | sam-3.1 | muse-image-1.0 | muse-voice-transcribe-1.0 | Muse Spark Open (Baseten)`
3. **Screen:** URL large.  **VO:** "CategoryOS. Try it now."  **Caption:** `categoryos.vercel.app`

If `baseline_status` is still `research_estimate`, say "modelled" and keep the on-screen label; never say "measured" for it.

## Recording checklist
- [ ] Record at 2560x1440, export 1080p or 1440p; browser window 1440 wide, zoom 110-125% so text is legible on a phone.
- [ ] Warm the backend: set `MIN_CONTAINERS=1` on Modal and hit `/api/mode` plus one run per vendor 5 minutes before recording. Check the mode banner; if still replay/mock, the "live" claim must not appear in VO.
- [ ] Clear site data / localStorage for categoryos.vercel.app (DevTools > Application > Clear site data), so no stale approvals and the impact meter starts fresh.
- [ ] Seeds: V001 Highland Paws (verifier + label + price list), V002 Mewsli (call + licence). Both are in the default data; no uploads needed except the `/try` samples.
- [ ] Hide bookmarks bar, notifications, and personal tabs; use a clean browser profile. Do not show any real employer name or data.
- [ ] Rehearse twice with a stopwatch; each hero beat must finish in its slot. Record each hero as its own take and edit.
- [ ] Mic: record VO separately, quiet room, then lay over screen capture; captions burned in (most viewers watch muted).
- [ ] If the live call fails, use "Simulate call"; the pipeline is identical.
- [ ] Final pass: every `{{...}}` replaced, no number spoken that is not on screen.

## 30-second cut for X (square or 16:9, captions burned in, no VO needed)
- 0:00-0:04 `One vendor onboarding = {{BASELINE_HOURS_PER_VENDOR}} h by hand.` (counter)
- 0:04-0:12 Live call: vendor offer -> red `P(hit) < 0.1% - don't accept` -> Say next card.
- 0:12-0:18 Verifier: `Rs 965.50 -> caught -> Rs 956.50`.
- 0:18-0:23 Label crop: `30% vs 32% protein`, licence `expires in a month`.
- 0:23-0:27 Fast montage: Run ops, playbook, /try.
- 0:27-0:30 `Built on Meta Muse | categoryos.vercel.app`
Post text: "I'm a category manager. I built the agent I wanted: it rejected a vendor's trap offer live, corrected its own wrong number, and caught an expiring licence. Built on Meta Muse. Try it: categoryos.vercel.app" (all data synthetic).
