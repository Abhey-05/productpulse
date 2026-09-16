# ProductPulse — E-commerce Conversion & Product Analytics

A SQL-first product analytics project built on a real, public 110-million-event
e-commerce clickstream dataset: funnel analysis, cart abandonment, product/category/
brand/price conversion, user segmentation, and a Streamlit + Plotly dashboard with
a lightweight rule-based "Ask ProductPulse" analyst on top.

**This is a product analytics project, not a machine-learning project.** There is
no predictive model here — the value is in correctly defined metrics, advanced SQL,
and product-relevant interpretation of real behavioral data.

---

## 1. Project Overview

ProductPulse answers the questions a product/growth team at a company like
Zomato, Blinkit, Swiggy, or InMobi would ask of raw event logs: where do users
drop out of the purchase journey, which products/categories draw traffic but
don't convert it, where is cart abandonment concentrated, and what should the
product team investigate next.

## 2. Business Problem

> An e-commerce product team has large volumes of user-event data but needs to
> understand where users drop out of the purchase journey, which products/
> categories are underperforming, and where potential revenue/conversion
> opportunities exist.

The project answers, with real numbers, not illustrative ones:
1. Where are users dropping off in the funnel?
2. Which products/categories get high traffic but convert poorly?
3. Where is cart abandonment highest?
4. How does price relate to conversion?
5. Which brands/categories perform strongly or weakly?
6. How does behavior change over time (daily/weekly/hour-of-day)?
7. What behavioral segments exist among users?
8. Which areas represent the biggest product opportunities?
9. What should a product team investigate or change next?

## 3. Dataset

**[eCommerce Behavior Data from Multi-Category Store](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store)**
— a public Kaggle dataset (REES46 Marketing Platform), **not proprietary company
data**. Files used: `2019-Oct.csv`, `2019-Nov.csv`.

| | |
|---|---|
| Raw rows | 109,950,743 |
| Date range | 2019-10-01 → 2019-11-30 (61 days) |
| Distinct users | 5,316,649 |
| Distinct sessions | 23,016,650 |
| Distinct products | 206,876 |
| Distinct categories (named) | 129 |
| Distinct brands | 4,303 |
| Event types | `view` (94.9%), `cart` (3.6%), `purchase` (1.5%) |

Full profiling output: [`docs/data_inspection_report.md`](docs/data_inspection_report.md).
Cleaning decisions and their rationale: [`docs/DATA_QUALITY_REPORT.md`](docs/DATA_QUALITY_REPORT.md).
Column-level documentation: [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).

**Important scope note:** this dataset has no `remove_from_cart` event (only
`view`/`cart`/`purchase`), no order-level fields (quantity/discount/shipping),
and no demographic/geographic/device data. Every metric below is defined
strictly within what these three event types support — see §7 and
`DATA_DICTIONARY.md` for exactly what is and isn't derivable.

## 4. Why This Problem Matters

Conversion-funnel and cart-abandonment analysis is the daily bread-and-butter
of product analyst / product manager roles at consumer marketplaces and
delivery platforms: revenue leakage almost always concentrates in a small
number of high-traffic, low-converting surfaces, and finding those surfaces
with rigorous, correctly-denominatored SQL (not naive event-count ratios) is
exactly what this project demonstrates.

## 5. Data Architecture

```
Raw CSV (2 files, ~14GB, 109.95M rows)
   │
   ▼  src/data_cleaning.py  (DuckDB CTAS, month-chunked for memory safety)
Cleaned fact table (fact_events) + dimensions (dim_product, dim_category)
   │
   ▼
Session-level tables (session_summary, session_product_funnel)
   │
   ▼
Precomputed aggregate tables (agg_daily_funnel, agg_product_metrics,
agg_category_metrics, agg_brand_metrics, agg_price_band_metrics, agg_user_metrics)
   │
   ▼  src/analytics.py  (single source of truth per metric)
   │
   ├──▶ dashboard/app.py  (Streamlit + Plotly, 7 pages)
   └──▶ src/ai_analyst.py  ("Ask ProductPulse" rule-based analyst)
```

**Why DuckDB, not PostgreSQL:** embedded, zero-config, and handles the ~14GB
raw CSV via out-of-core execution without needing a running server — while
still being full standard SQL (CTEs, window functions, `FILTER`, `QUALIFY`).
The tradeoff documented candidly in §16 Limitations: this machine has a small
free-disk/RAM budget, which shaped the pipeline's month-chunked, resumable,
disk-guarded design (see `src/data_cleaning.py`).

## 6. Database Schema

See [`sql/schema.sql`](sql/schema.sql) for full DDL and comments. Summary:

| Table | Grain | Rows (approx.) | Purpose |
|---|---|---|---|
| `fact_events` | 1 event | ~109.8M | Cleaned, deduplicated source of truth |
| `dim_product` | 1 product | 206,876 | Canonical category/brand per product |
| `dim_category` | 1 category | 129 | Category rollup |
| `session_summary` | 1 session | ~23.0M | Macro (session-level) funnel |
| `session_product_funnel` | 1 (session, product) | tens of millions | **Core table** — product-level funnel |
| `agg_daily_funnel` | 1 day | 61 | Daily/weekly trend |
| `agg_product_metrics` | 1 product | 206,876 | Product conversion & revenue |
| `agg_category_metrics` | 1 category | 129 | Category conversion & revenue |
| `agg_brand_metrics` | 1 brand | 4,303 | Brand conversion & revenue |
| `agg_price_band_metrics` | 1 price band | 8 | Price-band conversion & abandonment |
| `agg_user_metrics` | 1 user | 5,316,649 | User activity & behavioral segment |

## 7. Metric Definitions

All conversion rates are computed at the **session-product grain**
(`session_product_funnel`), not by dividing raw event counts — a session
viewing the same product 5 times must not inflate the denominator.

- **View-to-cart rate** = sessions that viewed product P and *subsequently*
  (by timestamp) added P to cart ÷ sessions that viewed P.
- **Cart-to-purchase rate** = sessions that carted P and subsequently
  purchased P ÷ sessions that carted P.
- **Overall conversion rate** = sessions that viewed P and subsequently
  purchased P ÷ sessions that viewed P.
- **Cart abandonment rate** = 1 − cart-to-purchase rate. *(No `remove_from_cart`
  event exists in this dataset — abandonment means "carted, never purchased
  in the observed window," not a confirmed explicit removal.)*
- **Revenue (proxy)** = `SUM(price)` over `purchase` events. There is no
  quantity field, so this is a line-item revenue proxy, not a true order total.
- **Session-level macro funnel** (Executive Overview page) = same logic but at
  the whole-session grain (did the session view *anything*, cart *anything*,
  purchase *anything*) — a looser, top-of-funnel view distinct from the
  stricter product-level funnel above.
- **New vs. returning user** = "new" only *within the observed 61-day window*
  (first-ever event in the dataset falls in that week); cannot detect activity
  before Oct 1, 2019.
- **Repeat purchaser** = purchased on ≥2 distinct calendar days.

## 8. SQL Analyses

39+ queries across 7 files in [`sql/`](sql/), using CTEs, `CASE WHEN`, window
functions (`LAG`/`LEAD`, `ROW_NUMBER`, `RANK`/`DENSE_RANK`, `NTILE`,
`PERCENT_RANK`), rolling-window aggregates, `FILTER`/conditional aggregation,
and `QUALIFY`:

| File | Covers |
|---|---|
| `funnel_analysis.sql` | Macro & product-level funnel, drop-off, cart abandonment (overall/category/price) |
| `product_analysis.sql` | Top products, high-traffic/low-conversion, cart-heavy/purchase-light, traffic×conversion quadrants, revenue concentration |
| `category_analysis.sql` | Category funnel & revenue contribution, brand performance, engagement depth |
| `price_analysis.sql` | Price-band conversion, traffic vs. revenue share by price, price-decile check |
| `segmentation.sql` | Activity segments, repeat purchase, new vs. returning, engagement deciles, RFM |
| `time_analysis.sql` | Daily trend + 7-day rolling avg, week-over-week, hour-of-day, day-of-week, month-over-month category movers |
| `advanced_analysis.sql` | Weekly acquisition cohorts, funnel-stage weakness ranking, session-depth vs. conversion, product lifecycle |

## 9. Dashboard

Streamlit + Plotly, 7 sidebar pages: Executive Overview, Funnel Analysis
(filterable), Product & Category Performance, User Behavior, Price &
Conversion, Insights & Recommendations, and Ask ProductPulse. Run locally per
§15 — screenshots aren't embedded here since this is a local project, not a
hosted app.

## 10. Key Findings

*(Filled in from the live database — see `docs/pipeline_run_log.md` for the
build log and re-run `python src/analytics.py` to reproduce every number
below directly against the database.)*

- Overall session-level purchase conversion: **4.07%** (view → cart 10.04%, cart → purchase 40.59%)
- Cart abandonment rate: **62.30%** (carted but never purchased)
- Highest-revenue category: **`electronics.smartphone`** ($334.9M, ~66% of total revenue proxy)
- Total revenue proxy across the window: **$505,126,293**
- Revenue concentration: the **"Repeat buyer"** segment is only 3.9% of users (209,188 of 5,316,649) but drives **66.4%** of revenue ($335.2M of $505.1M); "Viewer only" is 77.7% of users and drives $0

## 11. Product Recommendations

See the **Insights & Recommendations** dashboard page for the live,
data-generated version (numbers computed at render time). Structure:
**Finding → Evidence → Hypothesis → Suggested Action → Metric to Monitor.**
No recommendation states a number that isn't a direct SQL query result.

## 12. Experiment Proposals

Each recommendation on the dashboard's Insights page pairs with a proposed
A/B test (hypothesis, control, treatment, primary/secondary metrics,
guardrails). **No experiment has actually been run** — this is hypothesis
generation from observational data, clearly labeled as such throughout.

## 13. Optional AI Analyst — "Ask ProductPulse"

A deliberately simple, **rule-based** (not LLM-generated-SQL) analyst:

```
question → keyword intent match → ONE whitelisted analytics.py function
         → real query result → templated explanation with those exact numbers
         → cautious, labeled interpretation
```

Why rule-based: every possible answer traces to a tested, read-only SQL
query — it cannot fabricate a metric, because the number in the sentence *is*
the number the query returned. See `src/ai_analyst.py` for the full intent
list and `INTERVIEW_PREP.md` for the reasoning defense of this choice.

## 14. Tech Stack

Python · DuckDB · pandas · Streamlit · Plotly. No ML libraries — deliberately.

## 15. How to Run Locally

```bash
cd productpulse
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Place 2019-Oct.csv and 2019-Nov.csv in data/raw/ (or symlink them)

python3 src/inspect_data.py     # Phase 1 — profiling report
python3 src/data_cleaning.py    # Phase 2-4 — build the database (resumable; see script header)
python3 src/analytics.py        # Phase 7 — smoke-test every metric against the live DB

streamlit run dashboard/app.py  # Phase 6 — the dashboard
```

## 16. Limitations

- **Observational data, not an experiment.** Every price/conversion,
  category/conversion, etc. relationship reported is an *association*, never
  a causal claim.
- **No `remove_from_cart` event** — cart abandonment is a proxy ("carted,
  never purchased"), not a confirmed removal signal.
- **No true order totals** — revenue is a line-item `SUM(price)` proxy; no
  quantity, discount, or shipping fields exist.
- **No demographic/geographic/device/channel data** — segmentation is
  purely behavioral.
- **Two-month window only** — "new vs. returning" and cohort retention are
  bounded to what's observable in 61 days; a user active before Oct 1, 2019
  looks "new" here if their first event in-window falls late.
- **Local hardware constraints shaped the pipeline.** This was built on an
  8GB-RAM machine with a small, shared free-disk budget. An early attempt at
  a single-pass `SELECT DISTINCT` / `GROUP BY` over the full 109.8M-row table
  spiked temp-disk usage to a dangerous level; the final pipeline processes
  the two heaviest aggregation stages one month at a time and checkpoints
  between stages specifically to stay safe on constrained hardware — a
  deliberate, documented engineering tradeoff, not a shortcut on data
  fidelity (every real row is still processed; see `src/data_cleaning.py`
  docstring and `docs/pipeline_run_log.md`).

## 17. Future Improvements

- True order-level revenue if a dataset with quantity/order_id becomes available.
- A/B test the highest-confidence recommendation from §12 for real, and
  replace the hypothesis with an actual result.
- Extend the AI Analyst with an LLM purely for the *phrasing* of the final
  explanation (never for query generation), behind the same whitelisted
  function boundary.
- Move from DuckDB to a warehouse (BigQuery/Snowflake) + orchestrated
  pipeline (Airflow/dbt) if this needed to run on a real schedule against
  live production events.

---

## Resume Bullets

*(Numbers are from the actual pipeline run — see `docs/pipeline_run_log.md`.)*

- Analyzed 109.9M+ e-commerce user events using advanced SQL (window
  functions, CTEs, conditional aggregation) to quantify funnel drop-off,
  cart abandonment, and revenue concentration across 206K+ products, 129
  categories, and 4,300+ brands.
- Built a 7-page interactive Streamlit + Plotly product analytics dashboard
  covering funnel, product/category/brand, price-band, and user-segment
  drill-downs, backed by a precomputed DuckDB aggregation layer for
  sub-second response on a 110M-row source dataset.
- Identified high-traffic/low-conversion categories and products from
  session-level funnel data and translated findings into evidence-backed
  product recommendations and proposed A/B test designs.

## Interview Preparation

See [`INTERVIEW_PREP.md`](INTERVIEW_PREP.md).
