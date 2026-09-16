# Data Quality Report

Findings are from `src/inspect_data.py` run against the full raw files (109,950,743 rows). Full raw output: `docs/data_inspection_report.md`.

Every decision below is applied in `src/data_cleaning.py` / `sql/schema.sql` and nothing is silently dropped without being counted here first.

## 1. Exact duplicate rows
- **Found:** 130,739 fully-duplicate rows (0.12% of all rows) — identical `event_time, event_type, product_id, category_id, brand, price, user_id, user_session`.
- **Likely cause:** known upstream logging duplication in this dataset (documented by other users of this Kaggle dataset).
- **Decision:** de-duplicated with `SELECT DISTINCT` when building `fact_events`. Row counts before/after are logged by the pipeline.

## 2. Missing `category_code` (32.2% of rows)
- **Decision:** kept as `NULL`, never imputed or guessed. All category-level analyses report an explicit "uncategorized" bucket where relevant, or filter to `category_code IS NOT NULL` and **state the % of traffic that filter excludes** in the query/page. We do not silently drop a third of the data.

## 3. Missing `brand` (13.9% of rows)
- Same treatment as `category_code`: kept `NULL`, surfaced as "unbranded / unknown" rather than imputed.

## 4. `price = 0` rows (256,761 rows, 0.23%)
- Could be genuine free promotional items or a logging artifact — cannot be determined from the data alone.
- **Decision:** kept in `fact_events` (not deleted). For price-band analysis, `$0` is its own explicit band ("Free / $0") rather than merged into the lowest paid band, so it cannot distort that band's conversion rate.

## 5. No negative prices
- 0 rows with `price < 0`. No action needed.

## 6. Sessions spanning multiple `user_id`s (940 sessions, 0.004% of 23,016,650 sessions)
- Violates the assumption that a `user_session` belongs to exactly one user — almost certainly a client-side session ID collision/reuse edge case, not a real shared session.
- **Decision:** these 940 session IDs are flagged (`is_valid_session = FALSE`) and **excluded** from the macro session-level funnel (`session_summary`, used on the Executive Overview page), since attributing them to one user would be arbitrary. They are *not* separately filtered out of `session_product_funnel` (and therefore the product/category/brand/price-band aggregate tables built on it) — at 940 out of 23,016,650 sessions (0.004%), the effect on any rate computed from those tables is well below rounding precision, so the extra filter was judged not worth the added query complexity. Disclosed here rather than silently accepted.

## 7. No missing values in `event_time`, `event_type`, `product_id`, `category_id`, `user_id`, `user_session`, or `price`
- These fields are 100% populated; no cleaning needed.

## 8. `event_type` values
- Only three values exist: `view`, `cart`, `purchase`. **There is no `remove_from_cart` event in this dataset.** Cart abandonment is therefore defined as "carted but never purchased," not "explicitly removed" — documented in README metric definitions and in DATA_DICTIONARY.md.

## 9. Category/brand consistency per product
- A small number of `product_id`s show more than one distinct `category_code` or `brand` value across events (likely re-categorization or data entry correction over the 2-month window).
- **Decision:** `dim_product` resolves one canonical `category_code`/`brand` per product using the **most frequently observed value** (mode) across that product's events, rather than "first" or "last" seen, which would be arbitrary. The pipeline logs how many products this affects.

## 10. Row-count reconciliation
The pipeline prints before/after row counts at each stage so that any data loss is visible and intentional, per the project rule to never silently discard data. See `docs/pipeline_run_log.md` after running `src/data_cleaning.py`.
