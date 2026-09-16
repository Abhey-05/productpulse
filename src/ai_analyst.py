"""
ai_analyst.py
--------------
PHASE 9 — "Ask ProductPulse": a lightweight, RULE-BASED analyst.

Architecture (deliberately simple, per project requirements — no
autonomous multi-agent framework, no free-form LLM SQL generation):

    user question
       -> intent matching (keyword rules against a fixed intent list)
       -> ONE approved, read-only analytics.py function (never raw
          user-constructed SQL)
       -> real numbers from the database
       -> a template filled in with those exact numbers
       -> a cautious, clearly-labeled product interpretation

Why rule-based instead of an LLM generating SQL:
  - The project rule is "never fabricate metrics." A template built
    from numbers that just came out of a tested, validated query
    cannot hallucinate a number. An LLM asked to "write SQL and
    interpret it" can silently produce a plausible-looking wrong
    query or wrong number, which is exactly the failure mode a
    product analyst must not ship.
  - It keeps the surface area auditable: every possible answer this
    tool can give traces to one of the whitelisted functions below,
    all of which are simple SELECTs against precomputed tables.
  - This is easy to defend in an interview: "I chose a constrained,
    inspectable design over an impressive-looking one."

If a question doesn't match a known intent, or asks for something the
dataset can't support (e.g. anything demographic, or true multi-year
retention), the tool says so explicitly rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

import analytics as A


@dataclass
class AnalystAnswer:
    intent: str
    summary: str          # the numeric finding, in plain language
    interpretation: str    # cautious "possible interpretation" (association, not causal)
    data: object            # a DataFrame or dict backing the answer, for the UI to render


UNSUPPORTED_MSG = (
    "I can't answer that from this dataset. ProductPulse only has event-level "
    "behavioral data (view/cart/purchase, product, category, brand, price, "
    "user/session ids) for Oct-Nov 2019 — there's no demographic, geographic, "
    "device, marketing-channel, or order-level (quantity/discount) data, and no "
    "data outside this 61-day window. Try asking about funnel drop-off, cart "
    "abandonment, high-traffic/low-conversion categories or products, price "
    "bands, brand performance, or week-over-week changes instead."
)


def _match(question: str, *patterns: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in patterns)


def ask(con: duckdb.DuckDBPyConnection, question: str) -> AnalystAnswer:
    q = question.strip()
    if not q:
        return AnalystAnswer("empty", "Please ask a question.", "", None)

    # --- Intent: funnel drop-off ---------------------------------------
    if _match(q, r"drop[\s-]?off", r"funnel", r"where.*(lose|losing).*users"):
        stages = A.get_macro_funnel_stages(con)
        worst = stages.iloc[stages["drop_off_pct"].fillna(0).idxmax()]
        summary = (
            f"The biggest drop-off in the macro funnel (View → Cart → Purchase, "
            f"session-level) is at the **{worst['stage']}** stage: "
            f"{worst['drop_off_pct']:.1f}% of sessions that reached the previous stage "
            f"did not continue. Full funnel: "
            + " → ".join(f"{r.stage} {r.sessions:,}" for r in stages.itertuples())
        )
        interpretation = (
            "This is an association from observational funnel data, not a diagnosed cause. "
            "A large drop between View and Cart is usually associated with discovery/relevance "
            "friction; a large drop between Cart and Purchase is usually associated with "
            "checkout-stage friction (price, shipping, payment, trust)."
        )
        return AnalystAnswer("funnel_dropoff", summary, interpretation, stages)

    # --- Intent: cart abandonment ---------------------------------------
    if _match(q, r"cart abandon", r"abandon.*cart", r"never (purchase|convert)"):
        worst = A.get_worst_cart_abandonment_categories(con, n=5)
        overview = A.get_overview_kpis(con)
        top = worst.iloc[0] if len(worst) else None
        summary = (
            f"Overall cart abandonment (carted a product, never purchased it) is "
            f"{overview['cart_abandonment_pct']:.1f}%. "
            + (f"The worst-affected category with meaningful volume is **{top['category_code']}** "
               f"at {top['cart_abandonment_pct']:.1f}% abandonment across "
               f"{top['carting_session_products']:,} cart adds." if top is not None else "")
        )
        interpretation = (
            "This dataset has no explicit 'removed from cart' event, so abandonment here means "
            "'added to cart, not purchased in the observed window' — it cannot separate an "
            "intentional removal from an item still pending purchase."
        )
        return AnalystAnswer("cart_abandonment", summary, interpretation, worst)

    # --- Intent: high traffic / low conversion --------------------------
    if _match(q, r"high traffic.*(low|poor) conversion", r"traffic but (poor|weak|low)",
              r"underperform", r"traffic.*no sale"):
        cats = A.get_high_traffic_low_revenue_categories(con, n=5)
        prods = A.get_high_traffic_low_conversion_products(con, n=5)
        top_cat = cats.iloc[0] if len(cats) else None
        summary = (
            (f"**{top_cat['category_code']}** draws {top_cat['pct_of_total_views']:.1f}% of all "
             f"product views but only {top_cat['pct_of_total_revenue']:.1f}% of revenue "
             f"(overall conversion {top_cat['overall_conversion_pct']:.2f}%). "
             if top_cat is not None else "")
            + f"At the product level, {len(prods)} products in the top traffic quartile sit in "
              f"the bottom quartile of conversion — see the table for specifics."
        )
        interpretation = (
            "High traffic with low conversion is associated with a mismatch somewhere between "
            "discovery and purchase intent — possibly pricing, product relevance, availability, "
            "search/ranking placement, or trust signals. This flags WHERE to investigate, not WHY."
        )
        return AnalystAnswer("high_traffic_low_conversion", summary, interpretation,
                              {"categories": cats, "products": prods})

    # --- Intent: what products should the team investigate --------------
    if _match(q, r"which products.*investigate", r"products.*(look at|review|check)",
              r"cart.*rarely purchased", r"added to cart.*(not|never) purchased"):
        prods = A.get_high_traffic_low_conversion_products(con, n=10)
        summary = (
            f"{len(prods)} products combine top-quartile traffic with bottom-quartile conversion. "
            f"Top of the list: product {prods.iloc[0]['product_id']} "
            f"({prods.iloc[0]['category_code']}, {prods.iloc[0]['brand']}) with "
            f"{int(prods.iloc[0]['viewing_sessions']):,} viewing sessions and only "
            f"{prods.iloc[0]['overall_conversion_rate'] * 100:.2f}% conversion."
            if len(prods) else "No products met the minimum sample size for this comparison."
        )
        interpretation = (
            "These are candidates for a product-team review of listing quality, price "
            "positioning, and availability — not a diagnosis of what's wrong with each one."
        )
        return AnalystAnswer("products_to_investigate", summary, interpretation, prods)

    # --- Intent: what changed vs last week / why did conversion fall ----
    if _match(q, r"why did conversion (fall|drop|decline)", r"what changed",
              r"compared (with|to) (the )?(previous|last) week", r"week[\s-]?over[\s-]?week"):
        weekly = A.get_weekly_trend_wow(con)
        movers = A.get_category_movers(con, n=5)
        last = weekly.iloc[-1]
        if last["revenue_wow_change_pct"] is not None and last["revenue_wow_change_pct"] == last["revenue_wow_change_pct"]:
            direction = "up" if last["revenue_wow_change_pct"] >= 0 else "down"
            summary = (
                f"In the most recent complete week ({last['week_start'].date()}), revenue was "
                f"{direction} {abs(last['revenue_wow_change_pct']):.1f}% vs. the prior week "
                f"(purchase rate of views: {last['purchase_rate_of_views_pct']:.3f}% vs. "
                f"{last['prev_purchase_rate_pct']:.3f}% the week before). "
            )
        else:
            summary = "Not enough prior-week data to compute a week-over-week change for the latest week. "
        if len(movers):
            top_mover = movers.iloc[0]
            summary += (
                f"The category with the largest Oct→Nov conversion shift was "
                f"**{top_mover['category_code']}** ({top_mover['oct_conversion_pct']:.2f}% → "
                f"{top_mover['nov_conversion_pct']:.2f}%)."
            )
        interpretation = (
            "This dataset spans two calendar months (Oct-Nov 2019), so 'week-over-week' here means "
            "movement within that fixed window, not a live, ongoing trend. Treat any single week's "
            "swing as a signal to investigate, not a confirmed cause."
        )
        return AnalystAnswer("wow_change", summary, interpretation, {"weekly": weekly, "movers": movers})

    # --- Intent: price / price band --------------------------------------
    if _match(q, r"\bprice\b", r"price band", r"cheaper", r"expensive"):
        bands = A.get_price_band_metrics(con)
        best = bands.loc[bands["overall_conversion_rate"].idxmax()]
        worst = bands.loc[bands["overall_conversion_rate"].idxmin()]
        summary = (
            f"Conversion varies by price band: **{best['price_band']}** converts best "
            f"({best['overall_conversion_rate'] * 100:.2f}%), **{worst['price_band']}** converts "
            f"worst ({worst['overall_conversion_rate'] * 100:.2f}%)."
        )
        interpretation = (
            "Price and conversion are ASSOCIATED here, not proven causal — cheaper items may "
            "convert better simply because they carry less purchase-decision friction, not because "
            "of price alone."
        )
        return AnalystAnswer("price_conversion", summary, interpretation, bands)

    # --- Intent: brand performance ----------------------------------------
    if _match(q, r"\bbrand\b"):
        brands = A.get_brand_metrics(con, n=10)
        top = brands.iloc[0]
        summary = (
            f"Top brand by revenue is **{top['brand']}** (${top['revenue']:,.0f} revenue, "
            f"{top['overall_conversion_rate'] * 100:.2f}% conversion, {int(top['view_events']):,} views)."
        )
        interpretation = "Brand performance here reflects observed demand and conversion, not brand equity or marketing spend (not present in this dataset)."
        return AnalystAnswer("brand_performance", summary, interpretation, brands)

    # --- Intent: category performance --------------------------------------
    if _match(q, r"\bcategory\b", r"categories"):
        cats = A.get_category_metrics(con)
        top = cats.sort_values("revenue", ascending=False).iloc[0]
        summary = (
            f"Top category by revenue is **{top['category_code']}** (${top['revenue']:,.0f}, "
            f"{top['overall_conversion_rate'] * 100:.2f}% conversion)."
        )
        interpretation = "Category rankings reflect this dataset's two-month window only."
        return AnalystAnswer("category_performance", summary, interpretation, cats)

    # --- No match ------------------------------------------------------
    # Explicitly distinguish "unsupported by the data" only when the
    # question clearly asks for something out of scope; otherwise say we
    # don't have a matching analysis rather than guessing.
    if _match(q, r"demographic", r"age", r"gender", r"location", r"country", r"device",
              r"marketing", r"channel", r"discount", r"quantity", r"shipping", r"ad spend"):
        return AnalystAnswer("unsupported", UNSUPPORTED_MSG, "", None)

    return AnalystAnswer(
        "no_match",
        "I don't have a predefined analysis that matches that question yet. "
        "Try: funnel drop-off, cart abandonment, high-traffic/low-conversion categories or "
        "products, price-band conversion, brand or category performance, or week-over-week change.",
        "",
        None,
    )


EXAMPLE_QUESTIONS = [
    "Where is the biggest funnel drop-off?",
    "Which categories have high traffic but poor conversion?",
    "Which products should the product team investigate?",
    "What changed compared with the previous week?",
    "How does conversion vary by price band?",
    "Which brands perform best?",
    "Where is cart abandonment highest?",
]
