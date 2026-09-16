-- =====================================================================
-- schema.sql — ProductPulse analytical schema (DuckDB)
-- =====================================================================
-- This file documents the target schema built by src/data_cleaning.py.
-- The pipeline uses CREATE TABLE ... AS SELECT (CTAS) against a 110M-row
-- source for performance; this file is the readable contract for what
-- each table looks like and why it exists. Column comments are applied
-- for real via DuckDB's COMMENT ON syntax inside the pipeline.
--
-- Layer 1: fact_events            — cleaned, deduplicated raw events
-- Layer 2: dim_product/dim_category — resolved product & category dims
-- Layer 3: session_summary        — one row per session (macro funnel)
-- Layer 3: session_product_funnel — one row per (session, product)
--                                    (product-level funnel — the core
--                                     table behind conversion metrics)
-- Layer 4: agg_*                  — precomputed rollups for the dashboard
-- =====================================================================

-- ---------------------------------------------------------------------
-- LAYER 1: fact_events
-- ---------------------------------------------------------------------
-- Grain: one row per (deduplicated) user event.
-- Built from raw CSV with: exact-duplicate removal, derived date/hour/
-- price-band/taxonomy columns. Nothing else is altered — nulls in
-- category_code/brand are preserved as NULL, not imputed.
CREATE TABLE IF NOT EXISTS fact_events (
    event_time      TIMESTAMP,   -- UTC event timestamp
    event_date      DATE,        -- derived: calendar date
    event_hour      TINYINT,     -- derived: hour of day 0-23
    event_type      VARCHAR,     -- 'view' | 'cart' | 'purchase'
    product_id      BIGINT,
    category_id     BIGINT,
    category_code   VARCHAR,     -- nullable (32.2% null in raw data)
    category_l1     VARCHAR,     -- derived: first taxonomy segment
    category_l2     VARCHAR,     -- derived: second taxonomy segment
    brand           VARCHAR,     -- nullable (13.9% null in raw data)
    price           DOUBLE,
    price_band      VARCHAR,     -- derived bucket, see price bands below
    user_id         BIGINT,
    user_session    VARCHAR
);

-- Price bands (applied consistently everywhere price_band is used):
--   'Free ($0)'      price = 0
--   '$0-25'          0 < price <= 25
--   '$25-50'         25 < price <= 50
--   '$50-100'        50 < price <= 100
--   '$100-250'       100 < price <= 250
--   '$250-500'       250 < price <= 500
--   '$500-1000'      500 < price <= 1000
--   '$1000+'         price > 1000

-- ---------------------------------------------------------------------
-- LAYER 2: dim_product / dim_category
-- ---------------------------------------------------------------------
-- Grain: one row per product_id / one row per category_code.
-- category_code and brand are resolved to a single canonical value per
-- product using the MODE (most frequently observed value across that
-- product's events), since a small number of products show more than
-- one value over the 2-month window (see DATA_QUALITY_REPORT.md #9).
CREATE TABLE IF NOT EXISTS dim_product (
    product_id      BIGINT PRIMARY KEY,
    category_id     BIGINT,
    category_code   VARCHAR,
    category_l1     VARCHAR,
    category_l2     VARCHAR,
    brand           VARCHAR,
    is_categorized  BOOLEAN,
    is_branded      BOOLEAN,
    avg_price       DOUBLE,
    min_price       DOUBLE,
    max_price       DOUBLE,
    first_seen_date DATE,
    last_seen_date  DATE
);

CREATE TABLE IF NOT EXISTS dim_category (
    category_code   VARCHAR PRIMARY KEY,
    category_l1     VARCHAR,
    category_l2     VARCHAR,
    n_products      BIGINT,
    n_brands        BIGINT
);

-- ---------------------------------------------------------------------
-- LAYER 3: session_summary  (macro / session-level funnel)
-- ---------------------------------------------------------------------
-- Grain: one row per user_session.
-- Used for the "top-of-funnel" macro view: of all sessions with >=1
-- view, what share ever cart anything, and of those, what share ever
-- purchase anything (not necessarily the same product).
CREATE TABLE IF NOT EXISTS session_summary (
    user_session       VARCHAR PRIMARY KEY,
    user_id            BIGINT,
    n_distinct_users   INTEGER,   -- should be 1; >1 flags a corrupt session id
    is_valid_session   BOOLEAN,   -- FALSE for the 940 multi-user sessions
    session_start      TIMESTAMP,
    session_end        TIMESTAMP,
    session_duration_s DOUBLE,
    n_events           BIGINT,
    n_views            BIGINT,
    n_carts            BIGINT,
    n_purchases        BIGINT,
    has_view           BOOLEAN,
    has_cart           BOOLEAN,
    has_purchase       BOOLEAN,
    revenue            DOUBLE,    -- sum(price) of purchase events in session
    session_date       DATE
);

-- ---------------------------------------------------------------------
-- LAYER 3: session_product_funnel  (product-level funnel — CORE TABLE)
-- ---------------------------------------------------------------------
-- Grain: one row per (user_session, product_id) that had >=1 event.
-- This is the methodologically correct denominator for product/category
-- /brand/price conversion: "did the session view THIS product, and did
-- IT SUBSEQUENTLY get carted / purchased" — not just co-occurrence of
-- unrelated events in the same session.
CREATE TABLE IF NOT EXISTS session_product_funnel (
    user_session        VARCHAR,
    product_id          BIGINT,
    user_id             BIGINT,
    category_id         BIGINT,
    category_code       VARCHAR,
    brand                VARCHAR,
    price                DOUBLE,   -- first observed price for this product in this session
    price_band           VARCHAR,
    first_view_time      TIMESTAMP,
    first_cart_time      TIMESTAMP,
    first_purchase_time  TIMESTAMP,
    viewed               BOOLEAN,
    carted               BOOLEAN,
    purchased            BOOLEAN,
    view_to_cart         BOOLEAN,  -- carted AND first_cart_time >= first_view_time
    cart_to_purchase     BOOLEAN,  -- purchased AND first_purchase_time >= first_cart_time
    view_to_purchase     BOOLEAN,  -- purchased AND first_purchase_time >= first_view_time
    purchased_without_cart BOOLEAN, -- purchased with no prior cart event for this product
    event_date           DATE      -- date of first_view_time (or first event) for time trends
);

-- ---------------------------------------------------------------------
-- LAYER 4: agg_* — precomputed rollups (dashboard performance layer)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agg_daily_funnel (
    event_date      DATE PRIMARY KEY,
    day_of_week     VARCHAR,
    n_views         BIGINT,
    n_carts         BIGINT,
    n_purchases     BIGINT,
    n_sessions      BIGINT,
    n_users         BIGINT,
    revenue         DOUBLE
);

CREATE TABLE IF NOT EXISTS agg_product_metrics (
    product_id              BIGINT PRIMARY KEY,
    category_code           VARCHAR,
    brand                   VARCHAR,
    avg_price               DOUBLE,
    view_events             BIGINT,
    cart_events             BIGINT,
    purchase_events         BIGINT,
    viewing_sessions        BIGINT,
    carting_sessions        BIGINT,
    purchasing_sessions     BIGINT,
    view_to_cart_sessions   BIGINT,
    cart_to_purchase_sessions BIGINT,
    view_to_purchase_sessions BIGINT,
    view_to_cart_rate       DOUBLE,
    cart_to_purchase_rate   DOUBLE,
    overall_conversion_rate DOUBLE,
    revenue                 DOUBLE
);

CREATE TABLE IF NOT EXISTS agg_category_metrics (
    category_code           VARCHAR PRIMARY KEY,
    n_products               BIGINT,
    view_events              BIGINT,
    cart_events               BIGINT,
    purchase_events           BIGINT,
    viewing_sessions          BIGINT,
    carting_sessions          BIGINT,
    purchasing_sessions       BIGINT,
    view_to_cart_rate         DOUBLE,
    cart_to_purchase_rate     DOUBLE,
    overall_conversion_rate   DOUBLE,
    revenue                   DOUBLE,
    pct_of_total_views        DOUBLE,
    pct_of_total_revenue      DOUBLE
);

CREATE TABLE IF NOT EXISTS agg_brand_metrics (
    brand                    VARCHAR PRIMARY KEY,
    n_products               BIGINT,
    view_events              BIGINT,
    cart_events              BIGINT,
    purchase_events          BIGINT,
    viewing_sessions         BIGINT,
    view_to_cart_rate        DOUBLE,
    cart_to_purchase_rate    DOUBLE,
    overall_conversion_rate  DOUBLE,
    revenue                  DOUBLE
);

CREATE TABLE IF NOT EXISTS agg_price_band_metrics (
    price_band               VARCHAR PRIMARY KEY,
    band_order                INTEGER,
    n_products                BIGINT,
    view_events                BIGINT,
    cart_events                 BIGINT,
    purchase_events              BIGINT,
    viewing_sessions             BIGINT,
    carting_sessions             BIGINT,
    view_to_cart_rate            DOUBLE,
    cart_to_purchase_rate        DOUBLE,
    overall_conversion_rate      DOUBLE,
    cart_abandonment_rate        DOUBLE,
    revenue                      DOUBLE
);

CREATE TABLE IF NOT EXISTS agg_user_metrics (
    user_id              BIGINT PRIMARY KEY,
    first_seen_date      DATE,
    last_seen_date       DATE,
    active_days          BIGINT,
    total_sessions       BIGINT,
    total_events         BIGINT,
    total_views          BIGINT,
    total_carts          BIGINT,
    total_purchases      BIGINT,
    total_revenue        DOUBLE,
    is_purchaser         BOOLEAN,
    is_repeat_purchaser  BOOLEAN,   -- purchased on >=2 distinct calendar days
    activity_segment     VARCHAR    -- 'One-time viewer' | 'Cart, no purchase' | 'One-time buyer' | 'Repeat buyer'
);
