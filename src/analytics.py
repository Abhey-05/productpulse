"""
analytics.py
-------------
PHASE 5 — Metrics / analytics layer.

Thin, framework-agnostic wrappers around SQL queries against the
precomputed agg_* tables (fast — thousands to low-millions of rows)
and, where a filter genuinely needs row-level detail, against
session_product_funnel / fact_events directly (still fast thanks to
the indexes created in the pipeline).

This module is used by BOTH the Streamlit dashboard (dashboard/app.py)
and the "Ask ProductPulse" AI analyst (src/ai_analyst.py) — it is the
single, tested source of truth for every number shown anywhere in the
project, which is what makes "validate dashboard KPIs against SQL"
possible: there's only one query per metric, not two.

Every function is READ-ONLY (SELECT only) and returns a pandas
DataFrame or plain Python scalar/dict — never raw SQL strings built
from unescaped user input beyond simple, whitelisted filter values.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from database import get_connection

PRICE_BAND_ORDER = [
    "Free ($0)", "$0-25", "$25-50", "$50-100",
    "$100-250", "$250-500", "$500-1000", "$1000+",
]


# ---------------------------------------------------------------------
# Executive Overview (Page 1)
# ---------------------------------------------------------------------
def get_overview_kpis(con: duckdb.DuckDBPyConnection) -> dict:
    """Headline KPIs for the Executive Overview page.

    Definitions:
      - total_users / total_sessions: distinct counts over all events.
      - views/carts/purchases: raw event counts (traffic volume).
      - purchase_conversion: purchasing sessions / viewing sessions,
        at the SESSION level (any product) — see funnel_analysis.sql A1.
      - cart_abandonment: 1 - (cart_to_purchase sessions / carting
        sessions), at the session-product level — see B1.
      - revenue: SUM(price) over purchase events (line-item proxy,
        not a true order total — no quantity field exists).
    """
    row = con.execute("""
        WITH macro AS (
            SELECT
                COUNT(*) FILTER (WHERE has_view) AS viewing_sessions,
                COUNT(*) FILTER (WHERE has_view AND has_cart) AS cart_sessions,
                COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) AS purchase_sessions
            FROM session_summary WHERE is_valid_session
        ),
        product_level AS (
            SELECT
                COUNT(*) FILTER (WHERE carted) AS carting_sp,
                COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase) AS abandoned_sp
            FROM session_product_funnel
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
            FROM fact_events
        )
        SELECT
            t.total_users, t.total_sessions, t.total_views, t.total_carts, t.total_purchases,
            t.total_revenue, t.start_date, t.end_date,
            m.viewing_sessions, m.cart_sessions, m.purchase_sessions,
            p.carting_sp, p.abandoned_sp
        FROM totals t CROSS JOIN macro m CROSS JOIN product_level p
    """).fetchone()

    (total_users, total_sessions, total_views, total_carts, total_purchases,
     total_revenue, start_date, end_date,
     viewing_sessions, cart_sessions, purchase_sessions,
     carting_sp, abandoned_sp) = row

    return {
        "total_users": total_users,
        "total_sessions": total_sessions,
        "total_views": total_views,
        "total_carts": total_carts,
        "total_purchases": total_purchases,
        "total_revenue": total_revenue,
        "start_date": start_date,
        "end_date": end_date,
        "session_view_to_cart_pct": 100.0 * cart_sessions / viewing_sessions if viewing_sessions else None,
        "session_cart_to_purchase_pct": 100.0 * purchase_sessions / cart_sessions if cart_sessions else None,
        "session_overall_conversion_pct": 100.0 * purchase_sessions / viewing_sessions if viewing_sessions else None,
        "cart_abandonment_pct": 100.0 * abandoned_sp / carting_sp if carting_sp else None,
    }


def get_daily_trend(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT
            event_date, day_of_week, n_views, n_carts, n_purchases, n_sessions, n_users, revenue,
            ROUND(AVG(n_purchases) OVER (ORDER BY event_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS purchases_7d_avg,
            ROUND(AVG(revenue) OVER (ORDER BY event_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS revenue_7d_avg
        FROM agg_daily_funnel
        ORDER BY event_date
    """).df()


def get_weekly_trend_wow(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Week-over-week trend with LAG-based % change — backs the AI
    Analyst's "why did conversion change" / "what changed vs last week"
    questions with real, queryable numbers (see time_analysis.sql J2)."""
    return con.execute("""
        WITH weekly AS (
            SELECT date_trunc('week', event_date) AS week_start,
                   SUM(n_views) AS n_views, SUM(n_carts) AS n_carts,
                   SUM(n_purchases) AS n_purchases, SUM(revenue) AS revenue
            FROM agg_daily_funnel GROUP BY 1
        )
        SELECT
            week_start, n_views, n_carts, n_purchases, revenue,
            LAG(revenue) OVER (ORDER BY week_start) AS prev_week_revenue,
            ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY week_start))
                / NULLIF(LAG(revenue) OVER (ORDER BY week_start), 0), 2) AS revenue_wow_change_pct,
            ROUND(100.0 * n_purchases / NULLIF(n_views, 0), 3) AS purchase_rate_of_views_pct,
            LAG(ROUND(100.0 * n_purchases / NULLIF(n_views, 0), 3)) OVER (ORDER BY week_start) AS prev_purchase_rate_pct
        FROM weekly ORDER BY week_start
    """).df()


def get_category_movers(con: duckdb.DuckDBPyConnection, n: int = 10) -> pd.DataFrame:
    """Categories with the largest Oct->Nov conversion change — backs
    "what changed compared with the previous period" (see time_analysis.sql P2)."""
    return con.execute("""
        WITH monthly AS (
            SELECT COALESCE(category_code, 'Uncategorized') AS category_code,
                   date_trunc('month', event_date) AS month,
                   SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
                   SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
            FROM fact_events GROUP BY 1, 2
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
        LIMIT ?
    """, [n]).df()


def get_macro_funnel_stages(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        WITH stages AS (
            SELECT 1 AS stage_order, 'View' AS stage, COUNT(*) FILTER (WHERE has_view) AS sessions
            FROM session_summary WHERE is_valid_session
            UNION ALL
            SELECT 2, 'Cart', COUNT(*) FILTER (WHERE has_view AND has_cart) FROM session_summary WHERE is_valid_session
            UNION ALL
            SELECT 3, 'Purchase', COUNT(*) FILTER (WHERE has_view AND has_cart AND has_purchase) FROM session_summary WHERE is_valid_session
        )
        SELECT stage_order, stage, sessions,
               ROUND(100.0 * sessions / FIRST_VALUE(sessions) OVER (ORDER BY stage_order), 2) AS pct_of_top,
               ROUND(100.0 - 100.0 * sessions / NULLIF(LAG(sessions) OVER (ORDER BY stage_order), 0), 2) AS drop_off_pct
        FROM stages ORDER BY stage_order
    """).df()


def get_top_categories(con: duckdb.DuckDBPyConnection, n: int = 10, by: str = "revenue") -> pd.DataFrame:
    order_col = {"revenue": "revenue", "views": "view_events", "conversion": "overall_conversion_rate"}.get(by, "revenue")
    return con.execute(f"""
        SELECT category_code, n_products, view_events, cart_events, purchase_events,
               overall_conversion_rate, revenue
        FROM agg_category_metrics
        WHERE view_events >= 500
        ORDER BY {order_col} DESC
        LIMIT ?
    """, [n]).df()


# ---------------------------------------------------------------------
# Funnel Analysis (Page 2) — filterable
# ---------------------------------------------------------------------
def get_filtered_funnel(
    con: duckdb.DuckDBPyConnection,
    category_code: str | None = None,
    brand: str | None = None,
    price_band: str | None = None,
    start_date=None,
    end_date=None,
) -> dict:
    """Product-level funnel (session_product_funnel grain) with optional
    filters. All filters are AND-combined; None means "no filter."
    """
    clauses, params = [], []
    if category_code:
        clauses.append("category_code = ?")
        params.append(category_code)
    if brand:
        clauses.append("brand = ?")
        params.append(brand)
    if price_band:
        clauses.append("price_band = ?")
        params.append(price_band)
    if start_date:
        clauses.append("event_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("event_date <= ?")
        params.append(end_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    row = con.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE viewed) AS viewing,
            COUNT(*) FILTER (WHERE view_to_cart) AS view_to_cart,
            COUNT(*) FILTER (WHERE carted) AS carting,
            COUNT(*) FILTER (WHERE cart_to_purchase) AS cart_to_purchase,
            COUNT(*) FILTER (WHERE view_to_purchase) AS view_to_purchase
        FROM session_product_funnel
        {where}
    """, params).fetchone()
    viewing, v2c, carting, c2p, v2p = row
    return {
        "viewing_sessions": viewing,
        "cart_sessions": v2c,
        "purchase_sessions": v2p,
        "view_to_cart_pct": 100.0 * v2c / viewing if viewing else None,
        "cart_to_purchase_pct": 100.0 * c2p / carting if carting else None,
        "overall_conversion_pct": 100.0 * v2p / viewing if viewing else None,
    }


def get_filter_options(con: duckdb.DuckDBPyConnection) -> dict:
    categories = con.execute("""
        SELECT category_code FROM agg_category_metrics
        WHERE view_events >= 500 ORDER BY view_events DESC
    """).df()["category_code"].tolist()
    brands = con.execute("""
        SELECT brand FROM agg_brand_metrics
        WHERE view_events >= 500 ORDER BY view_events DESC LIMIT 100
    """).df()["brand"].tolist()
    return {
        "categories": categories,
        "brands": brands,
        "price_bands": PRICE_BAND_ORDER,
    }


# ---------------------------------------------------------------------
# Product & Category Performance (Page 3)
# ---------------------------------------------------------------------
def get_top_products(con: duckdb.DuckDBPyConnection, by: str = "views", n: int = 25) -> pd.DataFrame:
    order_col = {
        "views": "view_events", "purchases": "purchase_events",
        "conversion": "overall_conversion_rate", "revenue": "revenue",
    }.get(by, "view_events")
    min_sessions_clause = "WHERE viewing_sessions >= 200" if by == "conversion" else ""
    return con.execute(f"""
        SELECT product_id, category_code, brand, avg_price,
               view_events, cart_events, purchase_events,
               viewing_sessions, overall_conversion_rate, revenue
        FROM agg_product_metrics
        {min_sessions_clause}
        ORDER BY {order_col} DESC
        LIMIT ?
    """, [n]).df()


def get_high_traffic_low_conversion_products(con: duckdb.DuckDBPyConnection, n: int = 30) -> pd.DataFrame:
    return con.execute("""
        WITH ranked AS (
            SELECT product_id, category_code, brand, avg_price,
                   viewing_sessions, purchasing_sessions, overall_conversion_rate, revenue,
                   NTILE(4) OVER (ORDER BY viewing_sessions) AS view_quartile,
                   PERCENT_RANK() OVER (ORDER BY overall_conversion_rate) AS conv_pctile
            FROM agg_product_metrics
            WHERE viewing_sessions >= 200
        )
        SELECT product_id, category_code, brand, avg_price, viewing_sessions,
               purchasing_sessions, overall_conversion_rate, revenue
        FROM ranked
        WHERE view_quartile = 4 AND conv_pctile <= 0.25
        ORDER BY viewing_sessions DESC
        LIMIT ?
    """, [n]).df()


def get_product_quadrants(con: duckdb.DuckDBPyConnection, min_sessions: int = 50) -> pd.DataFrame:
    """Data for the Views x Conversion x Revenue bubble scatter with a
    quadrant label (Star / High-traffic underperformer / Hidden gem /
    Low priority) relative to dataset medians.
    """
    return con.execute("""
        WITH thresholds AS (
            SELECT MEDIAN(viewing_sessions) AS med_views, MEDIAN(overall_conversion_rate) AS med_conv
            FROM agg_product_metrics WHERE viewing_sessions >= ?
        )
        SELECT
            m.product_id, m.category_code, m.brand, m.viewing_sessions,
            m.overall_conversion_rate, m.revenue,
            CASE
                WHEN m.viewing_sessions >= t.med_views AND m.overall_conversion_rate >= t.med_conv THEN 'Star'
                WHEN m.viewing_sessions >= t.med_views AND m.overall_conversion_rate <  t.med_conv THEN 'High-traffic underperformer'
                WHEN m.viewing_sessions <  t.med_views AND m.overall_conversion_rate >= t.med_conv THEN 'Hidden gem'
                ELSE 'Low priority'
            END AS quadrant
        FROM agg_product_metrics m CROSS JOIN thresholds t
        WHERE m.viewing_sessions >= ?
    """, [min_sessions, min_sessions]).df()


def get_category_metrics(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT * FROM agg_category_metrics WHERE view_events >= 500 ORDER BY view_events DESC
    """).df()


def get_brand_metrics(con: duckdb.DuckDBPyConnection, n: int = 30) -> pd.DataFrame:
    return con.execute("""
        SELECT * FROM agg_brand_metrics WHERE view_events >= 500 ORDER BY revenue DESC LIMIT ?
    """, [n]).df()


# ---------------------------------------------------------------------
# User Behavior (Page 4)
# ---------------------------------------------------------------------
def get_user_segments(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT activity_segment, COUNT(*) AS n_users,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_users,
               ROUND(AVG(total_events), 1) AS avg_events,
               ROUND(AVG(total_sessions), 1) AS avg_sessions,
               ROUND(SUM(total_revenue), 2) AS total_revenue
        FROM agg_user_metrics
        GROUP BY activity_segment
        ORDER BY total_revenue DESC
    """).df()


def get_new_vs_returning_weekly(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        WITH weekly_activity AS (
            SELECT date_trunc('week', event_date) AS week_start, user_id
            FROM fact_events GROUP BY 1, 2
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
    """).df()


def get_repeat_purchase_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT is_repeat_purchaser, COUNT(*) AS n_purchasers,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_purchasers,
               ROUND(SUM(total_revenue), 2) AS total_revenue,
               ROUND(100.0 * SUM(total_revenue) / SUM(SUM(total_revenue)) OVER (), 2) AS pct_of_revenue
        FROM agg_user_metrics WHERE is_purchaser
        GROUP BY is_repeat_purchaser
    """).df()


# ---------------------------------------------------------------------
# Price & Conversion (Page 5)
# ---------------------------------------------------------------------
def get_price_band_metrics(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM agg_price_band_metrics ORDER BY band_order").df()


def get_price_conversion_by_category(con: duckdb.DuckDBPyConnection, category_code: str) -> pd.DataFrame:
    return con.execute("""
        SELECT price_band,
               COUNT(*) FILTER (WHERE viewed) AS viewing_session_products,
               ROUND(100.0 * COUNT(*) FILTER (WHERE view_to_purchase) / NULLIF(COUNT(*) FILTER (WHERE viewed), 0), 2) AS overall_conversion_pct
        FROM session_product_funnel
        WHERE category_code = ?
        GROUP BY price_band
        HAVING COUNT(*) FILTER (WHERE viewed) >= 20
    """, [category_code]).df()


# ---------------------------------------------------------------------
# Insights & Recommendations (Page 6) — programmatic finding surfacing
# ---------------------------------------------------------------------
def get_high_traffic_low_revenue_categories(con: duckdb.DuckDBPyConnection, n: int = 5) -> pd.DataFrame:
    return con.execute("""
        SELECT category_code, view_events,
               ROUND(100.0 * pct_of_total_views, 2) AS pct_of_total_views,
               ROUND(100.0 * pct_of_total_revenue, 2) AS pct_of_total_revenue,
               ROUND(100.0 * overall_conversion_rate, 2) AS overall_conversion_pct
        FROM agg_category_metrics
        WHERE view_events >= 1000
        ORDER BY (pct_of_total_views - pct_of_total_revenue) DESC
        LIMIT ?
    """, [n]).df()


def get_worst_cart_abandonment_categories(con: duckdb.DuckDBPyConnection, n: int = 5) -> pd.DataFrame:
    return con.execute("""
        SELECT COALESCE(category_code, 'Uncategorized') AS category_code,
               COUNT(*) FILTER (WHERE carted) AS carting_session_products,
               ROUND(100.0 * COUNT(*) FILTER (WHERE carted AND NOT cart_to_purchase)
                   / NULLIF(COUNT(*) FILTER (WHERE carted), 0), 2) AS cart_abandonment_pct
        FROM session_product_funnel
        GROUP BY category_code
        HAVING COUNT(*) FILTER (WHERE carted) >= 500
        ORDER BY cart_abandonment_pct DESC
        LIMIT ?
    """, [n]).df()


if __name__ == "__main__":
    # Smoke test: run every function once and print shapes, to validate
    # the whole analytics layer against the live database (Phase 7).
    con = get_connection(read_only=True)
    print("Overview KPIs:", get_overview_kpis(con))
    print("Daily trend rows:", len(get_daily_trend(con)))
    print("Top categories:\n", get_top_categories(con))
    print("Top products by views:\n", get_top_products(con, by="views", n=5))
    print("High-traffic/low-conversion products:\n", get_high_traffic_low_conversion_products(con, n=5))
    print("Category metrics rows:", len(get_category_metrics(con)))
    print("Brand metrics rows:", len(get_brand_metrics(con)))
    print("User segments:\n", get_user_segments(con))
    print("Price band metrics:\n", get_price_band_metrics(con))
    print("High-traffic/low-revenue categories:\n", get_high_traffic_low_revenue_categories(con))
    print("Worst cart abandonment categories:\n", get_worst_cart_abandonment_categories(con))
    con.close()
