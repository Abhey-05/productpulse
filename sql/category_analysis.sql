-- =====================================================================
-- category_analysis.sql — Category & brand performance
-- =====================================================================

-- =====================================================================
-- D1. CATEGORY-LEVEL FUNNEL & CONVERSION
-- =====================================================================
SELECT
    category_code,
    n_products,
    view_events,
    cart_events,
    purchase_events,
    ROUND(100.0 * view_to_cart_rate, 2) AS view_to_cart_pct,
    ROUND(100.0 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * pct_of_total_views, 2) AS pct_of_total_views,
    ROUND(100.0 * pct_of_total_revenue, 2) AS pct_of_total_revenue
FROM agg_category_metrics
WHERE view_events >= 1000
ORDER BY view_events DESC;


-- =====================================================================
-- D2. HIGH-TRAFFIC / LOW-CONVERSION CATEGORIES
-- The headline "product opportunity" query: categories that pull a
-- disproportionate share of views relative to their share of revenue.
-- =====================================================================
SELECT
    category_code,
    view_events,
    ROUND(100.0 * pct_of_total_views, 2) AS pct_of_total_views,
    ROUND(100.0 * pct_of_total_revenue, 2) AS pct_of_total_revenue,
    ROUND(100.0 * pct_of_total_views - 100.0 * pct_of_total_revenue, 2) AS views_minus_revenue_share_gap,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct
FROM agg_category_metrics
WHERE view_events >= 1000
ORDER BY views_minus_revenue_share_gap DESC
LIMIT 15;


-- =====================================================================
-- M1. CATEGORY REVENUE CONTRIBUTION — ranked with RANK/DENSE_RANK,
-- plus cumulative share (running total window function).
-- =====================================================================
WITH ranked AS (
    SELECT
        category_code,
        revenue,
        RANK() OVER (ORDER BY revenue DESC) AS revenue_rank,
        SUM(revenue) OVER () AS total_revenue
    FROM agg_category_metrics
)
SELECT
    revenue_rank,
    category_code,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * revenue / total_revenue, 2) AS pct_of_total_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue_rank) / total_revenue, 2) AS cumulative_revenue_pct
FROM ranked
ORDER BY revenue_rank;


-- =====================================================================
-- G1. BRAND PERFORMANCE — views, cart adds, purchases, conversion
-- =====================================================================
SELECT
    brand,
    n_products,
    view_events,
    cart_events,
    purchase_events,
    ROUND(100.0 * view_to_cart_rate, 2) AS view_to_cart_pct,
    ROUND(100.0 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(revenue, 2) AS revenue
FROM agg_brand_metrics
WHERE view_events >= 1000
ORDER BY revenue DESC
LIMIT 25;


-- =====================================================================
-- G2. STRONGEST & WEAKEST BRANDS BY CONVERSION (min-volume filtered)
-- Uses DENSE_RANK twice (best and worst) in one pass via CASE WHEN.
-- =====================================================================
WITH ranked AS (
    SELECT
        brand, view_events, purchase_events, overall_conversion_rate, revenue,
        DENSE_RANK() OVER (ORDER BY overall_conversion_rate DESC) AS best_rank,
        DENSE_RANK() OVER (ORDER BY overall_conversion_rate ASC) AS worst_rank
    FROM agg_brand_metrics
    WHERE view_events >= 2000
)
SELECT 'Top converting' AS grp, brand, view_events, purchase_events,
       ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct, ROUND(revenue, 2) AS revenue
FROM ranked WHERE best_rank <= 10
UNION ALL
SELECT 'Bottom converting', brand, view_events, purchase_events,
       ROUND(100.0 * overall_conversion_rate, 2), ROUND(revenue, 2)
FROM ranked WHERE worst_rank <= 10
ORDER BY grp, overall_conversion_pct DESC;


-- =====================================================================
-- CATEGORY ENGAGEMENT DEPTH — avg products viewed per session within
-- category vs. category conversion (are "browsier" categories worse
-- converters? association only, not causal).
-- =====================================================================
SELECT
    COALESCE(spf.category_code, 'Uncategorized') AS category_code,
    COUNT(*) AS session_product_rows,
    COUNT(DISTINCT spf.user_session) AS distinct_sessions,
    ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT spf.user_session), 2) AS avg_products_viewed_per_session,
    ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS overall_conversion_pct
FROM session_product_funnel spf
GROUP BY category_code
HAVING COUNT(*) FILTER (WHERE viewed) >= 1000
ORDER BY avg_products_viewed_per_session DESC
LIMIT 20;
