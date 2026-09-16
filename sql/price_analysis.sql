-- =====================================================================
-- price_analysis.sql — Price bands, conversion & cart behavior
-- =====================================================================
-- IMPORTANT: this dataset is observational. Any relationship between
-- price and conversion below is described as an ASSOCIATION, never a
-- causal effect (see README "Limitations").
-- =====================================================================

-- =====================================================================
-- F1. CONVERSION BY PRICE BAND
-- =====================================================================
SELECT
    price_band,
    n_products,
    view_events,
    cart_events,
    purchase_events,
    ROUND(100.0 * view_to_cart_rate, 2) AS view_to_cart_pct,
    ROUND(100.0 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(100.0 * cart_abandonment_rate, 2) AS cart_abandonment_pct,
    ROUND(revenue, 2) AS revenue
FROM agg_price_band_metrics
ORDER BY band_order;


-- =====================================================================
-- F2. PRICE BAND SHARE OF TRAFFIC VS SHARE OF REVENUE
-- Which price bands "punch above their weight" on revenue vs. traffic?
-- =====================================================================
WITH totals AS (
    SELECT SUM(view_events) AS total_views, SUM(revenue) AS total_revenue FROM agg_price_band_metrics
)
SELECT
    p.price_band,
    ROUND(100.0 * p.view_events / t.total_views, 2) AS pct_of_views,
    ROUND(100.0 * p.revenue / t.total_revenue, 2) AS pct_of_revenue,
    ROUND(100.0 * p.overall_conversion_rate, 2) AS overall_conversion_pct
FROM agg_price_band_metrics p
CROSS JOIN totals t
ORDER BY p.band_order;


-- =====================================================================
-- PRICE DISTRIBUTION WITHIN A CATEGORY VS CATEGORY CONVERSION
-- Useful drill-down when Page 6 recommends "investigate pricing" for a
-- specific underperforming category — this shows whether that category
-- is concentrated in a poorly-converting price band.
-- =====================================================================
SELECT
    COALESCE(spf.category_code, 'Uncategorized') AS category_code,
    spf.price_band,
    COUNT(*) FILTER (WHERE viewed) AS viewing_session_products,
    ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS overall_conversion_pct
FROM session_product_funnel spf
GROUP BY category_code, price_band
HAVING COUNT(*) FILTER (WHERE viewed) >= 200
ORDER BY category_code,
    CASE price_band
        WHEN 'Free ($0)' THEN 0 WHEN '$0-25' THEN 1 WHEN '$25-50' THEN 2 WHEN '$50-100' THEN 3
        WHEN '$100-250' THEN 4 WHEN '$250-500' THEN 5 WHEN '$500-1000' THEN 6 ELSE 7
    END;


-- =====================================================================
-- PRICE PERCENTILE BANDING (alternative to fixed $ bands) — uses
-- NTILE(10) to check conversion by price DECILE rather than fixed
-- dollar cutoffs, to confirm the fixed-band pattern isn't an artifact
-- of band boundaries.
-- =====================================================================
WITH product_deciles AS (
    SELECT
        product_id, avg_price, overall_conversion_rate, viewing_sessions,
        NTILE(10) OVER (ORDER BY avg_price) AS price_decile
    FROM agg_product_metrics
    WHERE viewing_sessions >= 50
)
SELECT
    price_decile,
    ROUND(MIN(avg_price), 2) AS min_price_in_decile,
    ROUND(MAX(avg_price), 2) AS max_price_in_decile,
    COUNT(*) AS n_products,
    ROUND(100.0 * AVG(overall_conversion_rate), 2) AS avg_conversion_pct
FROM product_deciles
GROUP BY price_decile
ORDER BY price_decile;
