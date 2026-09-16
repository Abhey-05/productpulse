"""
data_cleaning.py
-----------------
PHASE 3 — Build the full ProductPulse analytical database from the raw
Kaggle CSVs, following the cleaning decisions documented in
docs/DATA_QUALITY_REPORT.md and the schema documented in sql/schema.sql.

Pipeline stages (each is a CREATE OR REPLACE TABLE ... AS SELECT run
directly in DuckDB so the ~110M raw rows never pass through Python):

  1. fact_events            - dedup + derived columns
  2. dim_product             - canonical brand/category per product (mode)
  3. dim_category            - category rollup
  4. session_summary         - session-level (macro) funnel
  5. session_product_funnel  - session x product funnel (core table)
  6. agg_daily_funnel        - daily trend rollup
  7. agg_product_metrics     - product-level conversion & revenue
  8. agg_category_metrics    - category-level conversion & revenue
  9. agg_brand_metrics       - brand-level conversion & revenue
 10. agg_price_band_metrics  - price-band conversion & abandonment
 11. agg_user_metrics        - user-level activity & segments

Row counts before/after are logged to docs/pipeline_run_log.md so any
data loss at any stage is visible and intentional (never silent).
"""

import shutil
import time
from pathlib import Path

import duckdb

# Safety threshold: abort a stage rather than risk filling the disk.
# This machine has a small, shared APFS free pool — better to fail loud
# and early than crash mid-write.
MIN_FREE_GB = 2.5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "processed" / "productpulse.duckdb"
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

OCT_CSV = RAW_DIR / "2019-Oct.csv"
NOV_CSV = RAW_DIR / "2019-Nov.csv"

PRICE_BAND_CASE = """
    CASE
        WHEN price = 0 THEN 'Free ($0)'
        WHEN price <= 25 THEN '$0-25'
        WHEN price <= 50 THEN '$25-50'
        WHEN price <= 100 THEN '$50-100'
        WHEN price <= 250 THEN '$100-250'
        WHEN price <= 500 THEN '$250-500'
        WHEN price <= 1000 THEN '$500-1000'
        ELSE '$1000+'
    END
"""

log_lines = []


def log(msg=""):
    print(msg, flush=True)
    log_lines.append(msg)


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 ** 3)


def check_disk(label: str):
    g = free_gb(PROJECT_ROOT)
    log(f"  [disk check @ {label}] {g:.2f} GB free")
    if g < MIN_FREE_GB:
        raise RuntimeError(
            f"Aborting before '{label}': only {g:.2f} GB free (< {MIN_FREE_GB} GB safety floor). "
            f"Free up disk space and re-run — the pipeline is idempotent (CREATE OR REPLACE)."
        )


def table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main' AND table_name = ?",
        [name],
    ).fetchone()[0] > 0


def step(con, name, sql, count_table=None, skip_if_exists: str | None = None):
    """skip_if_exists: a table name — if it already exists (from a prior,
    interrupted run), skip re-running this stage entirely. Makes the
    pipeline resumable after a crash/kill without redoing expensive work."""
    if skip_if_exists and table_exists(con, skip_if_exists):
        n = con.execute(f"SELECT COUNT(*) FROM {skip_if_exists}").fetchone()[0]
        log(f"\n### {name}\n- SKIPPED (table `{skip_if_exists}` already exists, {n:,} rows) — resuming pipeline")
        return
    check_disk(name)
    t0 = time.time()
    log(f"\n### {name}")
    con.execute(sql)
    con.execute("CHECKPOINT")
    elapsed = time.time() - t0
    if count_table:
        n = con.execute(f"SELECT COUNT(*) FROM {count_table}").fetchone()[0]
        log(f"- rows in `{count_table}`: {n:,}")
    log(f"- elapsed: {elapsed:.1f}s")
    log(f"- disk free after: {free_gb(PROJECT_ROOT):.2f} GB")


def main():
    t_start = time.time()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    # Conservative limits: this box has 8GB RAM and a small shared APFS
    # free pool. Fewer threads + a lower memory ceiling means DuckDB
    # spills earlier and more gradually instead of building one huge
    # hash table and then blowing past available RAM/disk at once.
    # Lowered from threads=4/memory_limit=6GB after a background run got killed
    # by the OS for low system memory — this 8GB-RAM machine had Chrome and
    # other apps already holding most of physical RAM, leaving too little
    # headroom for DuckDB's 6GB ceiling to actually be safe in practice.
    con.execute("PRAGMA threads=2")
    con.execute("PRAGMA memory_limit='3GB'")
    con.execute("PRAGMA temp_directory='" + str((DB_PATH.parent / 'duckdb_tmp')) + "'")
    # Lets large aggregations stream results out instead of buffering to
    # preserve input order — meaningfully lowers peak memory/temp-disk
    # for the big GROUP BYs below, at no cost since row order doesn't
    # matter for any table here.
    con.execute("PRAGMA preserve_insertion_order=false")

    log("# ProductPulse — Pipeline Build Log")
    log(f"\nDatabase: {DB_PATH}")

    raw_rows_oct = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{OCT_CSV}')").fetchone()[0]
    raw_rows_nov = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{NOV_CSV}')").fetchone()[0]
    log(f"\nRaw source rows: Oct={raw_rows_oct:,}, Nov={raw_rows_nov:,}, "
        f"Total={raw_rows_oct + raw_rows_nov:,}")

    # ---------------------------------------------------------------
    # 1. fact_events — dedup + derived columns
    # ---------------------------------------------------------------
    # Built ONE MONTH AT A TIME (CREATE then INSERT) rather than as a
    # single DISTINCT over all 110M rows. A global DISTINCT here forces
    # a hash table sized close to the full row count (almost every row
    # is unique), which blew past this machine's disk headroom in an
    # earlier run. Deduping within each month first, then combining,
    # cuts peak memory/temp-disk roughly in half per pass and still
    # catches the documented duplicates (same-batch logging glitches;
    # see DATA_QUALITY_REPORT.md — cross-month duplicates, if any, are
    # a negligible edge case we accept and disclose).
    def fact_events_select(csv_path):
        return f"""
            WITH raw AS (
                SELECT DISTINCT
                    event_time, event_type, product_id, category_id,
                    NULLIF(category_code, '') AS category_code,
                    NULLIF(brand, '') AS brand,
                    price, user_id, user_session
                FROM read_csv_auto('{csv_path}', timestampformat='%Y-%m-%d %H:%M:%S UTC')
            )
            SELECT
                event_time,
                CAST(event_time AS DATE) AS event_date,
                CAST(EXTRACT(HOUR FROM event_time) AS TINYINT) AS event_hour,
                event_type, product_id, category_id, category_code,
                split_part(category_code, '.', 1) AS category_l1,
                NULLIF(split_part(category_code, '.', 2), '') AS category_l2,
                brand, price,
                {PRICE_BAND_CASE} AS price_band,
                user_id, user_session
            FROM raw
        """

    if table_exists(con, "fact_events"):
        total_rows = con.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0]
        log(f"\n### 1. fact_events\n- SKIPPED (already exists, {total_rows:,} rows) — resuming pipeline")
    else:
        check_disk("1a. fact_events — Oct")
        t0 = time.time()
        log("\n### 1a. fact_events — Oct (dedup + derived columns)")
        con.execute(f"CREATE OR REPLACE TABLE fact_events AS {fact_events_select(OCT_CSV)}")
        log(f"- rows after Oct: {con.execute('SELECT COUNT(*) FROM fact_events').fetchone()[0]:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")
        con.execute("CHECKPOINT")

        check_disk("1b. fact_events — Nov")
        t0 = time.time()
        log("\n### 1b. fact_events — Nov (dedup + derived columns, appended)")
        con.execute(f"INSERT INTO fact_events {fact_events_select(NOV_CSV)}")
        total_rows = con.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0]
        log(f"- rows after Oct+Nov: {total_rows:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")
        log(f"- duplicate rows removed (within-month): {raw_rows_oct + raw_rows_nov - total_rows:,}")
        con.execute("CHECKPOINT")

    # ---------------------------------------------------------------
    # 2. dim_product — canonical brand/category per product (mode)
    # ---------------------------------------------------------------
    step(con, "2. dim_product (canonical attributes per product)", """
        CREATE OR REPLACE TABLE dim_product AS
        WITH combo_counts AS (
            SELECT product_id, category_id, category_code, brand, COUNT(*) AS n,
                   ROW_NUMBER() OVER (
                       PARTITION BY product_id ORDER BY COUNT(*) DESC
                   ) AS rn
            FROM fact_events
            GROUP BY product_id, category_id, category_code, brand
        ),
        canonical AS (
            SELECT product_id, category_id, category_code, brand
            FROM combo_counts WHERE rn = 1
        ),
        price_stats AS (
            SELECT product_id,
                   AVG(price) AS avg_price,
                   MIN(price) AS min_price,
                   MAX(price) AS max_price,
                   MIN(event_date) AS first_seen_date,
                   MAX(event_date) AS last_seen_date
            FROM fact_events
            GROUP BY product_id
        )
        SELECT
            c.product_id,
            c.category_id,
            c.category_code,
            split_part(c.category_code, '.', 1) AS category_l1,
            NULLIF(split_part(c.category_code, '.', 2), '') AS category_l2,
            c.brand,
            c.category_code IS NOT NULL AS is_categorized,
            c.brand IS NOT NULL AS is_branded,
            p.avg_price, p.min_price, p.max_price,
            p.first_seen_date, p.last_seen_date
        FROM canonical c
        JOIN price_stats p USING (product_id)
    """, count_table="dim_product", skip_if_exists="dim_product")

    # ---------------------------------------------------------------
    # 3. dim_category
    # ---------------------------------------------------------------
    step(con, "3. dim_category", """
        CREATE OR REPLACE TABLE dim_category AS
        SELECT
            category_code,
            category_l1,
            category_l2,
            COUNT(DISTINCT product_id) AS n_products,
            COUNT(DISTINCT brand) AS n_brands
        FROM dim_product
        WHERE category_code IS NOT NULL
        GROUP BY category_code, category_l1, category_l2
    """, count_table="dim_category", skip_if_exists="dim_category")

    # ---------------------------------------------------------------
    # 4. session_summary — macro/session-level funnel
    # ---------------------------------------------------------------
    # Built one month at a time (like fact_events): grouping 109.8M rows
    # by user_session (23M distinct groups) in one pass needs a hash
    # table sized to millions of high-cardinality (UUID-keyed) groups,
    # which spiked temp-disk usage dangerously on this machine's tight
    # free-space budget. Splitting by month roughly halves peak size.
    # A session that happens to straddle Oct 31 -> Nov 1 midnight UTC
    # would be split into two rows here; this is a negligible, disclosed
    # edge case (sessions are typically minutes long, not hours).
    def session_summary_select(date_filter):
        return f"""
            SELECT
                user_session,
                arg_max(user_id, event_time) AS user_id,
                COUNT(DISTINCT user_id) AS n_distinct_users,
                COUNT(DISTINCT user_id) <= 1 AS is_valid_session,
                MIN(event_time) AS session_start,
                MAX(event_time) AS session_end,
                EXTRACT(EPOCH FROM (MAX(event_time) - MIN(event_time))) AS session_duration_s,
                COUNT(*) AS n_events,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS n_views,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS n_carts,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS n_purchases,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) > 0 AS has_view,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) > 0 AS has_cart,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) > 0 AS has_purchase,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue,
                CAST(MIN(event_time) AS DATE) AS session_date
            FROM fact_events
            WHERE {date_filter}
            GROUP BY user_session
        """

    oct_filter = "event_date < '2019-11-01'"
    nov_filter = "event_date >= '2019-11-01'"
    # Nov split into DAILY sub-chunks for the heaviest stage (5b below) —
    # a full-month INSERT for Nov (67.5M raw rows, the larger of the two
    # months) exceeded this machine's disk headroom even after monthly
    # chunking, and free disk on this box got tight enough (~2.6GB) that
    # even a ~13.5M-row weekly chunk was judged too risky. Daily chunks
    # (~2.2M raw events each) keep peak temp usage small; the tradeoff is
    # ~30 checkpoints instead of 1, which costs some wall-clock time but
    # not correctness — each chunk is still deduped/aggregated exactly
    # the same way, just over a narrower date filter.
    import datetime
    nov_day_filters = []
    d = datetime.date(2019, 11, 1)
    while d <= datetime.date(2019, 11, 30):
        nov_day_filters.append(f"event_date = '{d.isoformat()}'")
        d += datetime.timedelta(days=1)

    if table_exists(con, "session_summary"):
        n = con.execute("SELECT COUNT(*) FROM session_summary").fetchone()[0]
        log(f"\n### 4. session_summary\n- SKIPPED (already exists, {n:,} rows) — resuming pipeline")
    else:
        check_disk("4a. session_summary — Oct")
        t0 = time.time()
        log("\n### 4a. session_summary — Oct")
        con.execute(f"CREATE OR REPLACE TABLE session_summary AS {session_summary_select(oct_filter)}")
        con.execute("CHECKPOINT")
        log(f"- rows after Oct: {con.execute('SELECT COUNT(*) FROM session_summary').fetchone()[0]:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")

        check_disk("4b. session_summary — Nov")
        t0 = time.time()
        log("\n### 4b. session_summary — Nov")
        con.execute(f"INSERT INTO session_summary {session_summary_select(nov_filter)}")
        con.execute("CHECKPOINT")
        n_sessions = con.execute('SELECT COUNT(*) FROM session_summary').fetchone()[0]
        log(f"- rows after Oct+Nov: {n_sessions:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")
        invalid_sessions = con.execute("SELECT COUNT(*) FROM session_summary WHERE NOT is_valid_session").fetchone()[0]
        log(f"- sessions flagged invalid (multi-user): {invalid_sessions:,}")

    # ---------------------------------------------------------------
    # 5. session_product_funnel — CORE TABLE (also month-chunked)
    # ---------------------------------------------------------------
    def spf_select(date_filter):
        return f"""
            WITH base AS (
                SELECT
                    user_session,
                    product_id,
                    arg_min(user_id, event_time) AS user_id,
                    arg_min(category_id, event_time) AS category_id,
                    arg_min(category_code, event_time) AS category_code,
                    arg_min(brand, event_time) AS brand,
                    arg_min(price, event_time) AS price,
                    MIN(CASE WHEN event_type = 'view' THEN event_time END) AS first_view_time,
                    MIN(CASE WHEN event_type = 'cart' THEN event_time END) AS first_cart_time,
                    MIN(CASE WHEN event_type = 'purchase' THEN event_time END) AS first_purchase_time,
                    MIN(event_time) AS first_event_time
                FROM fact_events
                WHERE {date_filter}
                GROUP BY user_session, product_id
            )
            SELECT
                user_session, product_id, user_id, category_id, category_code, brand, price,
                {PRICE_BAND_CASE} AS price_band,
                first_view_time, first_cart_time, first_purchase_time,
                first_view_time IS NOT NULL AS viewed,
                first_cart_time IS NOT NULL AS carted,
                first_purchase_time IS NOT NULL AS purchased,
                (first_cart_time IS NOT NULL AND first_view_time IS NOT NULL
                    AND first_cart_time >= first_view_time) AS view_to_cart,
                (first_purchase_time IS NOT NULL AND first_cart_time IS NOT NULL
                    AND first_purchase_time >= first_cart_time) AS cart_to_purchase,
                (first_purchase_time IS NOT NULL AND first_view_time IS NOT NULL
                    AND first_purchase_time >= first_view_time) AS view_to_purchase,
                (first_purchase_time IS NOT NULL AND first_cart_time IS NULL) AS purchased_without_cart,
                CAST(first_event_time AS DATE) AS event_date
            FROM base
        """

    if table_exists(con, "session_product_funnel"):
        n = con.execute("SELECT COUNT(*) FROM session_product_funnel").fetchone()[0]
        log(f"\n### 5a. session_product_funnel — Oct\n- SKIPPED (table already exists, {n:,} rows so far) — resuming pipeline")
    else:
        check_disk("5a. session_product_funnel — Oct")
        t0 = time.time()
        log("\n### 5a. session_product_funnel — Oct")
        con.execute(f"CREATE OR REPLACE TABLE session_product_funnel AS {spf_select(oct_filter)}")
        con.execute("CHECKPOINT")
        log(f"- rows after Oct: {con.execute('SELECT COUNT(*) FROM session_product_funnel').fetchone()[0]:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")

    # Nov, one week at a time — resumable: skip any week whose rows are
    # already present, so a kill/crash partway through Nov only re-does
    # the one interrupted week. DuckDB's per-row-group zonemaps on
    # event_date make this COUNT cheap even without a dedicated index.
    for i, day_filter in enumerate(nov_day_filters, start=1):
        day_str = day_filter.split("'")[1]
        already_have = con.execute(
            f"SELECT COUNT(*) FROM session_product_funnel WHERE {day_filter}"
        ).fetchone()[0]
        if already_have > 0:
            log(f"\n### 5b.{i} session_product_funnel — Nov day {i} ({day_str})\n"
                f"- SKIPPED (already has {already_have:,} rows) — resuming pipeline")
            continue
        label = f"5b.{i} session_product_funnel — Nov day {i} ({day_str})"
        check_disk(label)
        t0 = time.time()
        log(f"\n### {label}")
        con.execute(f"INSERT INTO session_product_funnel {spf_select(day_filter)}")
        con.execute("CHECKPOINT")
        n_spf = con.execute("SELECT COUNT(*) FROM session_product_funnel").fetchone()[0]
        log(f"- cumulative rows: {n_spf:,}")
        log(f"- elapsed: {time.time() - t0:.1f}s; disk free: {free_gb(PROJECT_ROOT):.2f} GB")

    n_spf = con.execute('SELECT COUNT(*) FROM session_product_funnel').fetchone()[0]
    log(f"\n- session_product_funnel final row count: {n_spf:,}")
    pwc = con.execute("SELECT COUNT(*) FROM session_product_funnel WHERE purchased_without_cart").fetchone()[0]
    log(f"- (session,product) pairs purchased with no prior cart event: {pwc:,}")

    # ---------------------------------------------------------------
    # 6. agg_daily_funnel
    # ---------------------------------------------------------------
    step(con, "6. agg_daily_funnel", """
        CREATE OR REPLACE TABLE agg_daily_funnel AS
        SELECT
            event_date,
            strftime(event_date, '%A') AS day_of_week,
            SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS n_views,
            SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS n_carts,
            SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS n_purchases,
            COUNT(DISTINCT user_session) AS n_sessions,
            COUNT(DISTINCT user_id) AS n_users,
            SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue
        FROM fact_events
        GROUP BY event_date
    """, count_table="agg_daily_funnel")

    # ---------------------------------------------------------------
    # 7. agg_product_metrics
    # ---------------------------------------------------------------
    step(con, "7. agg_product_metrics", """
        CREATE OR REPLACE TABLE agg_product_metrics AS
        WITH events_agg AS (
            SELECT product_id,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_events,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS cart_events,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_events,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue
            FROM fact_events
            GROUP BY product_id
        ),
        funnel_agg AS (
            SELECT product_id,
                SUM(CASE WHEN viewed THEN 1 ELSE 0 END) AS viewing_sessions,
                SUM(CASE WHEN carted THEN 1 ELSE 0 END) AS carting_sessions,
                SUM(CASE WHEN purchased THEN 1 ELSE 0 END) AS purchasing_sessions,
                SUM(CASE WHEN view_to_cart THEN 1 ELSE 0 END) AS view_to_cart_sessions,
                SUM(CASE WHEN cart_to_purchase THEN 1 ELSE 0 END) AS cart_to_purchase_sessions,
                SUM(CASE WHEN view_to_purchase THEN 1 ELSE 0 END) AS view_to_purchase_sessions
            FROM session_product_funnel
            GROUP BY product_id
        )
        SELECT
            p.product_id, p.category_code, p.brand, p.avg_price,
            COALESCE(e.view_events, 0) AS view_events,
            COALESCE(e.cart_events, 0) AS cart_events,
            COALESCE(e.purchase_events, 0) AS purchase_events,
            COALESCE(f.viewing_sessions, 0) AS viewing_sessions,
            COALESCE(f.carting_sessions, 0) AS carting_sessions,
            COALESCE(f.purchasing_sessions, 0) AS purchasing_sessions,
            COALESCE(f.view_to_cart_sessions, 0) AS view_to_cart_sessions,
            COALESCE(f.cart_to_purchase_sessions, 0) AS cart_to_purchase_sessions,
            COALESCE(f.view_to_purchase_sessions, 0) AS view_to_purchase_sessions,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_cart_sessions * 1.0 / f.viewing_sessions END AS view_to_cart_rate,
            CASE WHEN f.carting_sessions > 0 THEN f.cart_to_purchase_sessions * 1.0 / f.carting_sessions END AS cart_to_purchase_rate,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_purchase_sessions * 1.0 / f.viewing_sessions END AS overall_conversion_rate,
            COALESCE(e.revenue, 0) AS revenue
        FROM dim_product p
        LEFT JOIN events_agg e USING (product_id)
        LEFT JOIN funnel_agg f USING (product_id)
    """, count_table="agg_product_metrics")

    # ---------------------------------------------------------------
    # 8. agg_category_metrics
    # ---------------------------------------------------------------
    step(con, "8. agg_category_metrics", """
        CREATE OR REPLACE TABLE agg_category_metrics AS
        WITH events_agg AS (
            SELECT category_code,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_events,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS cart_events,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_events,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue
            FROM fact_events
            WHERE category_code IS NOT NULL
            GROUP BY category_code
        ),
        funnel_agg AS (
            SELECT category_code,
                COUNT(DISTINCT product_id) AS n_products,
                SUM(CASE WHEN viewed THEN 1 ELSE 0 END) AS viewing_sessions,
                SUM(CASE WHEN carted THEN 1 ELSE 0 END) AS carting_sessions,
                SUM(CASE WHEN purchased THEN 1 ELSE 0 END) AS purchasing_sessions,
                SUM(CASE WHEN view_to_cart THEN 1 ELSE 0 END) AS view_to_cart_sessions,
                SUM(CASE WHEN cart_to_purchase THEN 1 ELSE 0 END) AS cart_to_purchase_sessions,
                SUM(CASE WHEN view_to_purchase THEN 1 ELSE 0 END) AS view_to_purchase_sessions
            FROM session_product_funnel
            WHERE category_code IS NOT NULL
            GROUP BY category_code
        ),
        totals AS (
            SELECT SUM(view_events) AS total_views, SUM(revenue) AS total_revenue FROM events_agg
        )
        SELECT
            e.category_code,
            COALESCE(f.n_products, 0) AS n_products,
            e.view_events, e.cart_events, e.purchase_events,
            COALESCE(f.viewing_sessions, 0) AS viewing_sessions,
            COALESCE(f.carting_sessions, 0) AS carting_sessions,
            COALESCE(f.purchasing_sessions, 0) AS purchasing_sessions,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_cart_sessions * 1.0 / f.viewing_sessions END AS view_to_cart_rate,
            CASE WHEN f.carting_sessions > 0 THEN f.cart_to_purchase_sessions * 1.0 / f.carting_sessions END AS cart_to_purchase_rate,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_purchase_sessions * 1.0 / f.viewing_sessions END AS overall_conversion_rate,
            e.revenue,
            e.view_events * 1.0 / t.total_views AS pct_of_total_views,
            e.revenue * 1.0 / NULLIF(t.total_revenue, 0) AS pct_of_total_revenue
        FROM events_agg e
        LEFT JOIN funnel_agg f USING (category_code)
        CROSS JOIN totals t
    """, count_table="agg_category_metrics")

    # ---------------------------------------------------------------
    # 9. agg_brand_metrics
    # ---------------------------------------------------------------
    step(con, "9. agg_brand_metrics", """
        CREATE OR REPLACE TABLE agg_brand_metrics AS
        WITH events_agg AS (
            SELECT brand,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_events,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS cart_events,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_events,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue
            FROM fact_events
            WHERE brand IS NOT NULL
            GROUP BY brand
        ),
        funnel_agg AS (
            SELECT brand,
                COUNT(DISTINCT product_id) AS n_products,
                SUM(CASE WHEN viewed THEN 1 ELSE 0 END) AS viewing_sessions,
                SUM(CASE WHEN view_to_cart THEN 1 ELSE 0 END) AS view_to_cart_sessions,
                SUM(CASE WHEN carted THEN 1 ELSE 0 END) AS carting_sessions,
                SUM(CASE WHEN cart_to_purchase THEN 1 ELSE 0 END) AS cart_to_purchase_sessions,
                SUM(CASE WHEN view_to_purchase THEN 1 ELSE 0 END) AS view_to_purchase_sessions
            FROM session_product_funnel
            WHERE brand IS NOT NULL
            GROUP BY brand
        )
        SELECT
            e.brand,
            COALESCE(f.n_products, 0) AS n_products,
            e.view_events, e.cart_events, e.purchase_events,
            COALESCE(f.viewing_sessions, 0) AS viewing_sessions,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_cart_sessions * 1.0 / f.viewing_sessions END AS view_to_cart_rate,
            CASE WHEN f.carting_sessions > 0 THEN f.cart_to_purchase_sessions * 1.0 / f.carting_sessions END AS cart_to_purchase_rate,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_purchase_sessions * 1.0 / f.viewing_sessions END AS overall_conversion_rate,
            e.revenue
        FROM events_agg e
        LEFT JOIN funnel_agg f USING (brand)
    """, count_table="agg_brand_metrics")

    # ---------------------------------------------------------------
    # 10. agg_price_band_metrics
    # ---------------------------------------------------------------
    step(con, "10. agg_price_band_metrics", """
        CREATE OR REPLACE TABLE agg_price_band_metrics AS
        WITH events_agg AS (
            SELECT price_band,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_events,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS cart_events,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchase_events,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS revenue,
                COUNT(DISTINCT product_id) AS n_products
            FROM fact_events
            GROUP BY price_band
        ),
        funnel_agg AS (
            SELECT price_band,
                SUM(CASE WHEN viewed THEN 1 ELSE 0 END) AS viewing_sessions,
                SUM(CASE WHEN carted THEN 1 ELSE 0 END) AS carting_sessions,
                SUM(CASE WHEN view_to_cart THEN 1 ELSE 0 END) AS view_to_cart_sessions,
                SUM(CASE WHEN cart_to_purchase THEN 1 ELSE 0 END) AS cart_to_purchase_sessions,
                SUM(CASE WHEN view_to_purchase THEN 1 ELSE 0 END) AS view_to_purchase_sessions
            FROM session_product_funnel
            GROUP BY price_band
        ),
        band_order AS (
            SELECT * FROM (VALUES
                ('Free ($0)', 0), ('$0-25', 1), ('$25-50', 2), ('$50-100', 3),
                ('$100-250', 4), ('$250-500', 5), ('$500-1000', 6), ('$1000+', 7)
            ) AS t(price_band, band_order)
        )
        SELECT
            e.price_band,
            b.band_order,
            e.n_products,
            e.view_events, e.cart_events, e.purchase_events,
            COALESCE(f.viewing_sessions, 0) AS viewing_sessions,
            COALESCE(f.carting_sessions, 0) AS carting_sessions,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_cart_sessions * 1.0 / f.viewing_sessions END AS view_to_cart_rate,
            CASE WHEN f.carting_sessions > 0 THEN f.cart_to_purchase_sessions * 1.0 / f.carting_sessions END AS cart_to_purchase_rate,
            CASE WHEN f.viewing_sessions > 0 THEN f.view_to_purchase_sessions * 1.0 / f.viewing_sessions END AS overall_conversion_rate,
            CASE WHEN f.carting_sessions > 0 THEN 1 - (f.cart_to_purchase_sessions * 1.0 / f.carting_sessions) END AS cart_abandonment_rate,
            e.revenue
        FROM events_agg e
        LEFT JOIN funnel_agg f USING (price_band)
        LEFT JOIN band_order b USING (price_band)
        ORDER BY b.band_order
    """, count_table="agg_price_band_metrics")

    # ---------------------------------------------------------------
    # 11. agg_user_metrics
    # ---------------------------------------------------------------
    # NOTE: originally a single GROUP BY user_id with three COUNT(DISTINCT...)
    # aggregates in one pass. That forces DuckDB to hold per-group distinct-value
    # state for all 5.3M user groups at once and OOM'd the temp-spill directory
    # on this machine's disk budget. Split into cheap dedup-then-count passes
    # (same pattern already used for fact_events/session_summary dedup above) —
    # each intermediate (user_id, session)/(user_id, date) distinct set is far
    # smaller than the raw 109.8M-row table, so no stage needs multi-distinct
    # per-group state.
    step(con, "11. agg_user_metrics", """
        CREATE OR REPLACE TABLE agg_user_metrics AS
        WITH base AS (
            SELECT user_id,
                MIN(event_date) AS first_seen_date,
                MAX(event_date) AS last_seen_date,
                COUNT(*) AS total_events,
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS total_views,
                SUM(CASE WHEN event_type = 'cart' THEN 1 ELSE 0 END) AS total_carts,
                SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS total_purchases,
                SUM(CASE WHEN event_type = 'purchase' THEN price ELSE 0 END) AS total_revenue
            FROM fact_events
            GROUP BY user_id
        ),
        sessions_per_user AS (
            SELECT user_id, COUNT(*) AS total_sessions
            FROM (SELECT DISTINCT user_id, user_session FROM fact_events)
            GROUP BY user_id
        ),
        active_days_per_user AS (
            SELECT user_id, COUNT(*) AS active_days
            FROM (SELECT DISTINCT user_id, event_date FROM fact_events)
            GROUP BY user_id
        ),
        purchase_days_per_user AS (
            SELECT user_id, COUNT(*) AS purchase_days
            FROM (SELECT DISTINCT user_id, event_date FROM fact_events WHERE event_type = 'purchase')
            GROUP BY user_id
        )
        SELECT
            b.user_id, b.first_seen_date, b.last_seen_date,
            COALESCE(ad.active_days, 0) AS active_days,
            COALESCE(sp.total_sessions, 0) AS total_sessions,
            b.total_events, b.total_views, b.total_carts, b.total_purchases, b.total_revenue,
            b.total_purchases > 0 AS is_purchaser,
            COALESCE(pd.purchase_days, 0) >= 2 AS is_repeat_purchaser,
            CASE
                WHEN b.total_purchases = 0 AND b.total_carts = 0 THEN 'Viewer only'
                WHEN b.total_purchases = 0 AND b.total_carts > 0 THEN 'Cart, no purchase'
                WHEN b.total_purchases > 0 AND COALESCE(pd.purchase_days, 0) >= 2 THEN 'Repeat buyer'
                ELSE 'One-time buyer'
            END AS activity_segment
        FROM base b
        LEFT JOIN sessions_per_user sp USING (user_id)
        LEFT JOIN active_days_per_user ad USING (user_id)
        LEFT JOIN purchase_days_per_user pd USING (user_id)
    """, count_table="agg_user_metrics")

    # ---------------------------------------------------------------
    # Indexes for dashboard/AI-analyst query speed
    # ---------------------------------------------------------------
    log("\n### Creating indexes")
    t0 = time.time()
    # One at a time + checkpoint after each so a kill mid-way (as happened once
    # on this machine under memory pressure) only loses the in-progress index,
    # not ones already built — CREATE INDEX IF NOT EXISTS makes each idempotent.
    for idx_sql, label in [
        ("CREATE INDEX IF NOT EXISTS idx_fact_events_date ON fact_events(event_date)", "idx_fact_events_date"),
        ("CREATE INDEX IF NOT EXISTS idx_fact_events_product ON fact_events(product_id)", "idx_fact_events_product"),
        ("CREATE INDEX IF NOT EXISTS idx_spf_category ON session_product_funnel(category_code)", "idx_spf_category"),
        ("CREATE INDEX IF NOT EXISTS idx_spf_brand ON session_product_funnel(brand)", "idx_spf_brand"),
    ]:
        ti = time.time()
        con.execute(idx_sql)
        con.execute("CHECKPOINT")
        log(f"- {label}: {time.time() - ti:.1f}s")
    log(f"- elapsed: {time.time() - t0:.1f}s")

    total_elapsed = time.time() - t_start
    log(f"\n---\n**Total pipeline runtime: {total_elapsed / 60:.1f} minutes**")

    con.close()

    out_path = DOCS_DIR / "pipeline_run_log.md"
    out_path.write_text("\n".join(log_lines))
    print(f"\nSaved pipeline log to {out_path}")


if __name__ == "__main__":
    main()
