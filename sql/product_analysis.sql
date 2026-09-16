-- =====================================================================
-- product_analysis.sql — Product-level conversion, traffic & opportunity
-- =====================================================================
-- All conversion rates use session_product_funnel (session-level truth),
-- never raw event-count ratios. A minimum sample size (HAVING) is
-- applied wherever a rate is ranked, to avoid a product with 2 views
-- and 1 purchase looking like a "50% converter."
-- =====================================================================


-- =====================================================================
-- C1. TOP PRODUCTS BY OVERALL CONVERSION (view -> purchase)
-- Minimum 200 viewing sessions required to qualify — "high-confidence
-- high converters."
-- =====================================================================
SELECT
    p.product_id,
    COALESCE(p.category_code, 'Uncategorized') AS category_code,
    COALESCE(p.brand, 'Unknown') AS brand,
    ROUND(m.avg_price, 2) AS avg_price,
    m.viewing_sessions,
    m.purchasing_sessions,
    ROUND(100.0 * m.overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(m.revenue, 2) AS revenue
FROM agg_product_metrics m
JOIN dim_product p USING (product_id)
WHERE m.viewing_sessions >= 200
ORDER BY m.overall_conversion_rate DESC
LIMIT 25;


-- =====================================================================
-- C2. TOP PRODUCTS BY VIEWS (raw traffic/discovery leaders)
-- =====================================================================
SELECT
    product_id,
    COALESCE(category_code, 'Uncategorized') AS category_code,
    COALESCE(brand, 'Unknown') AS brand,
    view_events,
    purchase_events,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(revenue, 2) AS revenue
FROM agg_product_metrics
ORDER BY view_events DESC
LIMIT 25;


-- =====================================================================
-- E1. HIGH-VIEW / LOW-CONVERSION PRODUCTS ("Stuck at discovery")
-- Uses window functions to rank products by view volume (top quartile
-- via NTILE) and then filters to those whose conversion is below the
-- dataset median for that quartile — surfaces "traffic but no sale."
-- =====================================================================
WITH ranked AS (
    SELECT
        product_id, category_code, brand, avg_price,
        viewing_sessions, purchasing_sessions, overall_conversion_rate, revenue,
        NTILE(4) OVER (ORDER BY viewing_sessions) AS view_quartile,
        PERCENT_RANK() OVER (ORDER BY overall_conversion_rate) AS conversion_percentile
    FROM agg_product_metrics
    WHERE viewing_sessions >= 200
)
SELECT
    product_id,
    COALESCE(category_code, 'Uncategorized') AS category_code,
    COALESCE(brand, 'Unknown') AS brand,
    ROUND(avg_price, 2) AS avg_price,
    viewing_sessions,
    purchasing_sessions,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(revenue, 2) AS revenue
FROM ranked
WHERE view_quartile = 4              -- top 25% by traffic
  AND conversion_percentile <= 0.25   -- bottom 25% by conversion
ORDER BY viewing_sessions DESC
LIMIT 30;


-- =====================================================================
-- L1. PRODUCTS FREQUENTLY ADDED TO CART BUT RARELY PURCHASED
-- (Distinct from E1: this looks at cart->purchase specifically, not
-- view->purchase — isolates checkout-stage friction from discovery.)
-- =====================================================================
SELECT
    product_id,
    COALESCE(category_code, 'Uncategorized') AS category_code,
    COALESCE(brand, 'Unknown') AS brand,
    ROUND(avg_price, 2) AS avg_price,
    carting_sessions,
    cart_to_purchase_sessions,
    ROUND(100.0 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    ROUND(100.0 * (1 - cart_to_purchase_rate), 2) AS cart_abandonment_pct
FROM agg_product_metrics
WHERE carting_sessions >= 100
ORDER BY cart_to_purchase_rate ASC, carting_sessions DESC
LIMIT 30;


-- =====================================================================
-- O1. TRAFFIC-VS-CONVERSION MATRIX (data source for the dashboard's
-- bubble scatter: x = views, y = conversion %, size = revenue)
-- Also classifies each product into a quadrant using CASE WHEN against
-- dataset-wide median thresholds, computed with window functions.
-- =====================================================================
WITH thresholds AS (
    SELECT
        MEDIAN(viewing_sessions) AS median_views,
        MEDIAN(overall_conversion_rate) AS median_conversion
    FROM agg_product_metrics
    WHERE viewing_sessions >= 50
)
SELECT
    m.product_id,
    COALESCE(m.category_code, 'Uncategorized') AS category_code,
    COALESCE(m.brand, 'Unknown') AS brand,
    m.viewing_sessions,
    ROUND(100.0 * m.overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(m.revenue, 2) AS revenue,
    CASE
        WHEN m.viewing_sessions >= t.median_views AND m.overall_conversion_rate >= t.median_conversion THEN 'Star (high traffic, high conversion)'
        WHEN m.viewing_sessions >= t.median_views AND m.overall_conversion_rate <  t.median_conversion THEN 'High-traffic underperformer'
        WHEN m.viewing_sessions <  t.median_views AND m.overall_conversion_rate >= t.median_conversion THEN 'Low-traffic high-converter (hidden gem)'
        ELSE 'Low priority'
    END AS quadrant
FROM agg_product_metrics m
CROSS JOIN thresholds t
WHERE m.viewing_sessions >= 50
ORDER BY m.revenue DESC;


-- =====================================================================
-- N1. PRODUCT REVENUE CONCENTRATION (Pareto / 80-20 check)
-- Cumulative revenue share by product rank — classic window-function
-- "running total" pattern.
-- =====================================================================
WITH ranked AS (
    SELECT
        product_id, revenue,
        ROW_NUMBER() OVER (ORDER BY revenue DESC) AS revenue_rank,
        SUM(revenue) OVER () AS total_revenue
    FROM agg_product_metrics
    WHERE revenue > 0
)
SELECT
    revenue_rank,
    product_id,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue_rank) / total_revenue, 2) AS cumulative_revenue_pct
FROM ranked
QUALIFY revenue_rank <= 500
ORDER BY revenue_rank;
