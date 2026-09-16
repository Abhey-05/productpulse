-- =====================================================================
-- time_analysis.sql — Daily/weekly trends & hour-of-day patterns
-- =====================================================================

-- =====================================================================
-- J1. DAILY TREND WITH 7-DAY ROLLING AVERAGE
-- Rolling average smooths day-of-week noise (e.g. weekend spikes) so
-- underlying trend direction is visible — classic window-frame query.
-- =====================================================================
SELECT
    event_date,
    day_of_week,
    n_views, n_carts, n_purchases,
    ROUND(100.0 * n_purchases / NULLIF(n_carts, 0), 2) AS daily_cart_to_purchase_pct,
    revenue,
    ROUND(AVG(n_purchases) OVER (
        ORDER BY event_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 1) AS purchases_7d_rolling_avg,
    ROUND(AVG(revenue) OVER (
        ORDER BY event_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 2) AS revenue_7d_rolling_avg
FROM agg_daily_funnel
ORDER BY event_date;


-- =====================================================================
-- J2. WEEK-OVER-WEEK TREND (LAG for period comparison)
-- =====================================================================
WITH weekly AS (
    SELECT
        date_trunc('week', event_date) AS week_start,
        SUM(n_views) AS n_views,
        SUM(n_carts) AS n_carts,
        SUM(n_purchases) AS n_purchases,
        SUM(revenue) AS revenue
    FROM agg_daily_funnel
    GROUP BY 1
)
SELECT
    week_start,
    n_views, n_carts, n_purchases, revenue,
    LAG(revenue) OVER (ORDER BY week_start) AS prev_week_revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY week_start))
        / NULLIF(LAG(revenue) OVER (ORDER BY week_start), 0), 2) AS revenue_wow_change_pct,
    ROUND(100.0 * n_purchases / NULLIF(n_views, 0), 3) AS purchase_rate_of_views_pct
FROM weekly
ORDER BY week_start;


-- =====================================================================
-- HOUR-OF-DAY PATTERNS — when do users browse vs. buy?
-- Also computes each hour's conversion (purchase events / view events)
-- to check whether high-traffic hours convert as well as they attract
-- attention.
-- =====================================================================
SELECT
    event_hour,
    SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
    SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS carts,
    SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases,
    ROUND(100.0 * SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END), 0), 3) AS purchase_rate_of_views_pct,
    RANK() OVER (ORDER BY SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) DESC) AS traffic_rank
FROM fact_events
GROUP BY event_hour
ORDER BY event_hour;


-- =====================================================================
-- DAY-OF-WEEK SEASONALITY — average funnel performance by weekday
-- (Mon/Tue/... averaged across all weeks in the dataset).
-- =====================================================================
SELECT
    day_of_week,
    ROUND(AVG(n_views), 0) AS avg_views,
    ROUND(AVG(n_carts), 0) AS avg_carts,
    ROUND(AVG(n_purchases), 0) AS avg_purchases,
    ROUND(AVG(revenue), 2) AS avg_revenue,
    ROUND(100.0 * AVG(n_purchases) / NULLIF(AVG(n_views), 0), 3) AS avg_purchase_rate_of_views_pct
FROM agg_daily_funnel
GROUP BY day_of_week
ORDER BY avg_revenue DESC;


-- =====================================================================
-- P1. CATEGORY PERFORMANCE OVER TIME (Oct vs Nov month-over-month)
-- Surfaces categories whose conversion improved/declined between the
-- two months in the dataset — the closest thing to a trend signal
-- available without a longer history. Uses LAG across an ordered
-- month axis per category.
-- =====================================================================
WITH monthly AS (
    SELECT
        COALESCE(category_code, 'Uncategorized') AS category_code,
        date_trunc('month', event_date) AS month,
        SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
    FROM fact_events
    GROUP BY 1, 2
),
with_rate AS (
    SELECT
        category_code, month, views, purchases,
        ROUND(100.0 * purchases / NULLIF(views, 0), 3) AS conversion_pct
    FROM monthly
    WHERE views >= 500
)
SELECT
    category_code, month, views, purchases, conversion_pct,
    LAG(conversion_pct) OVER (PARTITION BY category_code ORDER BY month) AS prev_month_conversion_pct,
    ROUND(conversion_pct - LAG(conversion_pct) OVER (PARTITION BY category_code ORDER BY month), 3) AS conversion_pct_change
FROM with_rate
ORDER BY category_code, month;


-- =====================================================================
-- P2. BIGGEST MOVERS — categories with the largest conversion change
-- Oct -> Nov (both directions), min-volume filtered. This directly
-- powers the "what changed compared with the previous period" question
-- the AI Analyst answers.
-- =====================================================================
WITH monthly AS (
    SELECT
        COALESCE(category_code, 'Uncategorized') AS category_code,
        date_trunc('month', event_date) AS month,
        SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
    FROM fact_events
    GROUP BY 1, 2
    HAVING SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) >= 500
),
pivoted AS (
    SELECT
        category_code,
        MAX(CASE WHEN month = '2019-10-01' THEN 100.0 * purchases / NULLIF(views, 0) END) AS oct_conversion_pct,
        MAX(CASE WHEN month = '2019-11-01' THEN 100.0 * purchases / NULLIF(views, 0) END) AS nov_conversion_pct
    FROM monthly
    GROUP BY category_code
)
SELECT
    category_code,
    ROUND(oct_conversion_pct, 3) AS oct_conversion_pct,
    ROUND(nov_conversion_pct, 3) AS nov_conversion_pct,
    ROUND(nov_conversion_pct - oct_conversion_pct, 3) AS conversion_pct_change
FROM pivoted
WHERE oct_conversion_pct IS NOT NULL AND nov_conversion_pct IS NOT NULL
ORDER BY ABS(nov_conversion_pct - oct_conversion_pct) DESC
LIMIT 20;
