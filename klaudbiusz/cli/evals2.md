# Databricks Apps 2.0 — Evaluation Framework (Agentic DevX + DORA)
**Version:** Working Spec v1.0 (Oct 29, 2025)
**Authors:** Evgenii Kniazev, Arseni Kravchenko, Igor Rekun

---

## Executive Summary

**Objective.** Define a clear, reproducible, and minimally biased way to determine whether AI-generated apps for Databricks Apps can reach production with little to no human intervention. Core principle: **if an AI agent cannot autonomously run and deploy what it generated, that artifact is not production-ready**.

**What we built.** A **9-layer validation pipeline** plus two agentic developer-experience metrics—**Runability** and **Deployability**—that test whether a lightweight agent can run, test, and deploy the codebase from generic instructions. These metrics map directly to **DORA** (Deployment Frequency, Lead Time, Change Failure Rate, MTTR) to discuss delivery performance in industry-standard terms.

**What's measured today.**
- **Baseline (Evals 1.0, manual rubric):** 73% viability across ~30 tasks; best-case time-to-deploy **30-60 minutes**.
- **Current (Evals 2.0, 20 simple apps on TS+tRPC template):** **Build/runtime: 20/20**, **Runability: 3.0/5**, **Deployability: 2.5/5**, **Type-safety pass: 1/20**, average **~732 LOC**, dashboard "avg build step" **2.7s**. These are **diagnostic** signals on a deliberately simple set—not production claims.

---

## 1) Business Outcomes

- **Speed:** Objective evaluation in minutes, not hours.
- **Scale:** Consistent evaluation across **100–300+** generated apps.
- **Quality:** Prioritizes **deployability evidence** over subjective style.
- **Cost:** Automates checks and rollbacks to reduce manual review.

---

## 2) Scope & Definitions

- **Unit of evaluation:** one **prompt→app** attempt on the **reference stack** (initially TypeScript+tRPC+custom Databricks inetgration + codegen MCP).
- **Viability (Evals 1.0 baseline):** human-audited "complete & ready to deploy"; used only as a baseline for improvement.
- **Runability (0–5):** ability of a sample AI agent to run the app using only README + `.env` file.
- **Deployability (0–5):** ability for a sample AI agent to build, pass healthcheck, and smoke-verify first response.

**Out-of-scope (for now):** complex multi-service topologies, bespoke UX polish, and long-running workflows; staged later via **Advanced/Hard** cohorts.

---

## 3) Evaluation Pipeline (9 Layers)

| # | Check | What it validates | Result |
|---|---|---|---|
| 1 | Build Success | Project compiles | Binary |
| 2 | Runtime Success | App starts & serves content | Binary |
| 3 | Type Safety | No type errors | Binary |
| 4 | Tests Pass | Unit/integration pass | Binary |
| 5 | DB Connectivity | Databricks connection works | Binary |
| 6 | Data Operations | CRUD operations correct | Binary |
| 7 | UI Validation | Frontend renders w/o errors | Binary |
| 8 | Runability (agentic) | Can sample AI agent run generated app locally? | 0–5 |
| 9 | Deployability (agentic) |Can sample AI agent deploy generated app? | 0–5 |

**Additional sub-checks:**
- **SQL validation:** TBD (start with lint, `EXPLAIN`, forbid destructive ops, column existence, result-shape sanity)
- **UI validation:** TBD (start with route discovery, basic screenshots, DOM error scan, simple accessibility smoke)

---

## 4) Agentic DevX Rubrics

**Runability (0–5):**
- 0: install/start fails; missing scripts/env
- 1: installs; start fails not solvable via README
- 2: starts with manual tweaks (undocumented env)
- 3: starts cleanly with `.env.example` + documented steps
- 4: starts **and** seeds/migrations via scripts
- 5: + healthcheck endpoint + smoke test succeeds

**Deployability (0–5):**
- 0: no/broken Dockerfile
- 1: image builds; container fails to start
- 2: starts; healthcheck fails or ports undefined
- 3: healthcheck OK; smoke 2xx
- 4: + logs/metrics hooks present
- 5: + **automated rollback** to prior known-good tag

---

## 5) Mapping to DORA (with calculation rules)

- **Deployment Frequency:** count of **successful Layer-9** events per app per day (or per 100 prompts).
- **Lead Time:** median time from **first model call** to **first successful Layer-9** (or Layer-7 "pre-deploy" when L9 gated).
- **Change Failure Rate:** fraction of L9 deployments that **fail healthcheck or are rolled back** within **T=30 min**.
- **MTTR:** median time from failure detection to **restore** (prior healthy image running).

Agentic DevX scores directly enable DORA by raising probability of L9 success and reducing fix time.

---

## 6) Results (Transparent & Bounded)

**Baseline (Evals 1.0, manual):** **73% viability**, deploy time **30-60 minutes** manual time-intence evaluation.

**Current (Evals 2.0, 20 simple apps, TS+tRPC template):**
- **Build success:** 20/20
- **Runtime success:** 20/20
- **Type-safety:** **1/20**
- **Runability:** **3.0/5**
- **Deployability:** **2.5/5**
- **Avg LOC:** ~**732**
- **Dashboard "avg build step":** **2.7s**
- **Total eval cost:** ~$14.81 (~$0.74/app)
- **Avg turns:** 93 (~173 tokens/turn)

Treat these results as **diagnostic**, not production-ready.


---

## 7) Readiness Levels & Go/No-Go Gates

| Level | When to use | Gate (must satisfy) | What's allowed |
|---|---|---|---|
| Research | model iteration & stack changes | L1–L2 pass; L8 ≥ 2 | Local demos only |
| Internal Preview | internal usage & feedback | L1–L7 pass; **L8 ≥ 3**, **L9 ≥ 3** | Staged internal deploy |
| Production Candidate | external consideration | L1–L7 pass; **L8 ≥ 4**, **L9 ≥ 4**; **type-safety pass**; DORA guardrails: **Lead Time P50 ≤ 10 min**, **CFR ≤ 15%**, **MTTR ≤ 15 min** over last 50 runs | On-demand deploy with rollback |

---

## 8) Risks & Mitigations

- **Narrow eval set.** Expand from 20 simple prompts → **100+** across **Basic / Advanced / Hard** tiers to improve generalizability.
- **Stack specificity.** Start with TS+tRPC; add A/B with **Databricks Apps SDK**, plus one mainstream Python/TS variant.
- **Test brittleness.** Prefer unit/integration; keep UI smoke minimal and actionable.
- **Reproducibility.** Ship a full **artifact pack** (prompts, seeds, Dockerfiles, CI, assessor rubric, one-command runner).

---

## 9) Roadmap (4–6 weeks)

1. **Artifacts & Telemetry:** Publish **repro pack**; instrument DORA telemetry in CI (deploy logs, healthchecks, rollbacks).
2. **Prompt Cohorts:** Grow to **100+ prompts** with tiered difficulty; keep current 20 as a regression set.
3. **Agentic DevX uplift:** Enforce `.env.example` + **exact** run/deploy steps; add observability as a Deployability sub-criterion (no new layer).
4. **Databricks Apps SDK A/B:** Measure Runability/Deployability delta vs baseline scaffolds.
5. **Benchmarks:** Add at least one external baseline (agent without environment scaffolding) + report **token counts**.

---

## Appendix A — Current "Simple 20" Prompt Set
| Prompt ID                    | Description                                                                                                                                                                                        |
|------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| churn-risk-dashboard         | Build a churn risk dashboard showing customers with less than 30 day login activity, declining usage trends, and support ticket volume. Calculate a risk score.                                    |
| revenue-by-channel           | Show daily revenue by channel (store/web/catalog) for the last 90 days with week-over-week growth rates and contribution percentages.                                                              |
| customer-rfm-segments        | Create customer segments using RFM analysis (recency, frequency, monetary). Show 4-5 clusters with average spend, purchase frequency, and last order date.                                         |
| taxi-trip-metrics            | Calculate taxi trip metrics: average fare by distance bracket and time of day. Show daily trip volume and revenue trends.                                                                         |
| slow-moving-inventory        | Identify slow-moving inventory: products with more than 90 days in stock, low turnover ratio, and current warehouse capacity by location.                                                          |
| customer-360-view            | Create a 360-degree customer view: lifetime orders, total spent, average order value, preferred categories, and payment methods used.                                                              |
| product-pair-analysis        | Show top 10 product pairs frequently purchased together with co-occurrence rates. Calculate potential bundle revenue opportunity.                                                                  |
| revenue-forecast-quarterly   | Show revenue trends for next quarter based on historical growth rates. Display monthly comparisons and seasonal patterns.                                                                          |
| data-quality-metrics         | Monitor data quality metrics: track completeness, outliers, and value distribution changes for key fields over time.                                                                               |
| channel-conversion-comparison| Compare conversion rates and average order value across store/web/catalog channels. Break down by customer segment.                                                                                |
| customer-churn-analysis      | Show customer churn analysis: identify customers who stopped purchasing in last 90 days, segment by last order value and ticket history.                                                           |
| pricing-impact-analysis      | Analyze pricing impact: compare revenue at different price points by category. Show price recommendations based on historical data.                                                                |
| supplier-scorecard           | Build supplier scorecard: on-time delivery percentage, defect rate, average lead time, and fill rate. Rank top 10 suppliers.                                                                      |
| sales-density-heatmap        | Map sales density by zip code with heatmap visualization. Show top 20 zips by revenue and compare to population density.                                                                          |
| cac-by-channel               | Calculate CAC by marketing channel (paid search, social, email, organic). Show CAC to LTV ratio and payback period in months.                                                                     |
| subscription-tier-optimization| Identify subscription tier optimization opportunities: show high-usage users near tier limits and low-usage users in premium tiers.                                                               |
| product-profitability        | Show product profitability: revenue minus returns percentage minus discount cost. Rank bottom 20 products by net margin.                                                                           |
| warehouse-efficiency         | Build warehouse efficiency dashboard: orders per hour, fulfillment SLA (percentage shipped within 24 hours), and capacity utilization by facility.                                                 |
| customer-ltv-cohorts         | Calculate customer LTV by acquisition cohort: average revenue per customer at 12, 24, 36 months. Show retention curves.                                                                           |
| promotion-roi-analysis       | Measure promotion ROI: incremental revenue during promo vs cost, with 7-day post-promotion lift. Flag underperforming promotions.                                                                 |

---

## Appendix B — Minimal Runbook (Repo Hygiene)

- `README` with exact **local run** & **docker run** commands
- `.env.example` listing **all** required keys
- **Healthcheck** endpoint + one-step smoke test
- Logs/metrics hooks (observability stubs)
- Seed/migration scripts when data is needed

---

## Appendix C — Reproducibility & Audit Checklist

- Cohort manifest (prompt IDs, seeds)
- Token accounting (input/output, calls/app)
- Exact repo commit + Dockerfiles + CI recipes
- One-command runner to reproduce summary tables
- Assessor rubric with pass/fail thresholds per gate

---

## TL;DR (one page)

- **What's new:** Ship/no-ship via **objective gates** + **DORA telemetry**, not subjective style.
- **Where we are:** Baseline **73% viability** (manual); current **20-app** sample shows **3.0/5 Runability**, **2.5/5 Deployability**, perfect build/runtime on a simple stack.
- **What's next:** Expand to **100+ prompts**, ship **artifact pack**, wire **DORA in CI**, and A/B the **Databricks Apps SDK** to raise Runability/Deployability.