"""
database.py
------------
Central place for connecting to the ProductPulse DuckDB database.

We use DuckDB (not PostgreSQL) because:
- It runs embedded, no server setup required (portfolio-friendly, zero-config).
- It handles the ~14GB raw CSV inputs via out-of-core execution without
  needing to load everything into Python/pandas memory.
- It supports full standard SQL (CTEs, window functions, etc.) which is
  what this project is meant to showcase.

The database file lives at productpulse/data/processed/productpulse.duckdb
"""

from pathlib import Path
import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "processed" / "productpulse.duckdb"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SQL_DIR = PROJECT_ROOT / "sql"


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection to the ProductPulse database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    return con


def run_sql_file(con: duckdb.DuckDBPyConnection, filename: str):
    """Execute a .sql file (statements separated by ';') located in sql/."""
    path = SQL_DIR / filename
    sql_text = path.read_text()
    con.execute(sql_text)


def query_df(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """Run a SQL query and return a pandas DataFrame."""
    if params:
        return con.execute(sql, params).df()
    return con.execute(sql).df()
