"""
analytics_cloud.py
-------------------
Cloud-deployment variant of analytics.py, for dashboard/app_cloud.py.

The public Streamlit Cloud deploy runs against data/cloud/productpulse_cloud.duckdb
(~10MB, built by src/build_cloud_export.py) instead of the full local
109.8M-row database (12GB, git-ignored, never committed).

Every function here that reads an unchanged small table (agg_*/dim_*)
is imported straight from analytics.py — same SQL, same table names,
same result. Only the functions whose original SQL touched a huge
table (fact_events, session_summary, session_product_funnel, or the
5.3M-row agg_user_metrics) are overridden below to read the
precomputed cloud_* replacement table instead. Every number is still a
real, direct query result computed from the full dataset — just
computed once at export time rather than live per request. See
build_cloud_export.py for exactly how each cloud_* table was derived.
"""

import duckdb
import pandas as pd

# Re-exported unchanged: these only ever query agg_*/dim_* tables,
# which are copied into the cloud DB with identical schema.
from analytics import (  # noqa: F401
    PRICE_BAND_ORDER,
    get_daily_trend,
    get_weekly_trend_wow,
    get_top_categories,
    get_top_products,
    get_high_traffic_low_conversion_products,
    get_product_quadrants,
    get_category_metrics,
    get_brand_metrics,
    get_price_band_metrics,
    get_high_traffic_low_revenue_categories,
)


def get_overview_kpis(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute("SELECT * FROM cloud_overview_kpis").fetchone()
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row))


def get_macro_funnel_stages(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM cloud_macro_funnel_stages ORDER BY stage_order").df()


def get_category_movers(con: duckdb.DuckDBPyConnection, n: int = 10) -> pd.DataFrame:
    return con.execute(
        "SELECT * FROM cloud_category_movers ORDER BY ABS(conversion_pct_change) DESC LIMIT ?", [n]
    ).df()


def get_new_vs_returning_weekly(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM cloud_new_vs_returning_weekly ORDER BY week_start").df()


def get_user_segments(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM cloud_user_segments ORDER BY total_revenue DESC").df()


def get_repeat_purchase_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM cloud_repeat_purchase_summary").df()


def get_price_conversion_by_category(con: duckdb.DuckDBPyConnection, category_code: str) -> pd.DataFrame:
    return con.execute(
        "SELECT price_band, viewing_session_products, overall_conversion_pct "
        "FROM cloud_category_price_band WHERE category_code = ?", [category_code]
    ).df()


def get_worst_cart_abandonment_categories(con: duckdb.DuckDBPyConnection, n: int = 5) -> pd.DataFrame:
    return con.execute(
        "SELECT * FROM cloud_category_abandonment ORDER BY cart_abandonment_pct DESC LIMIT ?", [n]
    ).df()


def get_filter_options(con: duckdb.DuckDBPyConnection) -> dict:
    categories = con.execute(
        "SELECT category_code FROM agg_category_metrics WHERE view_events >= 500 ORDER BY view_events DESC"
    ).df()["category_code"].tolist()
    brands = con.execute(
        "SELECT brand FROM agg_brand_metrics WHERE view_events >= 500 ORDER BY view_events DESC LIMIT 100"
    ).df()["brand"].tolist()
    return {"categories": categories, "brands": brands, "price_bands": PRICE_BAND_ORDER}


def get_dimension_funnel(con: duckdb.DuckDBPyConnection, dimension: str, value: str) -> dict:
    """Cloud replacement for the local get_filtered_funnel (which needs
    row-level session_product_funnel for arbitrary multi-filter + date-range
    combinations). Reads a single dimension's already-precomputed rate
    directly off the matching small agg_* table.
    """
    table = {"category_code": "agg_category_metrics", "brand": "agg_brand_metrics",
             "price_band": "agg_price_band_metrics"}[dimension]
    row = con.execute(
        f"SELECT viewing_sessions, view_to_cart_rate, cart_to_purchase_rate, overall_conversion_rate "
        f"FROM {table} WHERE {dimension} = ?", [value]
    ).fetchone()
    if row is None:
        return {"viewing_sessions": 0}
    viewing_sessions, v2c, c2p, overall = row
    return {
        "viewing_sessions": viewing_sessions,
        "view_to_cart_pct": None if v2c is None else v2c * 100,
        "overall_conversion_pct": None if overall is None else overall * 100,
        "cart_sessions": None if v2c is None else round(viewing_sessions * v2c),
        "purchase_sessions": None if overall is None else round(viewing_sessions * overall),
    }
