# Interview Preparation — ProductPulse

Every answer here is defensible from what's actually in this repo — no
invented numbers, no claimed causality, no overstated AI.

---

### 30-second explanation

"I built ProductPulse, a product analytics project on a real 110-million-event
e-commerce clickstream dataset from Kaggle. I used DuckDB and advanced SQL to
build a proper funnel — view, cart, purchase — at the session-product level,
not by naively dividing event counts, and surfaced where traffic doesn't
convert, where carts get abandoned, and how price and category relate to
conversion. It's a Streamlit dashboard with a rule-based 'ask a question'
feature on top, and every recommendation is tied to an actual number from the
data, not a made-up impact figure."

### 2-minute explanation

"The dataset is public — real e-commerce behavior data, ~110 million events
over two months, 5.3 million users, 207 thousand products. The core problem
I framed it around is what a product team actually needs: where do users drop
out of the purchase journey, and where's the revenue opportunity.

The engineering part I'm proudest of is the metric definitions. Most people
building something like this compute 'conversion rate' as purchase-events
divided by view-events — which is wrong, because one session can view the
same product five times. I built a table called `session_product_funnel` at
the (session, product) grain, with timestamps for first view/cart/purchase,
and every conversion rate is sessions-that-did-X divided by sessions-that-
did-the-prior-step, with the *and it happened after* condition enforced by
comparing timestamps.

I also had to solve a real infrastructure problem: this dataset is 14GB and I
built it on an 8GB-RAM machine with very little free disk. A naive `SELECT
DISTINCT` or a single `GROUP BY` over 110 million rows blew past available
disk during development — twice — so the final pipeline processes the two
heaviest aggregation stages one month at a time, checkpoints between stages,
and is resumable if it's interrupted. That's a real engineering tradeoff I
made and documented, not something I'm hiding.

On top of the SQL layer there's a Streamlit dashboard — funnel, product/
category/brand performance, price-band conversion, user segments, and an
insights page that generates its findings from live queries, not hardcoded
text. There's also a lightweight 'Ask ProductPulse' feature, but it's
deliberately rule-based, not an LLM writing SQL — I wanted every answer to be
traceable to a tested query so it literally cannot invent a number."

### Why did you choose this problem?

Funnel/conversion analysis is the single most common analytical task in a
product analyst role at a marketplace or delivery company — it's directly
what interviewers at places like Swiggy or Blinkit will ask about, and it
forces you to get metric definitions exactly right, which is the actual skill
being tested, not the charting.

### Why this dataset?

It's real behavioral data at meaningful scale (110M events), it has the exact
event types (view/cart/purchase) a funnel analysis needs, and it's public, so
I can be fully transparent that it's not proprietary company data — I say
that explicitly in the README rather than letting it be ambiguous.

### How did you define conversion?

At the (session, product) grain, using `session_product_funnel`: view-to-cart
= sessions that viewed product P and *subsequently* carted P, divided by
sessions that viewed P; cart-to-purchase and overall conversion follow the
same pattern. "Subsequently" is enforced by comparing `first_cart_time >=
first_view_time`, not just co-occurrence in the same session. I also compute
a looser session-level "macro funnel" (did the session view/cart/purchase
*anything*) for the Executive Overview KPI, and I'm explicit in the README
about which of the two a given number is using.

### Why session-level vs. event-level analysis?

Event-level ratios (purchase events ÷ view events) overcount and undercount
depending on how many times a user re-views or re-adds a product — they're
not a real conversion rate. Session-level (or session-product-level) is the
standard in product analytics because it answers the actual business
question: "of the people who showed interest, how many bought."

### What were the biggest findings?

See the README §10 "Key Findings" and the dashboard's Insights page — every
number there is a live query result (highest-traffic/lowest-converting
category, worst cart-abandonment category, price-band conversion spread).
I don't want to restate a number here that could drift from what the live
database says — pull it from the dashboard at interview time if asked for
specifics.

### How did you identify revenue leakage?

Two ways: (1) categories/products where % share of views is much higher than
% share of revenue (`agg_category_metrics.pct_of_total_views` vs.
`pct_of_total_revenue`) — a Pareto-style traffic/revenue mismatch; (2) high
cart-to-purchase abandonment on high cart-volume categories, which is
checkout-stage leakage specifically, distinct from discovery-stage leakage.

### What SQL techniques did you use?

CTEs (chained, multi-stage), `CASE WHEN` for bucketing (price bands, activity
segments), window functions — `LAG`/`LEAD` for period-over-period and
funnel-stage comparison, `ROW_NUMBER`/`RANK`/`DENSE_RANK` for
leaderboards and canonical-value resolution, `NTILE`/`PERCENT_RANK` for
quartile/decile segmentation, `arg_min`/`arg_max` for "value at first/last
event," `FILTER` for conditional aggregation, `QUALIFY` for post-window
filtering, rolling-window frames (`ROWS BETWEEN 6 PRECEDING AND CURRENT ROW`)
for 7-day averages, and RFM-style multi-dimension `NTILE` segmentation.

### Why did you choose these KPIs?

They map directly to the funnel stages that exist in the data (view/cart/
purchase) and to the two things a product team is actually accountable for:
conversion (are we turning interest into revenue) and abandonment (where is
committed interest — a cart add — being lost). I avoided KPIs the data can't
actually support (see "limitations" below).

### How would you validate your recommendation?

Every recommendation on the Insights page states the SQL-derived evidence
behind it explicitly (the finding IS the evidence). Before shipping a fix
based on one, I'd want to: (1) confirm the pattern holds over a longer window
than 61 days, since this is a snapshot; (2) segment by new vs. returning
users to rule out a mix-shift explanation; (3) check whether the
low-conversion products/categories share a confound (e.g., mostly one price
band, or mostly out of a specific date range) before assuming the category
itself is the lever.

### What would you A/B test?

See the dashboard's Insights & Recommendations page — each finding pairs
with a proposed experiment (hypothesis, control, treatment, primary/
secondary metrics, guardrails). Example: for the highest-traffic/lowest-
conversion category, test improved product ranking/relevance against the
current experience, with view-to-purchase conversion as the primary metric
and bounce rate as a guardrail. **I'm explicit that none of these experiments
have actually been run** — they're hypotheses generated from observational
data, not results.

### What are the limitations?

No `remove_from_cart` event (abandonment is a "never purchased" proxy), no
order-level fields so revenue is a line-item proxy, no demographic/device/
channel data so segmentation is purely behavioral, only a 61-day window so
"new vs. returning" and cohorts are bounded, and everything price-related is
an association, never a causal claim, because this is observational data.
I also disclose a hardware constraint: this was built on an 8GB-RAM machine
with limited free disk, which shaped the pipeline into a month-chunked,
resumable design — documented, not hidden.

### What would you build next?

Re-run the pipeline against a longer time window if one becomes available,
to check whether the two-month patterns hold; add the proposed A/B tests for
real if this were live production data; and extend the AI Analyst to use an
LLM for *phrasing* the explanation only (never for generating the SQL),
keeping the same whitelisted-function safety boundary.

### What did the AI component actually do?

It's a keyword-based intent router, not an LLM writing SQL. A question like
"which categories have high traffic but poor conversion?" matches a pattern,
which calls exactly one pre-approved, read-only function from
`analytics.py`, gets a real result back, and fills a template with those
exact numbers plus a cautious, labeled interpretation. If nothing matches, it
says so rather than guessing. I chose this over a "smarter"-looking LLM-SQL
approach specifically because it can't hallucinate a number — the number in
the answer is always the number the query returned.

### Why didn't you use ML?

Because the task is product analytics, not prediction. Nothing in this
project needed a model — funnel, cohort, and segmentation analysis are
fundamentally descriptive/diagnostic questions answerable with correctly
defined SQL. Adding an ML model would have been ML for its own sake, exactly
the kind of over-engineering the project brief explicitly ruled out.
