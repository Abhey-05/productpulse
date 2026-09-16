-- =====================================================================
-- funnel_analysis.sql — View → Cart → Purchase funnel & abandonment
-- =====================================================================
-- Metric definitions (see README.md "Metric Definitions" for the
-- canonical wording — repeated here so this file is self-contained):
--
--   view_to_cart_rate      = sessions that viewed a product AND
--                             subsequently carted THAT product
--                             / sessions that viewed that product
--   cart_to_purchase_rate  = sessions that carted a product AND
--                             subsequently purchased THAT product
--                             / sessions that carted that product
--   overall_conversion     = sessions that viewed a product AND
--                             subsequently purchased THAT product
--                             / sessions that viewed that product
--   cart_abandonment_rate  = 1 - cart_to_purchase_rate
--
-- All rates below are computed at the (session, product) grain via
-- session_product_funnel — NOT by naively dividing raw event counts,
-- which would overcount (one session can view a product many times).
-- =====================================================================


-- =====================================================================
-- A1. MACRO FUNNEL — session-level (any product), whole dataset
-- "Of all sessions that viewed anything, how many ever added anything
--  to cart, and how many of those ever purchased anything?"
-- This is the top-of-funnel KPI shown on the Executive Overview page.
-- =====================================================================
WITH funnel AS (
    SELECT
        COUNT(*) FILTER (WHERE has_view) AS viewing_sessions,
        COUNT(*) FILTER (WHERE has_view AND has_cart) AS cart_sessions,
        COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) AS purchase_sessions
    FROM session_summary
    WHERE is_valid_session
)
SELECT
    viewing_sessions,
    cart_sessions,
    purchase_sessions,
    ROUND(100.0 * cart_sessions / NULLIF(viewing_sessions, 0), 2) AS view_to_cart_pct,
    ROUND(100.0 * purchase_sessions / NULLIF(cart_sessions, 0), 2) AS cart_to_purchase_pct,
    ROUND(100.0 * purchase_sessions / NULLIF(viewing_sessions, 0), 2) AS overall_conversion_pct
FROM funnel;


-- =====================================================================
-- A2. PRODUCT-LEVEL FUNNEL — the methodologically stricter version
-- "Of sessions that viewed a SPECIFIC product, how many carted /
--  purchased THAT SAME product afterwards?" Aggregated dataset-wide.
-- =====================================================================
SELECT
    COUNT(*) FILTER (WHERE viewed) AS viewing_session_products,
    COUNT(*) FILTER (WHERE view_to_cart) AS view_to_cart_session_products,
    COUNT(*) FILTER (WHERE cart_to_purchase) AS cart_to_purchase_session_products,
    COUNT(*) FILTER (WHERE view_to_purchase) AS view_to_purchase_session_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_cart) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS view_to_cart_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE cart_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_to_purchase_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS overall_conversion_pct
FROM session_product_funnel;


-- =====================================================================
-- A3. FUNNEL AS STAGES WITH DROP-OFF — classic "funnel chart" shape
-- Uses UNION ALL to lay out each stage as a row, then a window
-- function (LAG) to compute stage-over-stage drop-off.
-- =====================================================================
WITH stages AS (
    SELECT 1 AS stage_order, 'View'     AS stage, COUNT(*) FILTER (WHERE has_view)                       AS sessions FROM session_summary WHERE is_valid_session
    UNION ALL
    SELECT 2, 'Cart',     COUNT(*) FILTER (WHERE has_view AND has_cart)                 FROM session_summary WHERE is_valid_session
    UNION ALL
    SELECT 3, 'Purchase', COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) FROM session_summary WHERE is_valid_session
)
SELECT
    stage_order,
    stage,
    sessions,
    LAG(sessions) OVER (ORDER BY stage_order) AS prev_stage_sessions,
    ROUND(100.0 * sessions / FIRST_VALUE(sessions) OVER (ORDER BY stage_order), 2) AS pct_of_top_of_funnel,
    ROUND(100.0 * sessions / NULLIF(LAG(sessions) OVER (ORDER BY stage_order), 0), 2) AS pct_of_previous_stage,
    ROUND(100.0 - 100.0 * sessions / NULLIF(LAG(sessions) OVER (ORDER BY stage_order), 0), 2) AS drop_off_pct
FROM stages
ORDER BY stage_order;


-- =====================================================================
-- B1. CART ABANDONMENT — overall
-- Cart abandonment = carted a product but never purchased it in that
-- session (no explicit "remove from cart" event exists in this
-- dataset — see DATA_DICTIONARY.md — so this is the best available
-- proxy: "added to cart, never converted").
-- =====================================================================
SELECT
    COUNT(*) FILTER (WHERE carted) AS carting_session_products,
    COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) AS abandoned_session_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase)
        / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_abandonment_pct
FROM session_product_funnel;


-- =====================================================================
-- B2. CART ABANDONMENT BY CATEGORY — where is abandonment worst?
-- Ranked with RANK() so ties are handled explicitly; HAVING filters
-- out categories with too little cart volume to be statistically
-- meaningful (avoids a category with 3 carts looking "100% abandoned").
-- =====================================================================
SELECT
    COALESCE(category_code, 'Uncategorized') AS category_code,
    COUNT(*) FILTER (WHERE carted) AS carting_session_products,
    COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) AS abandoned_session_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase)
        / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_abandonment_pct,
    RANK() OVER (ORDER BY
        100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE carted), 0) DESC
    ) AS abandonment_rank
FROM session_product_funnel
GROUP BY category_code
HAVING COUNT(*) FILTER (WHERE carted) >= 500
ORDER BY cart_abandonment_pct DESC
LIMIT 20;


-- =====================================================================
-- B3. CART ABANDONMENT BY PRICE BAND
-- Answers: "Is abandonment associated with price?" (association only,
-- not causal — see README limitations).
-- =====================================================================
SELECT
    price_band,
    COUNT(*) FILTER (WHERE carted) AS carting_session_products,
    COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) AS abandoned_session_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase)
        / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_abandonment_pct
FROM session_product_funnel
GROUP BY price_band
ORDER BY
    CASE price_band
        WHEN 'Free ($0)' THEN 0 WHEN '$0-25' THEN 1 WHEN '$25-50' THEN 2 WHEN '$50-100' THEN 3
        WHEN '$100-250' THEN 4 WHEN '$250-500' THEN 5 WHEN '$500-1000' THEN 6 ELSE 7
    END;


-- =====================================================================
-- FUNNEL FILTER TEMPLATE — used by the dashboard's Funnel Analysis page
-- to let a user filter by category / brand / price band / date range.
-- (Parameters shown as DuckDB-style named placeholders; the dashboard
-- substitutes real values via src/analytics.py.)
-- =====================================================================
-- SELECT
--     COUNT(*) FILTER (WHERE viewed) AS viewing_session_products,
--     COUNT(*) FILTER (WHERE view_to_cart) AS cart_session_products,
--     COUNT(*) FILTER (WHERE view_to_purchase) AS purchase_session_products
-- FROM session_product_funnel
-- WHERE (:category_code IS NULL OR category_code = :category_code)
--   AND (:brand IS NULL OR brand = :brand)
--   AND (:price_band IS NULL OR price_band = :price_band)
--   AND (:start_date IS NULL OR event_date >= :start_date)
--   AND (:end_date IS NULL OR event_date <= :end_date);
