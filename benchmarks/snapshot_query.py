"""Compare an existing DWH index, a covering index, and monthly routing."""

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from statistics import median
from time import perf_counter_ns

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    # Also support running this file directly from the project folder.
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.snapshot_partitions import FACT, refresh_snapshot_months


def build_monthly_tables(db):
    db.execute("CREATE TABLE IF NOT EXISTS snapshot_month (month_key INTEGER PRIMARY KEY, dirty INTEGER NOT NULL)")
    db.execute(
        f"INSERT OR REPLACE INTO snapshot_month SELECT DISTINCT date_key / 100, 1 FROM {FACT}"
    )
    refresh_snapshot_months(db)
    return [month for (month,) in db.execute(f"SELECT DISTINCT date_key / 100 FROM {FACT} ORDER BY 1")]


def query(table, index=None):
    index_hint = f" INDEXED BY {index}" if index else ""
    return f"""
        SELECT COUNT(*), ROUND(AVG(sale_price), 2)
        FROM {table}{index_hint}
        WHERE platform_key = ? AND date_key >= ? AND date_key < ?
    """


def compare(db, month, platform_key, runs):
    year, month_number = divmod(month, 100)
    next_month = (year + 1) * 100 + 1 if month_number == 12 else month + 1
    parameters = (platform_key, month * 100 + 1, next_month * 100 + 1)
    variants = [
        ("Existing date/product index", query(FACT, f"idx_{FACT}_date_product")),
        ("Added covering index", query(FACT)),
        ("Monthly table + covering index", query(f"snapshot_{month}")),
    ]
    expected = db.execute(query(FACT), parameters).fetchone()
    print(f"\nMonth {month}, platform {platform_key}: count={expected[0]}, avg={expected[1]}")
    for label, statement in variants:
        for _ in range(5):
            if db.execute(statement, parameters).fetchone() != expected:
                raise RuntimeError(f"{label} returned a different result")
        plans = db.execute("EXPLAIN QUERY PLAN " + statement, parameters)
        samples = []
        for _ in range(runs):
            start = perf_counter_ns()
            db.execute(statement, parameters).fetchone()
            samples.append((perf_counter_ns() - start) / 1_000_000)
        print(f"  {label}: {median(samples):.4f} ms")
        for plan in plans:
            print(f"    {plan[3]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "instance/dwh.db")
    parser.add_argument("--runs", type=int, default=100)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    source_uri = args.database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source:
        with closing(sqlite3.connect(":memory:")) as db:
            source.backup(db)
            months = build_monthly_tables(db)
            if not months:
                parser.error("the snapshot fact is empty")
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fact_snapshot_platform_date_price "
                f"ON {FACT} (platform_key, date_key, sale_price)"
            )
            db.execute("ANALYZE")
            total = db.execute(f"SELECT COUNT(*) FROM {FACT}").fetchone()[0]
            print(f"SQLite {sqlite3.sqlite_version}; {total} snapshots; {args.runs} timed runs")
            for month in months:
                table = f"snapshot_{month}"
                platform_key = db.execute(
                    f"""SELECT platform_key FROM {table} GROUP BY platform_key
                        ORDER BY COUNT(*) DESC, platform_key LIMIT 1"""
                ).fetchone()[0]
                compare(db, month, platform_key, args.runs)


if __name__ == "__main__":
    main()
