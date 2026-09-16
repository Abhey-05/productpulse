-- =====================================================================
-- advanced_analysis.sql — Cohort view, funnel diagnostics, cross-cuts
-- =====================================================================
-- These queries combine multiple advanced SQL techniques (CTEs chained
-- together, multiple window function types, conditional aggregation)
-- to answer compound product questions that a single simple query
-- can't.
-- =====================================================================

-- =====================================================================
-- WEEKLY ACQUISITION COHORTS — purchase-conversion cohort by the week
-- a user was first seen. This is the cohort/time-based analysis the
-- data genuinely supports: a "cohort" here = users grouped by their
-- first-active week; we then track how many of them purchase in
-- subsequent weeks of the same 61-day window. (True long-horizon
-- retention curves aren't possible — the observation window is only
-- 61 days — this is disclosed in README limitations.)
-- =====================================================================
WITH user_first_week AS (
    SELECT user_id, date_trunc('week', MIN(event_date)) AS cohort_week
    FROM fact_events
    GROUP BY user_id
),
user_activity_weeks AS (
    SELECT DISTINCT user_id, date_trunc('week', event_date) AS activity_week
    FROM fact_events
    WHERE event_type = 'purchase'
),
cohort_activity AS (
    SELECT
        f.cohort_week,
        a.activity_week,
        DATE_DIFF('week', f.cohort_week, a.activity_week) AS weeks_since_cohort,
        COUNT(DISTINCT a.user_id) AS purchasing_users
    FROM user_first_week f
    JOIN user_activity_weeks a USING (user_id)
    WHERE a.activity_week >= f.cohort_week
    GROUP BY f.cohort_week, a.activity_week
),
cohort_size AS (
    SELECT cohort_week, COUNT(*) AS cohort_users
    FROM user_first_week
    GROUP BY cohort_week
)
SELECT
    ca.cohort_week,
    cs.cohort_users,
    ca.weeks_since_cohort,
    ca.purchasing_users,
    ROUND(100.0 * ca.purchasing_users / cs.cohort_users, 2) AS pct_of_cohort_purchasing
FROM cohort_activity ca
JOIN cohort_size cs USING (cohort_week)
WHERE ca.weeks_since_cohort <= 8
ORDER BY ca.cohort_week, ca.weeks_since_cohort;


-- =====================================================================
-- FUNNEL DROP-OFF SEVERITY RANKING ACROSS CATEGORIES
-- Combines two window functions (RANK for view-to-cart drop-off and
-- cart-to-purchase drop-off) to flag WHERE in the funnel each category
-- is weakest — discovery stage vs. checkout stage.
-- =====================================================================
WITH cat_funnel AS (
    SELECT
        category_code,
        view_to_cart_rate,
        cart_to_purchase_rate,
        overall_conversion_rate
    FROM agg_category_metrics
    WHERE view_events >= 1000
)
SELECT
    category_code,
    ROUND(100.0 * view_to_cart_rate, 2) AS view_to_cart_pct,
    ROUND(100.0 * cart_to_purchase_rate, 2) AS cart_to_purchase_pct,
    RANK() OVER (ORDER BY view_to_cart_rate ASC) AS weakest_at_discovery_rank,
    RANK() OVER (ORDER BY cart_to_purchase_rate ASC) AS weakest_at_checkout_rank,
    CASE
        WHEN RANK() OVER (ORDER BY view_to_cart_rate ASC) <= 10 THEN 'Discovery-stage friction'
        WHEN RANK() OVER (ORDER BY cart_to_purchase_rate ASC) <= 10 THEN 'Checkout-stage friction'
        ELSE 'Not a top-10 outlier'
    END AS diagnosis
FROM cat_funnel
ORDER BY weakest_at_discovery_rank
LIMIT 15;


-- =====================================================================
-- SESSION DEPTH VS CONVERSION — do sessions that view MORE distinct
-- products convert better or worse? (association only). Uses CASE WHEN
-- conditional aggregation to bucket session depth, then compares.
-- =====================================================================
WITH session_depth AS (
    SELECT
        user_session,
        COUNT(DISTINCT product_id) AS distinct_products_viewed,
        MAX(CASE WHEN purchased THEN 1 ELSE 0 END) AS session_purchased
    FROM session_product_funnel
    WHERE viewed
    GROUP BY user_session
)
SELECT
    CASE
        WHEN distinct_products_viewed = 1 THEN '1 product'
        WHEN distinct_products_viewed BETWEEN 2 AND 3 THEN '2-3 products'
        WHEN distinct_products_viewed BETWEEN 4 AND 6 THEN '4-6 products'
        WHEN distinct_products_viewed BETWEEN 7 AND 10 THEN '7-10 products'
        ELSE '11+ products'
    END AS session_depth_bucket,
    COUNT(*) AS n_sessions,
    ROUND(100.0 * SUM(session_purchased) / COUNT(*), 2) AS purchase_rate_pct
FROM session_depth
GROUP BY 1
ORDER BY MIN(distinct_products_viewed);


-- =====================================================================
-- PRODUCT LIFECYCLE — first-seen vs last-seen date and whether a
-- product's conversion held up throughout its observed lifetime.
-- (Identifies products that may be running out of stock / losing
-- relevance vs. consistently strong performers.)
-- =====================================================================
WITH product_month AS (
    SELECT
        product_id,
        date_trunc('month', event_date) AS month,
        SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
    FROM fact_events
    GROUP BY 1, 2
)
SELECT
    p.product_id,
    p.category_code,
    p.brand,
    p.first_seen_date,
    p.last_seen_date,
    DATE_DIFF('day', p.first_seen_date, p.last_seen_date) AS days_active,
    SUM(pm.purchases) AS total_purchases
FROM dim_product p
JOIN product_month pm USING (product_id)
GROUP BY p.product_id, p.category_code, p.brand, p.first_seen_date, p.last_seen_date
HAVING SUM(pm.purchases) >= 20
ORDER BY total_purchases DESC
LIMIT 25;


-- =====================================================================
-- CONDITIONAL AGGREGATION SUMMARY — a single "scorecard" row per
-- category combining funnel, price, and revenue signals for the
-- Insights & Recommendations page to scan for outliers programmatically.
-- =====================================================================
SELECT
    category_code,
    n_products,
    view_events,
    ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * pct_of_total_views, 2) AS pct_of_total_views,
    ROUND(100.0 * pct_of_total_revenue, 2) AS pct_of_total_revenue,
    CASE
        WHEN pct_of_total_views > pct_of_total_revenue * 1.5 THEN 'Traffic-heavy, revenue-light'
        WHEN pct_of_total_revenue > pct_of_total_views * 1.5 THEN 'Revenue-heavy, traffic-light'
        ELSE 'Balanced'
    END AS traffic_revenue_profile
FROM agg_category_metrics
WHERE view_events >= 1000
ORDER BY view_events DESC;
