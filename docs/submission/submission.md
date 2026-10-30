# CategoryOS: submission text

Paste-ready text for the hackathon form. Every number below is in the repo (README, `eval/results/`, `GET /api/impact`) or labelled as modelled or anecdotal.

## Tagline (one line)

An AI category manager that onboards vendors, negotiates and runs the category, and never shows you a number it can't prove.

## The short pitch (about 60 words)

Category teams are among the largest in e-commerce, and most of their week is manual work on messy vendor data. CategoryOS reads the sheets, scans and calls with six Meta models, decides with Python, and re-checks every number against its source before a person approves. On our own team, onboarding a vendor takes about a week; with CategoryOS it took two hours.

## What makes it different: the verifier

Most AI assistants are confidently wrong some of the time. In a category team, one wrong number is a bad deal, an expired licence on a live listing, or a mispriced SKU. So in CategoryOS:

- **Models read and explain; Python decides every number.** Margins, probabilities, totals and verdicts are deterministic.
- **Every number a model states is a claim with a source cell**, and the verifier re-computes it. A wrong reading is sent back for correction; a claim that never gets right is removed before anyone sees it.
- **It caught real disagreements in the live runs, unscripted.** On 27 Oct 2026, the model read vendor V002's GST certificate as valid from 01 APR 2023 on the full page and 01 APR 2025 on the cropped re-read. The verifier refused to pick one and flagged it for a person.
- **Measured:** 198 of 200 planted errors caught (digit swaps, decimal shifts, kg vs g, rupees vs paise, wrong row or column), with 0 false alarms on 200 correct values. The two misses were below the playbook's tolerance by design.
- **Prompt injection hidden in vendor text:** the model detector caught 30 of 30 variants, against 9 of 30 for a regex.
- **A harder test, run live and used to improve the verifier:** 94 messy figures with ground truth (swapped columns, `Rs.399/-`, comma typos, paise, Hinglish emails, injection lines). The first live run found a blind spot: both Spark models read 11 rows with swapped cost and MRP columns wrong, and the verifier passed them. We added a row check (cost must be below MRP); in the next run the verifier caught 14 of muse-spark-1.3's slips and it fixed all 14 on one retry (81% to 95.7%). The errors still passing were email answers, and they exposed ambiguous tasks in our own test set; we fixed the set and added three email checks. On the corrected set all three models scored 100%, with muse-spark-1.3 at a quarter of muse-wonder-1.0's cost.

## What it does

- **Onboard a vendor:** screen documents and claims, decide which SKUs to take at what terms, negotiate, build the catalog, plan the launch and raise the first PO.
- **Negotiate live:** during a vendor call it transcribes, fills a gap table against your targets and prices conditional offers. "15% margin plus 20% marketing support if you sell 2,000 units in 90 days" sounds like 35%; a demand simulation shows the chance of hitting 2,000 is under 0.1%, so it is worth 15%, and it suggests the next line to say.
- **Read the paperwork:** Muse Spark reads licence scans, labels and price lists; SAM 3.1 cuts out the label panel so it can be read again up close. It caught an expiring licence, a 30% vs 32% protein claim and a swapped-digit price.
- **Run the category every week:** vendor review, price-increase requests with a counter-offer, late PO chasers, catalog fixes, promotions, competitor price watch and inventory health.
- **Rules in plain English, with governance:** write "raise the target margin on treats by 2 points"; Muse Spark turns it into a change to the structured playbook, code validates it, and team roles decide who can apply it. Over-limit changes wait for the head of category, and every attempt, refused ones included, is logged with undo.

## How we used Meta's models

| Model | Job in CategoryOS |
|---|---|
| muse-spark-1.3 | Reasoning, tool calling and structured extraction for every agent; vision on vendor scans; plain-English rules to structured settings |
| sam-3.1 | Cuts the nutrition and claims panel out of a label so it can be re-read up close; packshot cutouts |
| muse-image-1.0 | Packshots, lifestyle and campaign images |
| muse-voice-transcribe-1.0 | Transcribes the live vendor call for the negotiation copilot |
| Muse Spark Open (Baseten) | Open-weight SKU classification, benchmarked head to head against Spark 1.3 |
| muse-wonder-1.0 | Steps in when a claim is still rejected after the normal retries; also benchmarked on the hard test |

All four demo vendor runs were recorded live against the Meta API, and the public site can make real model calls within a capped budget.

## Impact

- **Our team:** onboarding a vendor takes about a week end to end today, fitted around other work. With CategoryOS it took two hours. This is our own team's experience, not a controlled measurement.
- **Modelled across the job:** about a third of a category team's week (34.6%), about 202 hours a month for a team of three. Modelled from research estimates across 17 activities, not measured; see `docs/research/category-manager-workload.md`.
- **Path to a real company:** `docs/pitch/enterprise-integration.md` shows how a company connects its mailboxes, scans, sheets, ERP and catalog, with each source marked as working now, needing an adapter, or roadmap.

## Challenges

- Model reasoning tokens count against the output limit, so structured calls needed bounded retries with larger budgets.
- SAM's masks come back box-relative and capped at 1,024 px; placing them correctly took a parser and origin maths.
- Being honest about what is live: every screen says whether a result is a replay of a live run, and modelled numbers are labelled.

## What's next

A read-only pilot on one category with a partner team, then mailbox and ERP connectors, then write-back with approvals and company login (SSO).

## Links

- Live app: https://categoryos.vercel.app
- Code: https://github.com/Nandish3010/categoryos
- Integration plan: https://github.com/Nandish3010/categoryos/blob/main/docs/pitch/enterprise-integration.md

All data in the demo is synthetic.
