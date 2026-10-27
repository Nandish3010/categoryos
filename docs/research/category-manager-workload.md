# Category manager / team workload and CategoryOS coverage

Method note. Web search found no study, survey or published time-use breakdown of e-commerce category managers or executives. Every percentage below is my estimate, built from three kinds of source:
- Job-description responsibility lists. These are qualitative only.
- Published SLAs and process facts.
- The 8-step category management model.

Cited facts are tagged [C]. Estimates are tagged [E]. Treat the figures as priors to be replaced by a time-diary from 2-3 real category teams (e.g. Supertails buyers), which is worth doing before the demo claims a number.

## Evidence base (all weak or indirect)
- [C] Amazon India, Vodafone, Toolsvilla and other postings list the same duties:
  - vendor and brand onboarding;
  - negotiating price, lead time, terms and marketing co-investment;
  - P&L and margin;
  - assortment and lifecycle;
  - promotions with marketing and supply;
  - forecasting;
  - vendor quality issues;
  - performance reviews.
  - They give no time split.
- [C] The Amazon private-brands "day in the life" runs: supplier conversations, then customer feedback and vendor quality, then promotions and listings with marketing, then a data review.
- [C] Flipkart catalog-edit QC takes about 48 hours (Fynd/Jio docs; third-party). Nykaa listing approval takes 7-10 business days. Nykaa brand-application approval takes 5-7 business days, with 25-30 days quoted for full onboarding and cataloging (Unicommerce, Fynd; the sources conflict).
- [C] The 8-step ECR/Nielsen model is: definition, role, assessment, scorecard, strategy, tactics, implementation, review. NielsenIQ calls assessment the most time-consuming step.
- [C, secondhand, unverified] McKinsey is said to say that up to two-thirds of buyer time is "busy work". Gartner is said to say that 83% of retailers used spreadsheets for merchandise management. A 2017 Symphony GOLD survey found 54% of retailers had inconsistent or incomplete data, and 27% of manufacturers spent 3-5 days consolidating category-insight data. A Bamboo Rose survey found 60%+ use Outlook/Excel as their main sourcing tools.
- [C] Brynjolfsson, Li and Raymond, "Generative AI at Work": about 14-15% more issues resolved per hour for customer-support agents, 34% for novices, and little gain for experts. Dell'Acqua/BCG "jagged frontier" (25% faster, 40% higher quality on in-frontier tasks) is from my memory and I could not verify it here.
- Not found, so do not cite:
  - any McKinsey/BCG/Bain/Redseer figure on category-manager time use;
  - Reddit/Quora/Glassdoor first-person splits;
  - quick-commerce vendor SLAs.
- Ignore the StealthAgents "head of category time statistics" page. It is unverifiable aggregation.

## 1-3. Task taxonomy, time share, automation (all [E] unless tagged)

Assumptions:
- 45-hour week.
- A team of 1 category manager (CM) and 2 category executives (CE).
- Mid-size Indian marketplace or D2C retailer with an active vendor base.
- Percentages sum to 100.
- Brackets are ranges.

"Saved" is the percentage of that task's time saved if automated with human review. "In scope" is the share of the task that CategoryOS today (new-vendor onboarding) touches.

| # | Task | Frequency / time per occurrence | CM % week | CE % week | Automation | Saved | CategoryOS in-scope |
|---|---|---|---|---|---|---|---|
| 1 | New vendor/brand sourcing, screening, research, negotiation, terms | 0.5-1 vendor/wk; ~10-18 h team per vendor | 14 [10-18] | 9 [6-13] | High | 45% [30-60] | 100% |
| 2 | Assortment planning / SKU add-drop (existing) | monthly + ad hoc; 2-4 h | 7 [4-10] | 5 [3-8] | Med | 30% | 0 |
| 3 | Existing-vendor cost / price-increase requests | 2-6 per week; ~90 min each | 6 [3-9] | 4 [2-6] | High | 50% [35-65] | 0 |
| 4 | Pricing and margin management (competitive match, margin mix) | daily/weekly; 15-60 min | 6 [4-9] | 5 [3-7] | Med | 25% | 0 |
| 5 | Catalog create/QC/fix (creation about 30%, fixes/updates about 70%) | per SKU 20-30 min new, 10-15 min fix | 3 [2-5] | 18 [12-26] | High | 55% [40-70] | creation only (30%) |
| 6 | Content / images coordination | per SKU 10 min + vendor chasing | 2 | 6 | Med | 45% | 30% |
| 7 | Promotions, sale events, co-op marketing funding | 2-4 events/month; 6-10 h each | 9 [6-12] | 7 [4-10] | Med | 35% | 0 |
| 8 | JBP / annual plan / QBR | quarterly 8-20 h per top vendor | 6 [3-9] | 2 | Med-High | 50% | 20% (first-year plan for new vendors) |
| 9 | PO raising, replenishment, fill-rate / PO follow-up | daily; 10-20 min per PO/chase | 5 [3-8] | 10 [6-15] | High | 55% [40-70] | 10% (first PO) |
| 10 | Inventory health (ageing, liquidation, RTV) | weekly 2-4 h | 4 [2-6] | 5 [3-7] | Med | 40% | 0 |
| 11 | Vendor scorecards / performance reviews | monthly 1-2 h per vendor | 3 [2-5] | 3 | High | 65% | 0 |
| 12 | Compliance (licences, claims, recalls) | per vendor/SKU 5-15 min | 2 | 4 | Med-High | 40% | 30% (at onboarding) |
| 13 | Reporting / MIS / dashboards (weekly business review, ad-hoc pulls) | weekly 4-8 h per head | 8 [5-12] | 9 [6-14] | High | 65% [50-80] | 0 |
| 14 | Internal meetings, escalations, stakeholder alignment | daily | 14 [10-18] | 5 | Low | 5% | 0 |
| 15 | Competitor / price monitoring | daily 20-40 min | 3 | 4 | High | 60% | 0 |
| 16 | Customer reviews / complaints triage | daily 15-30 min | 2 | 3 | Med-High | 50% | 0 |
| 17 | Other (admin, travel, learning) | n/a | 6 | 1 | Low | 0% | 0 |

Reasoning behind the shares:
- The CM share is weighted to negotiation, stakeholder work and judgment. Postings emphasise these.
- The CE share is weighted to execution: catalog, PO chasing, MIS. This is typical of how Indian teams are staffed, but it is my inference.
- The McKinsey "up to two-thirds busy work" claim (unverified) would imply the high-automation rows (1, 3, 5, 9, 11, 13, 15) are over half of CE time. My estimates have them at about 66% of CE time and about 40% of CM time, which is consistent.
- Where evidence is weakest: rows 7, 8, 10 and the CM/CE split of row 1.

## 4. Coverage analysis

Current CategoryOS scope is the in-scope share of rows 1, 5, 6, 8, 9 and 12.

| | In-scope % of week | Time saved (% of week) |
|---|---|---|
| CM | about 18% | about 8% (range 5-12) |
| CE | about 19% | about 9% (range 5-13) |
| Team (1 CM + 2 CE, hours-weighted) | about 19% | **about 9% (range 5-13)** |

Honest framing: CategoryOS is a strong tool for the 10-18 hours of work per new vendor. But new-vendor onboarding is a minority of a steady-state team's week, so it yields only about 9% total savings. If the team is in a heavy expansion phase, with vendor onboarding at 25%+ of workload, the saving rises to about 15%.

### Modules to reach 33% (ranked by team-hours saved per build effort)

Build effort is on a 1-5 scale, my estimate, assuming reuse of CategoryOS's LLM, sheet-parsing and negotiation components. "Team pts" is the saving added to the team's week.

| Rank | Module | CM pts | CE pts | Team pts | Effort | Pts/effort |
|---|---|---|---|---|---|---|
| 1 | Weekly vendor-performance review + MIS auto-generation (rows 11, 13) | 7.2 | 7.8 | 7.6 | 2 | 3.8 |
| 2 | Existing-vendor price-increase evaluator (row 3) | 3.0 | 2.0 | 2.3 | 1.5 | 1.5 (3.4 incl. pricing/margin) |
| 3 | PO follow-up / fill-rate chaser (row 9) | 2.8 | 5.5 | 4.6 | 2 | 2.3 |
| 4 | Catalog QC / fix queue on existing SKUs (row 5, 70% remainder) | 1.1 | 6.3 | 4.6 | 2 | 2.3 |
| 5 | Promotions / event planning (row 7) | 3.2 | 2.5 | 2.7 | 3 | 0.9 |
| 6 | Competitor price monitor (row 15) | 1.8 | 2.4 | 2.2 | 3 | 0.7 |
| 7 | Inventory health / liquidation (row 10) | 1.6 | 2.0 | 1.9 | 3 | 0.6 |

Cumulative team saving: base 9%, then modules 1-4 reach about 29%, module 5 reaches about 32%, module 6 reaches about 34%. A realistic claim is **"about one-third, with 30-35% as the plausible range"**. Discount by 20-30% for adoption friction and review overhead, which gives about 25%. Also say the time freed is for capacity, not headcount.

Specs:
1. **Weekly review + MIS generator.** Ingest the weekly sales, margin, stock and fill-rate sheets. Use deterministic code for the metrics and the LLM only for narrative. Produce the weekly business review pack, a per-vendor scorecard (fill rate, OTIF, return rate, margin, price index, complaints) and flagged exceptions. Draft vendor-facing review notes. Human edits and approves. Backlog shrinks because the data model is reusable by modules 3 and 4.
2. **Price-increase evaluator.** Take the vendor's request email or sheet and parse the SKU-level new cost. Compare against the old cost, the market price from research, the margin floor, the sell-through elasticity, and competitor price. Output accept / counter / reject with a counter-offer and a justification. Reuse the negotiation gap analysis and conditional-offer evaluator, and draft the reply. Minimal new build.
3. **PO follow-up / fill-rate chaser.** Watch open POs against promised ship dates and ASNs. Auto-draft chase emails and WhatsApp messages with escalation tiers. Maintain a fill-rate ledger with root-cause tagging. Propose reorder quantities from sell-through and lead time. A CE reviews a daily exception list rather than checking each PO.
4. **Catalog QC / fix queue.** Run the listing-generator's compliance checks and image checks as a batch on live catalog exports. Flag title, attribute, image, claim and category errors. Auto-fix common ones into upload-ready sheets (Flipkart/Amazon/Nykaa templates). Track marketplace QC rejections (Flipkart about 48 h, Nykaa 7-10 days) and re-submit.
5. **Promotions / event planner.** Select candidate SKUs by stock, margin and sell-through. Propose the discount depth within margin guardrails and a vendor-funding ask. Draft co-op and funding emails and the event calendar, and project event P&L.

## 5. Baseline minutes for the CategoryOS impact meter (research estimates, not measured)

### A. Per new-vendor onboarding, about 12 SKUs

| Step | Manual baseline (min) |
|---|---|
| Document screening (GST, licences, brand authorisation, FSSAI/etc.) | 45 |
| Market research go/no-go (20 min x 12 SKUs) | 240 |
| Shortlist and rationale | 30 |
| Negotiation prep / gap analysis | 60 |
| Negotiation calls (2 x 45) + notes | 110 |
| Conditional-offer evaluation | 30 |
| Catalog listing from messy sheet (25 min x 12) | 300 |
| Images / content sourcing and QC (10 min x 12) | 120 |
| Compliance checks (5 min x 12) | 60 |
| Marketing / JBP draft | 60 |
| First PO draft | 30 |
| **Total** | **1,085 (about 18 h)** |

With human review, expect a 40-55% saving: about 8-11 h saved per vendor. Suggested per-step savings: research 60%, catalog 65%, compliance 50%, negotiation prep 50%, calls 20% (the copilot helps the live call but does not shorten it), drafts 60%.

### B. Recurring tasks (for future modules)

| Task | Baseline | Unit |
|---|---|---|
| Price-increase request evaluation | 90 min | per request (CM 60 + CE 30) |
| Weekly business review / MIS pack | 240 min | per category per week |
| Vendor scorecard | 75 min | per vendor per month |
| PO chase | 15 min | per late PO |
| Fill-rate reconciliation | 45 min | per vendor per week |
| Existing catalog fix | 12 min | per SKU |
| Promotion / event plan | 480 min | per event |
| QBR / JBP deck | 600 min | per top vendor per quarter |
| Competitor price sweep | 30 min | per day per category |
| Inventory ageing review and liquidation plan | 180 min | per category per week |

## Bibliography
- Amazon India category manager postings: https://amazon.jobs/jobs/2866179 ; https://amazon.jobs/en/jobs/2923633/category-manager-gl-ce-audio ; https://amazon.dejobs.org/bengaluru-ind/senior-category-manager-apparel/25624278C77648A19D6357974D0B7E80/job
- Amazon Private Brands category manager (foundit): https://www.foundit.in/job/category-manager-private-brands-private-brands-amazon-music-india-60959161
- Vodafone e-commerce category associate manager: https://opportunities.vodafone.com/job/Giza-E-Commerce-Category-Associate-Manager/1395138033/
- Toolsvilla e-commerce category manager: https://jobs.techstars.com/companies/toolsvilla/jobs/64259702-e-commerce-category-manager
- Retail buying and the McKinsey "busy work" claim (secondhand): https://fashionunited.uk/news/retail/the-art-of-retail-buying-in-the-digital-age/2022091565160
- Symphony GOLD category management survey (2017): https://www.retaildive.com/press-release/20170206-symphony-gold-category-management-survey-finds-retailers-and-manufacturers/
- Bamboo Rose sourcing-tools survey: https://retaildive.com/news/survey-retailers-using-outdated-tools-to-manage-sourcing/447891
- SymphonyAI category manager copilot (vendor claims): https://symphonyai.com/resources/blog/retail-cpg/ai-is-making-category-management-fun-again
- Category management 8-step process: https://umbrex.com/resources/frameworks/marketing-frameworks/category-management-8-step-process/ ; https://nielseniq.com/global/en/client-learning/practical-category-management
- Flipkart cataloging QC (Fynd/Jio docs): https://documentation.fynd.com/commerce/docs/openapi/listings-management/flipkart/cataloging-flipkart
- Nykaa cataloging and onboarding: https://documentation.fynd.com/commerce/docs/openapi/listings-management/nykaa/cataloging-nykaa.md ; https://platform.fynd.com/help/docs/openapi/new-seller-onboarding/nykaa ; https://unicommerce.com/blog/sell-on-nykaa/
- Brynjolfsson, Li, Raymond, Generative AI at Work: https://nber.org/papers/w31161 ; https://arxiv.org/abs/2304.11771
