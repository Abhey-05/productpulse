-- =====================================================================
-- segmentation.sql — User-level behavior & segmentation
-- =====================================================================
-- No demographic fields exist in this dataset (see DATA_DICTIONARY.md),
-- so all segmentation here is BEHAVIORAL: activity level, recency,
-- and purchase history derived purely from event logs.
-- =====================================================================

-- =====================================================================
-- H1. USER ACTIVITY SEGMENTS (K + H combined)
-- 'Viewer only' / 'Cart, no purchase' / 'One-time buyer' / 'Repeat buyer'
-- =====================================================================
SELECT
    activity_segment,
    COUNT(*) AS n_users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_users,
    ROUND(AVG(total_events), 1) AS avg_events_per_user,
    ROUND(AVG(total_sessions), 1) AS avg_sessions_per_user,
    ROUND(AVG(total_revenue), 2) AS avg_revenue_per_user,
    ROUND(SUM(total_revenue), 2) AS total_revenue_from_segment
FROM agg_user_metrics
GROUP BY activity_segment
ORDER BY total_revenue_from_segment DESC;


-- =====================================================================
-- H2. REPEAT PURCHASE BEHAVIOR — how much of revenue comes from
-- repeat buyers vs. one-time buyers? (classic retention-value question)
-- =====================================================================
SELECT
    is_repeat_purchaser,
    COUNT(*) AS n_purchasers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_purchasers,
    ROUND(SUM(total_revenue), 2) AS total_revenue,
    ROUND(100.0 * SUM(total_revenue) / SUM(SUM(total_revenue)) OVER (), 2) AS pct_of_purchaser_revenue,
    ROUND(AVG(total_purchases), 2) AS avg_purchase_events
FROM agg_user_metrics
WHERE is_purchaser
GROUP BY is_repeat_purchaser;


-- =====================================================================
-- I1. NEW VS RETURNING USERS BY WEEK
-- A user is "new" in the week containing their first-ever event
-- (first_seen_date), "returning" in any subsequent active week.
-- This is derivable here ONLY because the dataset covers a full 61-day
-- window from a clean start (Oct 1) — a user's true "first ever" visit
-- to the site is not knowable if it happened before Oct 1, so this is
-- reported as "new/returning within the observed window," not
-- lifetime new/returning. Stated explicitly in README limitations.
-- =====================================================================
WITH weekly_activity AS (
    SELECT
        date_trunc('week', event_date) AS week_start,
        user_id
    FROM fact_events
    GROUP BY 1, 2
),
user_first_week AS (
    SELECT user_id, MIN(week_start) AS first_week FROM weekly_activity GROUP BY user_id
)
SELECT
    wa.week_start,
    COUNT(*) FILTER (WHERE wa.week_start = uf.first_week) AS new_users,
    COUNT(*) FILTER (WHERE wa.week_start > uf.first_week) AS returning_users
FROM weekly_activity wa
JOIN user_first_week uf USING (user_id)
GROUP BY wa.week_start
ORDER BY wa.week_start;


-- =====================================================================
-- K1. USER EVENT FREQUENCY DISTRIBUTION — how "engaged" is the typical
-- user? Uses NTILE to bucket users into engagement deciles.
-- =====================================================================
WITH deciles AS (
    SELECT
        user_id, total_events, total_purchases, total_revenue,
        NTILE(10) OVER (ORDER BY total_events) AS engagement_decile
    FROM agg_user_metrics
)
SELECT
    engagement_decile,
    COUNT(*) AS n_users,
    MIN(total_events) AS min_events, MAX(total_events) AS max_events,
    ROUND(AVG(total_events), 1) AS avg_events,
    ROUND(100.0 * SUM(CASE WHEN total_purchases > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_who_purchased,
    ROUND(SUM(total_revenue), 2) AS total_revenue
FROM deciles
GROUP BY engagement_decile
ORDER BY engagement_decile;


-- =====================================================================
-- RFM-STYLE SEGMENTATION (Recency / Frequency / Monetary) among
-- purchasers — a standard product-analytics segmentation, built here
-- with NTILE quintiles per dimension.
-- Recency = days between last purchase and the dataset's last day
-- (lower = more recent = better, so recency score is inverted).
-- =====================================================================
WITH dataset_end AS (SELECT MAX(event_date) AS max_date FROM fact_events),
purchaser_stats AS (
    SELECT
        f.user_id,
        MAX(f.event_date) AS last_purchase_date,
        COUNT(DISTINCT f.event_date) AS purchase_frequency_days,
        SUM(f.price) AS monetary_value
    FROM fact_events f
    WHERE f.event_type = 'purchase'
    GROUP BY f.user_id
),
scored AS (
    SELECT
        p.user_id,
        d.max_date - p.last_purchase_date AS recency_days,
        p.purchase_frequency_days,
        p.monetary_value,
        NTILE(5) OVER (ORDER BY d.max_date - p.last_purchase_date DESC) AS recency_score,   -- 5 = most recent
        NTILE(5) OVER (ORDER BY p.purchase_frequency_days ASC) AS frequency_score,          -- 5 = most frequent
        NTILE(5) OVER (ORDER BY p.monetary_value ASC) AS monetary_score                     -- 5 = highest spend
    FROM purchaser_stats p
    CROSS JOIN dataset_end d
)
SELECT
    recency_score, frequency_score, monetary_score,
    (recency_score + frequency_score + monetary_score) AS rfm_total,
    COUNT(*) AS n_users,
    ROUND(AVG(monetary_value), 2) AS avg_monetary_value
FROM scored
GROUP BY recency_score, frequency_score, monetary_score
ORDER BY rfm_total DESC
LIMIT 30;
