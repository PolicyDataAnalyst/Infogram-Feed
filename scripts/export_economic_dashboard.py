"""
Exports PA labor market data from labordata.db into JSON files formatted for
Infogram's Live Data feature.

Mirrors the PA Economic Dashboard artifact's data source
(IdeaProjects/Test/dashboard_refresh/build_dashboard.py) — same 9 BLS LAUS
series, monthly, since 2019.

Produces 4 output files:
  - labor_market_trend.json      - all 9 series, one row per month, since 2019
  - employment_rate.json         - PA Employment-Population Ratio, last 5 years
  - unemployment_rate.json       - PA Unemployment Rate, last 5 years
  - labor_participation_rate.json - PA Labor Force Participation Rate, last 5 years

Run directly: py export_economic_dashboard.py
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = r"C:\Users\JacobNCuster\IdeaProjects\Test\db\labordata.db"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = REPO_ROOT / "labor_market_trend.json"
EMPLOYMENT_RATE_OUTPUT_PATH = REPO_ROOT / "employment_rate.json"
UNEMPLOYMENT_RATE_OUTPUT_PATH = REPO_ROOT / "unemployment_rate.json"
LABOR_PARTICIPATION_RATE_OUTPUT_PATH = REPO_ROOT / "labor_participation_rate.json"

RATE_TREND_MONTHS = 60  # trailing 5 years of monthly data

# "Employment rate" conventionally means the Employment-Population Ratio (the
# BLS/labordata.db series names for PA's unemployment rate, participation
# rate, and employment-population ratio, respectively).
EMPLOYMENT_RATE_SERIES = ("LASST420000000000007", "PA Employment Rate", "Employment-Population Ratio (%)")
UNEMPLOYMENT_RATE_SERIES = ("LASST420000000000003", "PA Unemployment Rate", "Unemployment Rate (%)")
LABOR_PARTICIPATION_RATE_SERIES = ("LASST420000000000008", "PA Labor Force Participation Rate", "Participation Rate (%)")

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


def last_n_months_sheet(cur, series_id, title, value_label, months=RATE_TREND_MONTHS):
    cur.execute("SELECT date, value FROM series_data WHERE series_id = ? ORDER BY date", (series_id,))
    rows = cur.fetchall()[-months:]
    header_row = [title, value_label]
    data_rows = [[date, round(value, 1) if value is not None else None] for date, value in rows]
    return [header_row] + data_rows


def main():
    conn = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date FROM series_data ORDER BY date")
    dates = [row[0] for row in cur.fetchall()]

    values_by_series = {}
    for series_id, _ in SERIES:
        cur.execute("SELECT date, value FROM series_data WHERE series_id = ?", (series_id,))
        values_by_series[series_id] = dict(cur.fetchall())

    header_row = ["PA Labor Market Trend"] + [label for _, label in SERIES]
    data_rows = []
    for date in dates:
        row = [date]
        for series_id, _ in SERIES:
            value = values_by_series[series_id].get(date)
            row.append(round(value, 1) if value is not None else None)
        data_rows.append(row)
    labor_market_sheets = [[header_row] + data_rows]

    employment_rate_sheets = [last_n_months_sheet(cur, *EMPLOYMENT_RATE_SERIES)]
    unemployment_rate_sheets = [last_n_months_sheet(cur, *UNEMPLOYMENT_RATE_SERIES)]
    labor_participation_rate_sheets = [last_n_months_sheet(cur, *LABOR_PARTICIPATION_RATE_SERIES)]

    conn.close()

    outputs = [
        (OUTPUT_PATH, labor_market_sheets),
        (EMPLOYMENT_RATE_OUTPUT_PATH, employment_rate_sheets),
        (UNEMPLOYMENT_RATE_OUTPUT_PATH, unemployment_rate_sheets),
        (LABOR_PARTICIPATION_RATE_OUTPUT_PATH, labor_participation_rate_sheets),
    ]

    print("Export complete.")
    for path, sheets in outputs:
        path.write_text(json.dumps(sheets, indent=2), encoding="utf-8")
        print(f"  Output file: {path}")
        for sheet in sheets:
            print(f"    - {sheet[0][0]}: {len(sheet) - 1} rows")


if __name__ == "__main__":
    main()
