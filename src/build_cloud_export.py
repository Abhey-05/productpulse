"""
build_cloud_export.py
----------------------
Builds a small (~10MB), fully self-contained DuckDB database for the
public Streamlit Cloud deployment. The full local database
(data/processed/productpulse.duckdb) is 12GB+ (109.8M-row fact table,
69.8M-row session-product funnel) and cannot be committed to GitHub or
run on Streamlit Community Cloud's free tier.

This script copies the small precomputed agg_*/dim_* tables as-is, and
replaces every analytics.py query that touches a huge table
(fact_events, session_summary, session_product_funnel, or the
5.3M-row agg_user_metrics) with a precomputed small result table. See
dashboard/app_cloud.py + src/analytics_cloud.py for how these are
consumed — every number is still a real, direct query result against
the full dataset, just computed once here instead of live per request.
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT_ROOT / "data" / "processed" / "productpulse.duckdb"
CLOUD_DB = PROJECT_ROOT / "data" / "cloud" / "productpulse_cloud.duckdb"


def main():
    CLOUD_DB.parent.mkdir(parents=True, exist_ok=True)
    if CLOUD_DB.exists():
        CLOUD_DB.unlink()

    con = duckdb.connect(str(CLOUD_DB))
    con.execute(f"ATTACH '{SOURCE_DB}' AS src (READ_ONLY)")

    # 1. Small tables copied as-is — same name/schema, so most of
    # analytics.py's functions work completely unchanged against this db.
    for t in ["dim_product", "dim_category", "agg_daily_funnel",
              "agg_product_metrics", "agg_category_metrics",
              "agg_brand_metrics", "agg_price_band_metrics"]:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t}")
        print(f"{t}: {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:,} rows")

    # 2. cloud_overview_kpis — replaces get_overview_kpis (touches
    # fact_events + session_summary + session_product_funnel).
    con.execute("""
        CREATE TABLE cloud_overview_kpis AS
        WITH macro AS (
            SELECT
                COUNT(*) FILTER (WHERE has_view) AS viewing_sessions,
                COUNT(*) FILTER (WHERE has_view AND has_cart) AS cart_sessions,
                COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) AS purchase_sessions
            FROM src.session_summary WHERE is_valid_session
        ),
        product_level AS (
            SELECT
                COUNT(*) FILTER (WHERE carted) AS carting_sp,
                COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) AS abandoned_sp
            FROM src.session_product_funnel
        ),
        totals AS (
            SELECT
                COUNT(DISTINCT user_id) AS total_users,
                COUNT(DISTINCT user_session) AS total_sessions,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS total_views,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS total_carts,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS total_purchases,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS total_revenue,
                MIN(event_date) AS start_date,
                MAX(event_date) AS end_date
            FROM src.fact_events
        )
        SELECT
            t.total_users, t.total_sessions, t.total_views, t.total_carts, t.total_purchases,
            t.total_revenue, t.start_date, t.end_date,
            m.viewing_sessions, m.cart_sessions, m.purchase_sessions,
            p.carting_sp, p.abandoned_sp,
            100.0 * m.cart_sessions / m.viewing_sessions AS session_view_to_cart_pct,
            100.0 * m.purchase_sessions / m.cart_sessions AS session_cart_to_purchase_pct,
            100.0 * m.purchase_sessions / m.viewing_sessions AS session_overall_conversion_pct,
            100.0 * p.abandoned_sp / p.carting_sp AS cart_abandonment_pct
        FROM totals t CROSS JOIN macro m CROSS JOIN product_level p
    """)
    print("cloud_overview_kpis: 1 row")

    # 3. cloud_macro_funnel_stages — replaces get_macro_funnel_stages
    # (touches session_summary, 23M rows).
    con.execute("""
        CREATE TABLE cloud_macro_funnel_stages AS
        WITH stages AS (
            SELECT 1 AS stage_order, 'View' AS stage, COUNT(*) FILTER (WHERE has_view) AS sessions
            FROM src.session_summary WHERE is_valid_session
            UNION ALL
            SELECT 2, 'Cart', COUNT(*) FILTER (WHERE has_view AND has_cart) FROM src.session_summary WHERE is_valid_session
            UNION ALL
            SELECT 3, 'Purchase', COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) FROM src.session_summary WHERE is_valid_session
        )
        SELECT stage_order, stage, sessions,
               ROUND(100.0 * sessions / FIRST_VALUE(sessions) OVER (ORDER BY stage_order), 2) AS pct_of_top,
               ROUND(100.0 - 100.0 * sessions / NULLIF(LAG(sessions) OVER (ORDER BY stage_order), 0), 2) AS drop_off_pct
        FROM stages ORDER BY stage_order
    """)
    print("cloud_macro_funnel_stages:", con.execute("SELECT COUNT(*) FROM cloud_macro_funnel_stages").fetchone()[0], "rows")

    # 4. cloud_category_movers — replaces get_category_movers (touches
    # fact_events, 109.8M rows). Precompute generously (n=60) since it's tiny.
    con.execute("""
        CREATE TABLE cloud_category_movers AS
        WITH monthly AS (
            SELECT COALESCE(category_code, 'Uncategorized') AS category_code,
                   date_trunc('month', event_date) AS month,
                   SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
                   SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
            FROM src.fact_events GROUP BY 1, 2
            HAVING SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) >= 500
        ),
        pivoted AS (
            SELECT category_code,
                MAX(CASE WHEN month = '2019-10-01' THEN 100.0 * purchases / NULLIF(views, 0) END) AS oct_conversion_pct,
                MAX(CASE WHEN month = '2019-11-01' THEN 100.0 * purchases / NULLIF(views, 0) END) AS nov_conversion_pct
            FROM monthly GROUP BY category_code
        )
        SELECT category_code, ROUND(oct_conversion_pct, 3) AS oct_conversion_pct,
               ROUND(nov_conversion_pct, 3) AS nov_conversion_pct,
               ROUND(nov_conversion_pct - oct_conversion_pct, 3) AS conversion_pct_change
        FROM pivoted
        WHERE oct_conversion_pct IS NOT NULL AND nov_conversion_pct IS NOT NULL
        ORDER BY ABS(nov_conversion_pct - oct_conversion_pct) DESC
        LIMIT 60
    """)
    print("cloud_category_movers:", con.execute("SELECT COUNT(*) FROM cloud_category_movers").fetchone()[0], "rows")

    # 5. cloud_new_vs_returning_weekly — replaces get_new_vs_returning_weekly
    # (touches fact_events, 109.8M rows).
    con.execute("""
        CREATE TABLE cloud_new_vs_returning_weekly AS
        WITH weekly_activity AS (
            SELECT date_trunc('week', event_date) AS week_start, user_id
            FROM src.fact_events GROUP BY 1, 2
        ),
        user_first_week AS (
            SELECT user_id, MIN(week_start) AS first_week FROM weekly_activity GROUP BY user_id
        )
        SELECT
            wa.week_start,
            COUNT(*) FILTER (WHERE wa.week_start = uf.first_week) AS new_users,
            COUNT(*) FILTER (WHERE wa.week_start > uf.first_week) AS returning_users
        FROM weekly_activity wa JOIN user_first_week uf USING (user_id)
        GROUP BY wa.week_start ORDER BY wa.week_start
    """)
    print("cloud_new_vs_returning_weekly:", con.execute("SELECT COUNT(*) FROM cloud_new_vs_returning_weekly").fetchone()[0], "rows")

    # 6. cloud_user_segments — replaces get_user_segments (touches
    # agg_user_metrics, 5.3M rows / 45MB as parquet — too big to ship raw).
    con.execute("""
        CREATE TABLE cloud_user_segments AS
        SELECT activity_segment, COUNT(*) AS n_users,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_users,
               ROUND(AVG(total_events), 1) AS avg_events,
               ROUND(AVG(total_sessions), 1) AS avg_sessions,
               ROUND(SUM(total_revenue), 2) AS total_revenue
        FROM src.agg_user_metrics
        GROUP BY activity_segment
        ORDER BY total_revenue DESC
    """)
    print("cloud_user_segments:", con.execute("SELECT COUNT(*) FROM cloud_user_segments").fetchone()[0], "rows")

    # 7. cloud_repeat_purchase_summary — replaces get_repeat_purchase_summary.
    con.execute("""
        CREATE TABLE cloud_repeat_purchase_summary AS
        SELECT is_repeat_purchaser, COUNT(*) AS n_purchasers,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_purchasers,
               ROUND(SUM(total_revenue), 2) AS total_revenue,
               ROUND(100.0 * SUM(total_revenue) / SUM(SUM(total_revenue)) OVER (), 2) AS pct_of_revenue
        FROM src.agg_user_metrics WHERE is_purchaser
        GROUP BY is_repeat_purchaser
    """)
    print("cloud_repeat_purchase_summary:", con.execute("SELECT COUNT(*) FROM cloud_repeat_purchase_summary").fetchone()[0], "rows")

    # 8. cloud_category_price_band — replaces get_price_conversion_by_category
    # (touches session_product_funnel, 69.8M rows). Precomputed for EVERY
    # category at once (<=1032 rows: 129 categories x 8 price bands).
    con.execute("""
        CREATE TABLE cloud_category_price_band AS
        SELECT COALESCE(category_code, 'Uncategorized') AS category_code,
               price_band,
               COUNT(*) FILTER (WHERE viewed) AS viewing_session_products,
               ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS overall_conversion_pct
        FROM src.session_product_funnel
        GROUP BY category_code, price_band
        HAVING COUNT(*) FILTER (WHERE viewed) >= 20
    """)
    print("cloud_category_price_band:", con.execute("SELECT COUNT(*) FROM cloud_category_price_band").fetchone()[0], "rows")

    # 9. cloud_category_abandonment — replaces get_worst_cart_abandonment_categories
    # AND the Funnel Analysis page's inline unfiltered category-abandonment
    # query (both touch session_product_funnel directly). All qualifying
    # categories precomputed at once (<=129 rows); callers LIMIT/ORDER as needed.
    con.execute("""
        CREATE TABLE cloud_category_abandonment AS
        SELECT COALESCE(category_code, 'Uncategorized') AS category_code,
               COUNT(*) FILTER (WHERE carted) AS carting_session_products,
               ROUND(100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase)
                   / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_abandonment_pct
        FROM src.session_product_funnel
        GROUP BY category_code
        HAVING COUNT(*) FILTER (WHERE carted) >= 500
    """)
    print("cloud_category_abandonment:", con.execute("SELECT COUNT(*) FROM cloud_category_abandonment").fetchone()[0], "rows")

    con.execute("DETACH src")
    con.execute("CHECKPOINT")
    con.close()

    size_mb = CLOUD_DB.stat().st_size / (1024 * 1024)
    print(f"\nCloud DB built: {CLOUD_DB} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
