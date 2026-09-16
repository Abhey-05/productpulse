"""
inspect_data.py
----------------
PHASE 1 — Inspect the raw dataset BEFORE building anything else.

This script loads the two raw CSVs into DuckDB as external (view-based)
sources and runs a battery of profiling queries: row counts, unique users/
sessions/products/categories/brands, date range, event type breakdown,
null rates per column, duplicate rows, and basic price sanity checks.

Output is printed to stdout and also written to
productpulse/docs/data_inspection_report.md so findings are reproducible
and documented, per project requirements (inspect before building).
"""

import time
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

OCT_CSV = RAW_DIR / "2019-Oct.csv"
NOV_CSV = RAW_DIR / "2019-Nov.csv"

report_lines = []


def log(msg=""):
    print(msg)
    report_lines.append(msg)


def main():
    t0 = time.time()
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")

    log("# ProductPulse — Raw Data Inspection Report")
    log(f"\nGenerated from files:\n- {OCT_CSV}\n- {NOV_CSV}\n")

    # Create a view over both files combined (schema already verified identical)
    con.execute(f"""
        CREATE VIEW raw_events AS
        SELECT * FROM read_csv_auto(
            ['{OCT_CSV}', '{NOV_CSV}'],
            union_by_name=True,
            timestampformat='%Y-%m-%d %H:%M:%S UTC'
        )
    """)

    # --- Row counts per file & combined ---
    log("## 1. Row counts")
    oct_count = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{OCT_CSV}')").fetchone()[0]
    nov_count = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{NOV_CSV}')").fetchone()[0]
    log(f"- 2019-Oct.csv rows: {oct_count:,}")
    log(f"- 2019-Nov.csv rows: {nov_count:,}")
    log(f"- Combined rows: {oct_count + nov_count:,}")

    # --- Schema ---
    log("\n## 2. Schema (inferred by DuckDB)")
    schema = con.execute("DESCRIBE raw_events").fetchdf()
    log(schema.to_markdown(index=False))

    # --- Date range ---
    log("\n## 3. Date range")
    date_range = con.execute("""
        SELECT MIN(event_time) AS min_ts, MAX(event_time) AS max_ts
        FROM raw_events
    """).fetchone()
    log(f"- Min event_time: {date_range[0]}")
    log(f"- Max event_time: {date_range[1]}")

    # --- Event type breakdown ---
    log("\n## 4. Event type breakdown")
    ev = con.execute("""
        SELECT event_type, COUNT(*) AS n,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 3) AS pct
        FROM raw_events
        GROUP BY event_type
        ORDER BY n DESC
    """).fetchdf()
    log(ev.to_markdown(index=False))

    # --- Cardinalities ---
    log("\n## 5. Cardinality (distinct counts)")
    card = con.execute("""
        SELECT
            COUNT(DISTINCT user_id) AS distinct_users,
            COUNT(DISTINCT user_session) AS distinct_sessions,
            COUNT(DISTINCT product_id) AS distinct_products,
            COUNT(DISTINCT category_id) AS distinct_category_ids,
            COUNT(DISTINCT category_code) AS distinct_category_codes,
            COUNT(DISTINCT brand) AS distinct_brands
        FROM raw_events
    """).fetchdf()
    log(card.to_markdown(index=False))

    # --- Null / missing value rates ---
    log("\n## 6. Missing value rates (%)")
    nulls = con.execute("""
        SELECT
            ROUND(100.0 * SUM(CASE WHEN event_time IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS event_time_null_pct,
            ROUND(100.0 * SUM(CASE WHEN event_type IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS event_type_null_pct,
            ROUND(100.0 * SUM(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS product_id_null_pct,
            ROUND(100.0 * SUM(CASE WHEN category_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS category_id_null_pct,
            ROUND(100.0 * SUM(CASE WHEN category_code IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS category_code_null_pct,
            ROUND(100.0 * SUM(CASE WHEN brand IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS brand_null_pct,
            ROUND(100.0 * SUM(CASE WHEN price IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS price_null_pct,
            ROUND(100.0 * SUM(CASE WHEN user_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS user_id_null_pct,
            ROUND(100.0 * SUM(CASE WHEN user_session IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS user_session_null_pct
        FROM raw_events
    """).fetchdf()
    log(nulls.T.to_markdown())

    # --- Duplicate rows (exact duplicates) ---
    log("\n## 7. Exact duplicate rows")
    dup = con.execute("""
        SELECT COUNT(*) AS total_rows, COUNT(*) - COUNT(DISTINCT (event_time, event_type, product_id, category_id, brand, price, user_id, user_session)) AS duplicate_rows
        FROM raw_events
    """).fetchdf()
    log(dup.to_markdown(index=False))

    # --- Price sanity ---
    log("\n## 8. Price sanity check")
    price_check = con.execute("""
        SELECT
            MIN(price) AS min_price,
            MAX(price) AS max_price,
            AVG(price) AS avg_price,
            SUM(CASE WHEN price < 0 THEN 1 ELSE 0 END) AS negative_price_rows,
            SUM(CASE WHEN price = 0 THEN 1 ELSE 0 END) AS zero_price_rows
        FROM raw_events
    """).fetchdf()
    log(price_check.to_markdown(index=False))

    # --- event_type distinct values (sanity — confirm only expected values) ---
    log("\n## 9. Distinct event_type values")
    ev_vals = con.execute("SELECT DISTINCT event_type FROM raw_events").fetchdf()
    log(ev_vals.to_markdown(index=False))

    # --- category_code structure sample ---
    log("\n## 10. Sample category_code values (non-null)")
    cc_sample = con.execute("""
        SELECT DISTINCT category_code FROM raw_events
        WHERE category_code IS NOT NULL
        LIMIT 20
    """).fetchdf()
    log(cc_sample.to_markdown(index=False))

    # --- rows with category_code null but category_id present ---
    log("\n## 11. category_code coverage")
    cc_cov = con.execute("""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN category_code IS NULL THEN 1 ELSE 0 END) AS null_category_code,
            SUM(CASE WHEN brand IS NULL THEN 1 ELSE 0 END) AS null_brand
        FROM raw_events
    """).fetchdf()
    log(cc_cov.to_markdown(index=False))

    # --- session-level sanity: does a session ever span multiple users? ---
    log("\n## 12. Session integrity check (does user_session map 1:1 to user_id?)")
    sess_check = con.execute("""
        SELECT COUNT(*) AS sessions_with_multiple_users FROM (
            SELECT user_session, COUNT(DISTINCT user_id) AS n_users
            FROM raw_events
            GROUP BY user_session
            HAVING COUNT(DISTINCT user_id) > 1
        )
    """).fetchdf()
    log(sess_check.to_markdown(index=False))

    # --- events per day for continuity check ---
    log("\n## 13. Distinct dates covered & any gaps")
    days = con.execute("""
        SELECT CAST(event_time AS DATE) AS d, COUNT(*) AS n
        FROM raw_events
        GROUP BY 1 ORDER BY 1
    """).fetchdf()
    log(f"- Number of distinct calendar days: {len(days)}")
    log(f"- First day: {days['d'].min()}, Last day: {days['d'].max()}")
    log(f"- Min events/day: {days['n'].min():,}, Max events/day: {days['n'].max():,}")

    elapsed = time.time() - t0
    log(f"\n---\nInspection completed in {elapsed:.1f}s")

    out_path = DOCS_DIR / "data_inspection_report.md"
    out_path.write_text("\n".join(report_lines))
    print(f"\nSaved report to {out_path}")


if __name__ == "__main__":
    main()
