"""
Exports PA labor market trend data from labordata.db into a JSON file
formatted for Infogram's Live Data feature.

Mirrors the PA Economic Dashboard artifact's data source
(IdeaProjects/Test/dashboard_refresh/build_dashboard.py) — same 9 BLS LAUS
series, monthly, since 2019.

Produces 1 output file:
  - labor_market_trend.json - one sheet, one row per month, one column per series

Run directly: py export_economic_dashboard.py
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = r"C:\Users\JacobNCuster\IdeaProjects\Test\db\labordata.db"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = REPO_ROOT / "labor_market_trend.json"

# Same series + order as dashboard_refresh/build_dashboard.py's SERIES_IDS.
# NOTE: series_metadata.unit says "Thousands" for the count-based series below,
# but the stored values are actual persons counts (e.g. ~6.3 million for PA
# employment, not 6,300) — that metadata label appears stale, so these are
# labeled "(Persons)" here to match the real data rather than the DB's label.
SERIES = [
    ("LASST420000000000005", "PA Employment (Persons)"),
    ("LASST420000000000004", "PA Unemployment (Persons)"),
    ("LASST420000000000006", "PA Labor Force (Persons)"),
    ("LAUST420000000000009", "PA Civilian Noninstitutional Population (Persons)"),
    ("LAUST420000000000006", "PA Labor Force, NSA (Persons)"),
    ("LASST420000000000003", "PA Unemployment Rate (%)"),
    ("LASST420000000000008", "PA Labor Force Participation Rate (%)"),
    ("LASST420000000000007", "PA Employment-Population Ratio (%)"),
    ("LNS14000000", "National Unemployment Rate (%)"),
]


def main():
    conn = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date FROM series_data ORDER BY date")
    dates = [row[0] for row in cur.fetchall()]

    values_by_series = {}
    for series_id, _ in SERIES:
        cur.execute("SELECT date, value FROM series_data WHERE series_id = ?", (series_id,))
        values_by_series[series_id] = dict(cur.fetchall())

    conn.close()

    header_row = ["PA Labor Market Trend"] + [label for _, label in SERIES]
    data_rows = []
    for date in dates:
        row = [date]
        for series_id, _ in SERIES:
            value = values_by_series[series_id].get(date)
            row.append(round(value, 1) if value is not None else None)
        data_rows.append(row)

    sheets = [[header_row] + data_rows]

    OUTPUT_PATH.write_text(json.dumps(sheets, indent=2), encoding="utf-8")

    print("Export complete.")
    print(f"  Output file: {OUTPUT_PATH}")
    print(f"  PA Labor Market Trend: {len(data_rows)} rows ({dates[0]} to {dates[-1]})")


if __name__ == "__main__":
    main()
