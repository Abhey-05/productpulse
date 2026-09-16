# Data Dictionary — ProductPulse

**Source:** [eCommerce Behavior Data from Multi-Category Store](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store) (Kaggle, public dataset — REES46 Marketing Platform)
**Files used:** `2019-Oct.csv`, `2019-Nov.csv`
**Grain:** one row = one user event (view / cart / purchase) on a product
**Scale (raw, as inspected):** 109,950,743 rows across 61 days (2019-10-01 → 2019-11-30)

Full raw profiling output is in [`docs/data_inspection_report.md`](docs/data_inspection_report.md).

## Raw columns

| Column | Type (as loaded) | Meaning | Example | Used in analysis? |
|---|---|---|---|---|
| `event_time` | TIMESTAMP (UTC) | When the event occurred | `2019-10-01 00:00:00` | Yes — funnel timing, daily/weekly trends, hour-of-day, event ordering (view before cart before purchase) |
| `event_type` | VARCHAR | One of `view`, `cart`, `purchase` | `view` | Yes — the entire funnel is built on this |
| `product_id` | BIGINT | Unique product identifier | `44600062` | Yes — product-level conversion, top products |
| `category_id` | BIGINT | Unique category identifier (finer-grained than `category_code`; 691 distinct values) | `2103807459595387724` | Yes — joined to `category_code` where available |
| `category_code` | VARCHAR, nullable (32.2% null) | Human-readable category taxonomy, dot-delimited (`l1.l2.l3`) | `electronics.smartphone` | Yes, with caveat — only usable where present; category-level analysis is reported as "categorized" vs "uncategorized" traffic, never silently dropped |
| `brand` | VARCHAR, nullable (13.9% null) | Product brand, lowercase | `samsung` | Yes, with caveat — same null-handling approach as category_code |
| `price` | DOUBLE | Price in USD at time of event | `1081.98` | Yes — price-band analysis, revenue. 256,761 rows (0.23%) have `price = 0`, kept as an explicit "Free / $0" band rather than dropped (see DATA_QUALITY_REPORT.md) |
| `user_id` | BIGINT | Unique user/visitor identifier | `541312140` | Yes — user-level aggregation, repeat behavior |
| `user_session` | VARCHAR (UUID) | Session identifier | `72d76fde-...` | Yes — session-level funnel and abandonment analysis. 940 sessions (0.004%) map to more than one `user_id` and are excluded from strict session-level/user-level joins (see quality report) |

## Fields the brief mentions that this dataset does NOT contain

- **`remove_from_cart` event** — this dataset only has `view`, `cart`, `purchase`. There is no explicit "removed from cart" signal. **Cart abandonment is therefore defined as "added to cart but never purchased (within the observed window)"** — it cannot distinguish an intentional removal from a cart item that is simply still pending or was abandoned passively. This is stated explicitly wherever cart abandonment is reported.
- **Order-level fields** (order_id, quantity, discount, shipping, total order value) — not present. "Revenue/GMV" in this project is a **proxy**: `SUM(price)` over `purchase` events, i.e. line-item revenue, not a true order total (no quantity field, so we assume 1 unit per purchase event, which is the standard treatment for this dataset).
- **User demographics / geography / device / channel** — not present. Segmentation is therefore behavioral (activity level, recency, repeat-purchase status) rather than demographic.

## Derived fields (created during cleaning — see `sql/schema.sql`)

| Field | Derived from | Meaning |
|---|---|---|
| `event_date` | `event_time` | Calendar date (UTC) for daily aggregation |
| `event_hour` | `event_time` | Hour of day (0–23) for hour-of-day patterns |
| `category_l1` | `category_code` | First segment of the taxonomy (e.g. `electronics`) |
| `category_l2` | `category_code` | Second segment (e.g. `smartphone`) |
| `price_band` | `price` | Bucketed price range for price-conversion analysis |
| `is_categorized` | `category_code` | Boolean flag — `category_code IS NOT NULL` |
| `is_branded` | `brand` | Boolean flag — `brand IS NOT NULL` |

## Data dictionary for derived analytical tables

See `sql/schema.sql` for full DDL and column comments on:
- `fact_events` — cleaned, deduplicated event fact table
- `dim_product`, `dim_category` — product/category dimensions (canonical brand/category resolved by mode per product)
- `session_summary` — one row per session with funnel flags and duration
- `session_product_funnel` — one row per (session, product) with view/cart/purchase timestamps and derived conversion flags — the core table behind product/category/brand/price conversion metrics
- `agg_*` tables — precomputed daily/product/category/brand/price-band/user rollups used by the dashboard for performance
