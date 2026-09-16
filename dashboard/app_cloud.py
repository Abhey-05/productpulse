"""
dashboard/app_cloud.py
------------------------
Public Streamlit Cloud deployment entry point.

This is a variant of dashboard/app.py adapted to run against the small
(~18MB) data/cloud/productpulse_cloud.duckdb instead of the full local
12GB database (which is git-ignored and never committed — see
src/build_cloud_export.py for how the cloud DB is derived from it).

Only genuine differences from app.py:
  1. Connects to the small committed cloud DB via a relative path
     (no local/absolute paths — this must run in a clean container).
  2. Imports analytics_cloud instead of analytics; every cloud_*
     function it doesn't override is a straight passthrough to the
     original analytics.py logic (see analytics_cloud.py docstring).
  3. Ask ProductPulse (ai_analyst.py) is reused UNCHANGED — we alias
     analytics_cloud into sys.modules as "analytics" before importing
     it, so its internal `import analytics as A` resolves to the cloud
     module with zero duplication and zero edits to ai_analyst.py.
  4. Funnel Analysis's interactive filter is single-dimension
     (category OR brand OR price band, no date range) instead of the
     full local version's simultaneous multi-filter + date range,
     because that needs row-level session_product_funnel (69.8M rows)
     which isn't shippable to a public repo. Clearly labeled below.

The full-fidelity dashboard (dashboard/app.py) is untouched and still
the one described in the README for local use against the full dataset.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import duckdb
import analytics_cloud as A  # noqa: E402

# Alias so ai_analyst.py's hardcoded `import analytics as A` resolves to
# the cloud module instead — reuses ai_analyst.py completely unchanged.
sys.modules["analytics"] = A
import ai_analyst as AI  # noqa: E402

from theme import apply_plotly_theme, CUSTOM_CSS, CATEGORICAL, STATUS  # noqa: E402

st.set_page_config(page_title="ProductPulse (Demo)", page_icon="📈", layout="wide")
apply_plotly_theme()
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

CLOUD_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "cloud" / "productpulse_cloud.duckdb"


@st.cache_resource
def _connection():
    return duckdb.connect(str(CLOUD_DB_PATH), read_only=True)


con = _connection()

cached_product_quadrants = st.cache_data(show_spinner=False)(lambda **kw: A.get_product_quadrants(con, **kw))
cached_price_by_category = st.cache_data(show_spinner=False)(lambda cat: A.get_price_conversion_by_category(con, cat))
cached_high_traffic_low_conv = st.cache_data(show_spinner=False)(lambda **kw: A.get_high_traffic_low_conversion_products(con, **kw))

PAGES = [
    "Executive Overview",
    "Funnel Analysis",
    "Product & Category Performance",
    "User Behavior",
    "Price & Conversion",
    "Insights & Recommendations",
    "Ask ProductPulse (AI Analyst)",
]

with st.sidebar:
    st.markdown("### 📈 ProductPulse")
    st.caption("E-commerce Conversion & Product Analytics — Public Demo")
    st.info(
        "This is the public demo build, running against a small precomputed "
        "dataset (~18MB) instead of the full 110M-event / 12GB local database. "
        "Every number is still a real query result — see the "
        "[GitHub repo](https://github.com/Abhey-05/productpulse) for the full "
        "local version with the complete interactive filter set.",
        icon="ℹ️",
    )
    page = st.radio("Navigate", PAGES, label_visibility="collapsed")
    st.divider()
    st.caption(
        "Data: [eCommerce Behavior Data — Multi-Category Store](https://www.kaggle.com/datasets/mkechinov/"
        "ecommerce-behavior-data-from-multi-category-store) (Kaggle, public). "
        "Oct–Nov 2019. Observational data — associations shown are not causal claims."
    )


def fmt_compact(n) -> str:
    """Display-only compact formatting for large numbers in st.metric cards
    (e.g. 104331840 -> "104.3M") — never changes the underlying value used
    in any query or calculation, purely how it's rendered here."""
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:,.0f}"


# Friendly display names for raw column names in st.dataframe tables —
# label/formatting only, never renames the underlying DataFrame columns
# (chart code elsewhere still references the original column names).
COLUMN_LABELS = {
    "product_id": "Product ID", "category_code": "Category", "brand": "Brand",
    "avg_price": "Avg. Price", "view_events": "View Events", "cart_events": "Cart Events",
    "purchase_events": "Purchase Events", "viewing_sessions": "Viewing Sessions",
    "carting_sessions": "Carting Sessions", "purchasing_sessions": "Purchasing Sessions",
    "overall_conversion_rate": "Conversion Rate", "view_to_cart_rate": "View → Cart Conversion",
    "cart_to_purchase_rate": "Cart → Purchase Conversion", "cart_abandonment_rate": "Cart Abandonment Rate",
    "revenue": "Revenue", "n_products": "# Products", "pct_of_total_views": "% of Total Views",
    "pct_of_total_revenue": "% of Total Revenue", "price_band": "Price Band",
    "activity_segment": "Segment", "n_users": "# Users", "pct_of_users": "% of Users",
    "avg_events": "Avg. Events", "avg_sessions": "Avg. Sessions", "total_revenue": "Total Revenue",
}
# 0-1 fraction columns (agg_*_metrics tables) — Streamlit's format="percent"
# multiplies by 100 for display, so these must NOT already be pre-scaled.
PERCENT_COLUMNS = {"overall_conversion_rate", "view_to_cart_rate", "cart_to_purchase_rate",
                    "cart_abandonment_rate", "pct_of_total_views", "pct_of_total_revenue"}
# Already scaled to 0-100 by their own SQL (ROUND(100.0 * ..., 2)) — needs a
# literal "%" appended, NOT format="percent", or it would double-multiply
# (e.g. 77.71 would render as "7771.00%").
ALREADY_SCALED_PERCENT_COLUMNS = {"pct_of_users"}
CURRENCY_COLUMNS = {"revenue", "total_revenue", "avg_price"}


def col_cfg(columns):
    """Build a column_config dict with friendly labels (+ percent/currency
    formatting where applicable) for the given column names, for st.dataframe.
    Presentation only — never touches the underlying data."""
    cfg = {}
    for c in columns:
        label = COLUMN_LABELS.get(c, c)
        if c in PERCENT_COLUMNS:
            cfg[c] = st.column_config.NumberColumn(label, format="percent")
        elif c in ALREADY_SCALED_PERCENT_COLUMNS:
            cfg[c] = st.column_config.NumberColumn(label, format="%.2f%%")
        elif c in CURRENCY_COLUMNS:
            cfg[c] = st.column_config.NumberColumn(label, format="dollar")
        else:
            cfg[c] = st.column_config.Column(label)
    return cfg


def callout(label: str, title: str, body_html: str, tone: str = "default"):
    st.markdown(
        f"""<div class="pp-callout {tone}">
            <div class="pp-callout-label">{label}</div>
            <div class="pp-callout-title">{title}</div>
            <div class="pp-callout-body">{body_html}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# =======================================================================
# PAGE 1 — EXECUTIVE OVERVIEW
# =======================================================================
def page_overview():
    st.title("Executive Overview")
    kpis = A.get_overview_kpis(con)
    st.caption(f"{kpis['start_date']} → {kpis['end_date']} · {kpis['total_users']:,} users · "
               f"{kpis['total_sessions']:,} sessions")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Users", fmt_compact(kpis['total_users']),
              help=f"{kpis['total_users']:,} distinct users, all time in this window")
    c2.metric("Total Sessions", fmt_compact(kpis['total_sessions']),
              help=f"{kpis['total_sessions']:,} distinct sessions, all time in this window")
    c3.metric("Product View Events", fmt_compact(kpis['total_views']),
              help=f"{kpis['total_views']:,} raw view events — a session viewing the same product "
                   f"multiple times counts each time (see the funnel below for session-level counts)")
    c4.metric("Cart-Add Events", fmt_compact(kpis['total_carts']),
              help=f"{kpis['total_carts']:,} raw add-to-cart events (event count, not sessions)")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Purchase Events", fmt_compact(kpis['total_purchases']),
              help=f"{kpis['total_purchases']:,} raw purchase events — a session buying multiple "
                   f"products in one purchase logs one event per item (see the funnel below for "
                   f"purchasing sessions, a different, smaller number)")
    c6.metric("Purchase Conversion", f"{kpis['session_overall_conversion_pct']:.2f}%",
              help="Purchasing sessions ÷ viewing sessions (session-level macro funnel, View → Purchase)")
    c7.metric("Cart Abandonment", f"{kpis['cart_abandonment_pct']:.1f}%",
              help="Carted a product, never purchased it (session-product level)")
    c8.metric("Revenue (proxy)", f"${fmt_compact(kpis['total_revenue'])}",
              help=f"${kpis['total_revenue']:,.0f} — SUM(price) over purchase events, a line-item proxy, "
                   f"not a true order total (no quantity field exists)")

    st.markdown("## Funnel")
    stages = A.get_macro_funnel_stages(con)
    fig = go.Figure(go.Funnel(
        y=stages["stage"], x=stages["sessions"],
        textinfo="value+percent initial",
        marker=dict(color=CATEGORICAL[:3]),
        connector=dict(line=dict(color="#c3c2b7", width=1)),
    ))
    fig.update_layout(height=320, title="Session-level funnel: View → Cart → Purchase")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Chart percentages are relative to the View stage (the funnel's first stage) at every level.")
    fc1, fc2, fc3 = st.columns(3)
    fc1.metric("View → Cart", f"{kpis['session_view_to_cart_pct']:.2f}%",
               help="% of viewing sessions that also added a product to cart")
    fc2.metric("Cart → Purchase", f"{kpis['session_cart_to_purchase_pct']:.2f}%",
               help="% of carting sessions that went on to purchase (a different, smaller denominator "
                    "than the two figures either side of it)")
    fc3.metric("View → Purchase", f"{kpis['session_overall_conversion_pct']:.2f}%",
               help="% of viewing sessions that went on to purchase (same as Purchase Conversion above)")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.markdown("## Daily Trend")
        daily = A.get_daily_trend(con)
        fig = go.Figure()
        fig.add_bar(x=daily["event_date"], y=daily["n_purchases"], name="Purchases",
                    marker_color=CATEGORICAL[0], opacity=0.35)
        fig.add_scatter(x=daily["event_date"], y=daily["purchases_7d_avg"], name="7-day avg",
                         line=dict(color=CATEGORICAL[0], width=2))
        fig.update_layout(height=340, title="Daily purchases with 7-day rolling average",
                           legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        st.markdown("## Top Categories")
        top_cats = A.get_top_categories(con, n=8, by="revenue")
        fig = px.bar(top_cats.sort_values("revenue"), x="revenue", y="category_code",
                     orientation="h", color_discrete_sequence=[CATEGORICAL[0]])
        fig.update_layout(height=340, title="By revenue", yaxis_title="", xaxis_title="Revenue ($)")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("## Key Insight")
    ht = A.get_high_traffic_low_revenue_categories(con, n=1).iloc[0]
    callout(
        "Insight 01", f"{ht['category_code']} pulls disproportionate traffic relative to revenue",
        f"This category drives <b>{ht['pct_of_total_views']:.1f}%</b> of all product views but only "
        f"<b>{ht['pct_of_total_revenue']:.1f}%</b> of revenue, converting at "
        f"<b>{ht['overall_conversion_pct']:.2f}%</b>. See the Insights & Recommendations page for the "
        f"full breakdown and suggested investigation.",
        tone="serious",
    )


# =======================================================================
# PAGE 2 — FUNNEL ANALYSIS (single-dimension filter — see module docstring)
# =======================================================================
def page_funnel():
    st.title("Funnel Analysis")
    st.caption("View → Cart → Purchase, computed at the (session, product) grain — "
               "did a session view THIS product and subsequently cart/purchase it.")
    st.caption("🔎 Demo build: filter by ONE dimension at a time (no combined multi-filter "
               "or date range — that needs the full 69.8M-row local table). See the full "
               "local dashboard for the complete interactive filter set.")
    st.caption("View → Cart and View → Purchase are both % of viewing sessions. "
               "Cart → Purchase is % of carting sessions (a different, smaller denominator).")

    opts = A.get_filter_options(con)
    dim_label = st.radio("Filter by", ["Category", "Brand", "Price band"], horizontal=True)
    dim_map = {"Category": ("category_code", opts["categories"]),
               "Brand": ("brand", opts["brands"]),
               "Price band": ("price_band", opts["price_bands"])}
    dim_col, dim_values = dim_map[dim_label]
    value = st.selectbox(dim_label, dim_values)

    result = A.get_dimension_funnel(con, dim_col, value)

    if not result["viewing_sessions"]:
        st.warning("No data matches this filter.")
        return

    cart_to_purchase_pct = result.get("cart_to_purchase_pct")

    st.caption(f"Metrics below are for **{dim_label}: {value}** only, not the whole dataset — "
               f"that's why they're smaller than the Executive Overview totals.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Viewing sessions", fmt_compact(result['viewing_sessions']), help=f"{result['viewing_sessions']:,}")
    c2.metric("View → Cart", f"{result['view_to_cart_pct']:.2f}%" if result['view_to_cart_pct'] is not None else "—",
              help="Viewing sessions that also added this to cart, ÷ all viewing sessions")
    c3.metric("Cart → Purchase", f"{cart_to_purchase_pct:.2f}%" if cart_to_purchase_pct is not None else "—",
              help="Carting sessions that went on to purchase, ÷ all carting sessions")
    c4.metric("View → Purchase", f"{result['overall_conversion_pct']:.2f}%" if result['overall_conversion_pct'] is not None else "—",
              help="Viewing sessions that went on to purchase, ÷ all viewing sessions (overall conversion)")

    funnel_df = pd.DataFrame({
        "stage": ["Viewed", "Carted", "Purchased"],
        "count": [result["viewing_sessions"], result.get("cart_sessions") or 0, result.get("purchase_sessions") or 0],
    })
    fig = go.Figure(go.Funnel(
        y=funnel_df["stage"], x=funnel_df["count"], textinfo="value+percent initial",
        marker=dict(color=CATEGORICAL[:3]),
    ))
    fig.update_layout(height=340, title=f"Funnel for {dim_label.lower()} = {value}")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("## Cart Abandonment by Category (unfiltered, top 15)")
    abandon = A.get_worst_cart_abandonment_categories(con, n=15)
    fig = px.bar(abandon.sort_values("cart_abandonment_pct"), x="cart_abandonment_pct", y="category_code",
                 orientation="h", color_discrete_sequence=[STATUS["serious"]])
    fig.update_layout(height=420, xaxis_title="Cart abandonment %", yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


# =======================================================================
# PAGE 3 — PRODUCT & CATEGORY PERFORMANCE
# =======================================================================
def page_product_category():
    st.title("Product & Category Performance")

    tab1, tab2, tab3 = st.tabs(["Products", "Categories", "Brands"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Top Products by Views")
            top_views = A.get_top_products(con, by="views", n=15).fillna(
                {"category_code": "Unknown category", "brand": "Unknown brand"})
            cols = ["product_id", "category_code", "brand", "view_events",
                    "purchase_events", "overall_conversion_rate", "revenue"]
            st.dataframe(top_views[cols], use_container_width=True, hide_index=True,
                         column_config=col_cfg(cols))
        with col2:
            st.markdown("### Top Products by Purchases")
            top_purch = A.get_top_products(con, by="purchases", n=15).fillna(
                {"category_code": "Unknown category", "brand": "Unknown brand"})
            cols = ["product_id", "category_code", "brand", "purchase_events",
                    "overall_conversion_rate", "revenue"]
            st.dataframe(top_purch[cols], use_container_width=True, hide_index=True,
                         column_config=col_cfg(cols))

        st.markdown("### Traffic vs. Conversion (bubble = revenue)")
        st.caption("Quadrants split at the dataset median viewing sessions and median conversion rate, "
                   "for products with ≥50 viewing sessions: **Star** = above-median traffic and "
                   "conversion · **High-traffic underperformer** = above-median traffic, below-median "
                   "conversion · **Hidden gem** = below-median traffic, above-median conversion · "
                   "**Low priority** = below-median on both.")
        quad = cached_product_quadrants(min_sessions=50).fillna(
            {"category_code": "Unknown category", "brand": "Unknown brand"})
        quad_colors = {"Star": CATEGORICAL[2], "High-traffic underperformer": STATUS["serious"],
                       "Hidden gem": CATEGORICAL[0], "Low priority": "#c3c2b7"}
        fig = px.scatter(
            quad, x="viewing_sessions", y="overall_conversion_rate", size="revenue", color="quadrant",
            color_discrete_map=quad_colors, hover_data=["product_id", "category_code", "brand"],
            labels={"viewing_sessions": "Viewing Sessions", "overall_conversion_rate": "Conversion Rate",
                    "product_id": "Product ID", "category_code": "Category", "brand": "Brand",
                    "revenue": "Revenue", "quadrant": "Quadrant"},
            log_x=True,
        )
        fig.update_layout(height=480, xaxis_title="Viewing sessions (log scale)", yaxis_title="Overall conversion rate")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### High-Traffic / Low-Conversion Products")
        st.caption("Top traffic quartile, bottom conversion quartile, ≥200 viewing sessions.")
        ht_lc = cached_high_traffic_low_conv(n=20).fillna(
            {"category_code": "Unknown category", "brand": "Unknown brand"})
        st.dataframe(ht_lc, use_container_width=True, hide_index=True, column_config=col_cfg(ht_lc.columns))

    with tab2:
        cats = A.get_category_metrics(con)
        st.markdown("### Category Conversion & Revenue")
        fig = px.scatter(
            cats, x="view_events", y="overall_conversion_rate", size="revenue",
            hover_data=["category_code"], text="category_code",
            labels={"view_events": "View Events", "overall_conversion_rate": "Conversion Rate",
                    "category_code": "Category", "revenue": "Revenue"},
            color_discrete_sequence=[CATEGORICAL[0]], log_x=True,
        )
        fig.update_traces(textposition="top center", textfont=dict(size=9))
        fig.update_layout(height=520, xaxis_title="Views (log scale)", yaxis_title="Overall conversion rate")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
        cat_cols = ["category_code", "n_products", "view_events", "purchase_events",
                    "overall_conversion_rate", "revenue", "pct_of_total_views", "pct_of_total_revenue"]
        st.dataframe(cats[cat_cols], use_container_width=True, hide_index=True, column_config=col_cfg(cat_cols))

    with tab3:
        st.markdown("### Brand Performance (top 30 by revenue)")
        brands = A.get_brand_metrics(con, n=30)
        fig = px.bar(brands.sort_values("revenue").tail(20), x="revenue", y="brand", orientation="h",
                     color_discrete_sequence=[CATEGORICAL[0]])
        fig.update_layout(height=560, xaxis_title="Revenue ($)", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(brands, use_container_width=True, hide_index=True, column_config=col_cfg(brands.columns))


# =======================================================================
# PAGE 4 — USER BEHAVIOR
# =======================================================================
def page_user_behavior():
    st.title("User Behavior")

    segments = A.get_user_segments(con)
    c1, c2 = st.columns([1, 1])
    with c1:
        fig = px.pie(segments, values="n_users", names="activity_segment",
                     color_discrete_sequence=CATEGORICAL, hole=0.45)
        fig.update_layout(height=360, title="Users by activity segment")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(segments.sort_values("total_revenue"), x="total_revenue", y="activity_segment",
                     orientation="h", color_discrete_sequence=[CATEGORICAL[0]])
        fig.update_layout(height=360, title="Revenue by segment", xaxis_title="Revenue ($)", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(segments, use_container_width=True, hide_index=True, column_config=col_cfg(segments.columns))

    st.markdown("## Repeat Purchase Behavior")
    repeat = A.get_repeat_purchase_summary(con)
    repeat["is_repeat_purchaser"] = repeat["is_repeat_purchaser"].map(
        {True: "Repeat buyer", False: "One-time buyer"})
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(repeat, x="is_repeat_purchaser", y="n_purchasers", color_discrete_sequence=[CATEGORICAL[0]])
        fig.update_layout(height=320, title="Purchasers: repeat vs. one-time",
                           xaxis_title="Repeat purchaser (≥2 distinct purchase days)")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.pie(repeat, values="total_revenue", names="is_repeat_purchaser",
                     color_discrete_sequence=CATEGORICAL, hole=0.45)
        fig.update_layout(height=320, title="Revenue share: repeat vs. one-time")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("## New vs. Returning Users (weekly, within observed window)")
    st.caption("'New' = first-ever event in this dataset falls in that week. Cannot detect activity before Oct 1, 2019.")
    nvr = A.get_new_vs_returning_weekly(con)
    fig = go.Figure()
    fig.add_bar(x=nvr["week_start"], y=nvr["new_users"], name="New", marker_color=CATEGORICAL[0])
    fig.add_bar(x=nvr["week_start"], y=nvr["returning_users"], name="Returning", marker_color=CATEGORICAL[2])
    fig.update_layout(barmode="stack", height=360, legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)


# =======================================================================
# PAGE 5 — PRICE & CONVERSION
# =======================================================================
def page_price():
    st.title("Price & Conversion")
    st.caption("Associations only — this is observational data, not an experiment. "
               "No causal claims are made about price driving conversion.")

    bands = A.get_price_band_metrics(con)
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(bands, x="price_band", y="overall_conversion_rate", color_discrete_sequence=[CATEGORICAL[0]])
        fig.update_layout(height=380, title="Overall conversion by price band", yaxis_tickformat=".1%",
                           xaxis_title="Price Band", yaxis_title="Overall Conversion Rate")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(bands, x="price_band", y="cart_abandonment_rate", color_discrete_sequence=[STATUS["serious"]])
        fig.update_layout(height=380, title="Cart abandonment by price band", yaxis_tickformat=".1%",
                           xaxis_title="Price Band", yaxis_title="Cart Abandonment Rate")
        st.plotly_chart(fig, use_container_width=True)

    price_cols = ["price_band", "n_products", "view_events", "cart_events", "purchase_events",
                  "view_to_cart_rate", "cart_to_purchase_rate", "overall_conversion_rate",
                  "cart_abandonment_rate", "revenue"]
    st.dataframe(bands[price_cols], use_container_width=True, hide_index=True, column_config=col_cfg(price_cols))

    st.markdown("## Drill Down: Price Conversion Within a Category")
    opts = A.get_filter_options(con)
    category = st.selectbox("Category", opts["categories"])
    if category:
        detail = cached_price_by_category(category)
        if len(detail):
            fig = px.bar(detail, x="price_band", y="overall_conversion_pct", color_discrete_sequence=[CATEGORICAL[0]])
            fig.update_layout(height=360, title=f"{category}: conversion by price band")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough volume in this category to break down by price band.")


# =======================================================================
# PAGE 6 — INSIGHTS & RECOMMENDATIONS
# =======================================================================
def page_insights():
    st.title("Insights & Recommendations")
    st.caption("Every number below is pulled live from the database — nothing here is invented.")

    ht_cats = A.get_high_traffic_low_revenue_categories(con, n=3)
    abandon_cats = A.get_worst_cart_abandonment_categories(con, n=3)
    bands = A.get_price_band_metrics(con)
    ht_products = cached_high_traffic_low_conv(n=5)

    n = 1
    for _, row in ht_cats.iterrows():
        callout(
            f"Insight {n:02d}", f"High traffic, low conversion — {row['category_code']}",
            f"Category <b>{row['category_code']}</b> generates <b>{row['pct_of_total_views']:.1f}%</b> of "
            f"all product views but only <b>{row['pct_of_total_revenue']:.1f}%</b> of revenue "
            f"(overall conversion {row['overall_conversion_pct']:.2f}%).<br><br>"
            f"<b>Possible interpretation:</b> the category attracts substantial discovery traffic but "
            f"has weak downstream conversion.<br>"
            f"<b>Product question:</b> is the issue pricing, product relevance, availability, ranking, "
            f"or checkout friction?<br>"
            f"<b>Recommended investigation:</b> product-level conversion and price distribution within "
            f"{row['category_code']} (see Price & Conversion page drill-down).",
            tone="serious",
        )
        n += 1

    for _, row in abandon_cats.iterrows():
        callout(
            f"Insight {n:02d}", f"High cart abandonment — {row['category_code']}",
            f"Category <b>{row['category_code']}</b> has a <b>{row['cart_abandonment_pct']:.1f}%</b> cart "
            f"abandonment rate across {row['carting_session_products']:,} cart adds.<br><br>"
            f"<b>Possible interpretation:</b> users reach purchase intent (adding to cart) but do not "
            f"complete — consistent with checkout-stage friction (price shock, shipping cost, payment "
            f"options, trust) rather than a discovery problem.<br>"
            f"<b>Recommended investigation:</b> checkout funnel instrumentation and price sensitivity "
            f"within this category.",
            tone="critical",
        )
        n += 1

    worst_band = bands.loc[bands["overall_conversion_rate"].idxmin()]
    best_band = bands.loc[bands["overall_conversion_rate"].idxmax()]
    callout(
        f"Insight {n:02d}", "Conversion varies materially by price band",
        f"<b>{best_band['price_band']}</b> converts at <b>{best_band['overall_conversion_rate']*100:.2f}%</b> "
        f"vs. <b>{worst_band['price_band']}</b> at <b>{worst_band['overall_conversion_rate']*100:.2f}%</b>.<br><br>"
        f"<b>Possible interpretation:</b> higher-priced items are associated with more deliberation and "
        f"lower conversion — an association, not evidence that price alone causes the gap.<br>"
        f"<b>Recommended investigation:</b> compare cart abandonment and session depth across bands to "
        f"see whether friction concentrates at checkout for higher-price items.",
    )
    n += 1

    if len(ht_products):
        p = ht_products.iloc[0]
        callout(
            f"Insight {n:02d}", "Specific products worth a listing review",
            f"Product <b>{p['product_id']}</b> ({p['category_code']}, {p['brand']}) has "
            f"{int(p['viewing_sessions']):,} viewing sessions but only "
            f"{p['overall_conversion_rate']*100:.2f}% conversion — {len(ht_products)} similar products "
            f"identified in total (top traffic quartile, bottom conversion quartile).<br><br>"
            f"<b>Recommended investigation:</b> listing quality, price positioning, and stock availability "
            f"for these specific SKUs.",
        )
        n += 1

    st.markdown("## Product Recommendations")
    st.markdown(f"""
| Finding | Evidence | Hypothesis | Suggested Action | Metric to Monitor |
|---|---|---|---|---|
| High-traffic categories underconvert | {ht_cats.iloc[0]['category_code']}: {ht_cats.iloc[0]['pct_of_total_views']:.1f}% of views, {ht_cats.iloc[0]['pct_of_total_revenue']:.1f}% of revenue | Discovery works; something downstream (relevance/price/ranking) doesn't | Investigate product relevance, pricing, availability & checkout for this category | View-to-purchase conversion |
| Cart abandonment concentrated in specific categories | {abandon_cats.iloc[0]['category_code']}: {abandon_cats.iloc[0]['cart_abandonment_pct']:.1f}% abandonment | Checkout-stage friction (price shock, shipping, payment) | Audit checkout flow and price presentation for this category | Cart-to-purchase conversion |
| Conversion drops at higher price bands | {worst_band['price_band']} converts at {worst_band['overall_conversion_rate']*100:.2f}% | Price is a friction point without adequate value framing | A/B test value messaging / financing options for high-price items | Overall conversion rate by price band |
| Specific SKUs combine high traffic + low conversion | {len(ht_products)} products flagged | Listing-level issues (image, description, price, stock) rather than category-wide | Manual listing review + price-competitiveness check for flagged SKUs | Product-level conversion rate |
""")

    st.markdown("## Experiment Proposals (hypotheses — not run)")
    st.info(
        "**Important:** these are proposed A/B tests based on the observed patterns above. "
        "No experiment has actually been run — this section is a hypothesis, not a result."
    )
    st.markdown(f"""
**Experiment 1 — Improve discovery/ranking for {ht_cats.iloc[0]['category_code']}**
- **Hypothesis:** improving product relevance/ranking for high-traffic, low-conversion categories increases purchase conversion.
- **Control:** existing ranking/discovery experience.
- **Treatment:** improved ranking/relevance signals for this category.
- **Primary metric:** view-to-purchase conversion.
- **Secondary metrics:** cart conversion, revenue/session.
- **Guardrails:** bounce rate, average session depth.

**Experiment 2 — Reduce checkout friction for {abandon_cats.iloc[0]['category_code']}**
- **Hypothesis:** simplifying checkout (fewer steps, clearer shipping cost, more payment options) reduces cart abandonment.
- **Control:** existing checkout flow.
- **Treatment:** streamlined checkout flow.
- **Primary metric:** cart-to-purchase conversion.
- **Secondary metrics:** average order value, time-to-purchase.
- **Guardrails:** overall conversion rate (make sure the change doesn't create new drop-off elsewhere).
""")


# =======================================================================
# PAGE 7 — ASK PRODUCTPULSE (AI ANALYST)
# =======================================================================
def page_ai_analyst():
    st.title("Ask ProductPulse")
    st.caption(
        "A rule-based analyst: your question is matched to one of a fixed set of approved, "
        "read-only SQL analyses — never free-form generated SQL — so every number is guaranteed "
        "to come straight from the database, never invented."
    )

    with st.expander("Example questions"):
        for ex in AI.EXAMPLE_QUESTIONS:
            st.markdown(f"- {ex}")

    question = st.text_input("Your question", placeholder="e.g. Which categories have high traffic but poor conversion?")
    if st.button("Ask", type="primary") or question:
        if question:
            answer = AI.ask(con, question)
            st.markdown(f"**{answer.summary}**")
            if answer.interpretation:
                st.caption(f"⚠️ {answer.interpretation}")
            if isinstance(answer.data, pd.DataFrame) and len(answer.data):
                st.dataframe(answer.data, use_container_width=True, hide_index=True)
            elif isinstance(answer.data, dict):
                for key, df in answer.data.items():
                    if isinstance(df, pd.DataFrame) and len(df):
                        st.markdown(f"**{key.title()}**")
                        st.dataframe(df, use_container_width=True, hide_index=True)


PAGE_FUNCS = {
    "Executive Overview": page_overview,
    "Funnel Analysis": page_funnel,
    "Product & Category Performance": page_product_category,
    "User Behavior": page_user_behavior,
    "Price & Conversion": page_price,
    "Insights & Recommendations": page_insights,
    "Ask ProductPulse (AI Analyst)": page_ai_analyst,
}

PAGE_FUNCS[page]()
