"""
Exports PA education data from silver.db into a JSON file formatted for
Infogram's Live Data feature.

Mirrors the "Overview" page of the education_dashboard Java app
(IdeaProjects/Test, com.education.EducationDataService), but replaces the
PSSA/Keystone grade-by-grade/group breakdown tables with a single statewide
headline row per subject.

Produces 4 sheets:
  1. PSSA Statewide       - one row per subject, most recent year vs prior
  2. Keystone Statewide   - same shape, Keystone exam
  3. Enrollment Overview  - statewide enrollment summary stats
  4. Adequacy Payments Overview - Ready-to-Learn funding summary stats

Run directly: py export_education_overview.py
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = r"C:\Users\JacobNCuster\database_project\data\warehouse\silver.db"
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR.parent / "education_overview.json"

PSSA_KEYSTONE_YEARS = [2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]
ENROLL_TRY_YEARS = [2026, 2025, 2024, 2023, 2022, 2021]


# ─── Table name / schema helpers (mirrors EducationDataService.java) ─────────

def pssa_table(year):
    return f"silver_pde_{year}_pssa_school_level_data"


def keystone_table(year):
    if 2021 <= year <= 2023:
        return f"silver_pde_{year}_keystone_school_level_data"
    return f"silver_pde_{year}_keystone_exams_school_level_data"


def table_exists(cur, table):
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def table_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def normalized_year_select(cur, table, year):
    """Build a SELECT that normalizes column-naming differences between years
    (pct_advanced vs percent_advanced, presence of a year column, etc.)."""
    cols = table_columns(cur, table)
    if not cols:
        return None
    yr_expr = "year" if "year" in cols else f"'{year}'"
    has_pct_prefix = "pct_advanced" in cols
    adv = "CAST(pct_advanced AS REAL)" if has_pct_prefix else "CAST(percent_advanced AS REAL)"
    prof = "CAST(pct_proficient AS REAL)" if has_pct_prefix else "CAST(percent_proficient AS REAL)"
    basic = "CAST(pct_basic AS REAL)" if has_pct_prefix else "CAST(percent_basic AS REAL)"
    bb = "CAST(pct_below_basic AS REAL)" if has_pct_prefix else "CAST(percent_below_basic AS REAL)"
    return (
        f"SELECT {yr_expr} AS yr, subject, \"group\" AS grp, grade, "
        f"CAST(number_scored AS INTEGER) AS number_scored, "
        f"{adv} AS adv, {prof} AS prof, {basic} AS basic, {bb} AS bb "
        f"FROM {table}"
    )


def build_union(cur, table_fn):
    parts = []
    for year in PSSA_KEYSTONE_YEARS:
        table = table_fn(year)
        if table_exists(cur, table):
            select = normalized_year_select(cur, table, year)
            if select:
                parts.append(select)
    return " UNION ALL ".join(parts)


def grade_sort_key(grade):
    try:
        return (0, int(grade))
    except (TypeError, ValueError):
        return (1, str(grade))


def pp_change(cur_val, prev_val):
    if cur_val is None or prev_val is None:
        return None
    return round(cur_val - prev_val, 1)


def pct_change(cur_val, prev_val):
    if cur_val is None or prev_val is None or prev_val == 0:
        return None
    return round((cur_val - prev_val) / prev_val * 100, 1)


# ─── PSSA / Keystone statewide headline rows ─────────────────────────────────

def statewide_exam_rows(cur, exam):
    table_fn = pssa_table if exam == "pssa" else keystone_table
    union_sql = build_union(cur, table_fn)
    if not union_sql:
        return [], None, None

    # Two most recent years that have "All Students" data
    cur.execute(
        f"SELECT DISTINCT yr FROM ({union_sql}) WHERE grp = 'All Students' "
        f"ORDER BY CAST(yr AS INTEGER) DESC LIMIT 2"
    )
    years = [row[0] for row in cur.fetchall()]
    if not years:
        return [], None, None
    cur_yr = years[0]
    prev_yr = years[1] if len(years) > 1 else None

    year_list = [cur_yr] + ([prev_yr] if prev_yr else [])
    placeholders = ",".join("?" for _ in year_list)
    cur.execute(
        f"SELECT yr, subject, grade, AVG(adv) adv, AVG(prof) prof, AVG(basic) basic, "
        f"AVG(bb) bb, SUM(number_scored) ns "
        f"FROM ({union_sql}) WHERE grp = 'All Students' AND yr IN ({placeholders}) "
        f"GROUP BY yr, subject, grade",
        year_list,
    )

    by_subject_grade = {}
    grades_by_subject = {}
    for yr, subject, grade, adv, prof, basic, bb, ns in cur.fetchall():
        by_subject_grade.setdefault((subject, grade), {})[yr] = {
            "adv": adv, "prof": prof, "basic": basic, "bb": bb, "ns": ns,
        }
        seen = grades_by_subject.setdefault(subject, [])
        if grade not in seen:
            seen.append(grade)

    rows = []
    for subject in sorted(grades_by_subject.keys()):
        grades = grades_by_subject[subject]
        headline_grade = "Total" if "Total" in grades else sorted(grades, key=grade_sort_key)[0]

        by_year = by_subject_grade.get((subject, headline_grade), {})
        cur_vals = by_year.get(cur_yr)
        if not cur_vals:
            continue
        prev_vals = by_year.get(prev_yr) if prev_yr else None

        def r1(v):
            return round(v, 1) if v is not None else None

        rows.append([
            subject,
            cur_yr,
            prev_yr,
            r1(cur_vals["adv"]),
            pp_change(cur_vals["adv"], prev_vals["adv"] if prev_vals else None),
            r1(cur_vals["prof"]),
            pp_change(cur_vals["prof"], prev_vals["prof"] if prev_vals else None),
            r1(cur_vals["basic"]),
            pp_change(cur_vals["basic"], prev_vals["basic"] if prev_vals else None),
            r1(cur_vals["bb"]),
            pp_change(cur_vals["bb"], prev_vals["bb"] if prev_vals else None),
            cur_vals["ns"],
            pct_change(cur_vals["ns"], prev_vals["ns"] if prev_vals else None),
        ])

    return rows, cur_yr, prev_yr


EXAM_HEADERS = [
    "Subject", "Year", "Prior Year", "Advanced %", "Advanced Point Change",
    "Proficient %", "Proficient Point Change",
    "Basic %", "Basic Point Change",
    "Below Basic %", "Below Basic Point Change",
    "Students Tested", "Students Tested % Change",
]

# Indices into an EXAM_HEADERS row for the 4 proficiency-band percentages,
# used to build a chart-friendly sheet with just Subject + percentages
# (no year/point-change/count columns to confuse a first bar chart).
CHART_HEADERS = ["Subject", "Advanced %", "Proficient %", "Basic %", "Below Basic %"]
CHART_COL_IDX = [0, 3, 5, 7, 9]


# ─── Enrollment overview ──────────────────────────────────────────────────────

def detect_enroll_years(cur):
    found = []
    for year in ENROLL_TRY_YEARS:
        table = f"silver_pde_{year}_enrollment_lea"
        if not table_exists(cur, table):
            continue
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        if cur.fetchone()[0] > 0:
            found.append(year)
            if len(found) == 2:
                break
    return found


def enrollment_overview_rows(cur):
    years = detect_enroll_years(cur)
    if not years:
        return [], None
    cur_yr = years[0]
    prev_yr = years[1] if len(years) > 1 else None

    union = (
        f"SELECT {cur_yr} AS yr, aun, lea_name, CAST(total AS INTEGER) AS total "
        f"FROM silver_pde_{cur_yr}_enrollment_lea"
    )
    if prev_yr:
        union += (
            f" UNION ALL SELECT {prev_yr} AS yr, aun, lea_name, CAST(total AS INTEGER) AS total "
            f"FROM silver_pde_{prev_yr}_enrollment_lea"
        )
    prev_col = f"SUM(CASE WHEN yr={prev_yr} THEN total END) AS total_prev" if prev_yr else "NULL AS total_prev"

    cur.execute(
        f"SELECT aun, lea_name, SUM(CASE WHEN yr={cur_yr} THEN total END) AS total_cur, {prev_col} "
        f"FROM ({union}) GROUP BY aun, lea_name "
        f"HAVING total_cur IS NOT NULL AND total_cur > 0 ORDER BY total_cur DESC"
    )
    districts = cur.fetchall()
    if not districts:
        return [], cur_yr

    total_enrollment = sum(d[2] for d in districts)
    district_count = len(districts)
    largest = districts[0]

    biggest_gain = None
    biggest_loss = None
    for aun, name, cur_v, prev_v in districts:
        if prev_v is None:
            continue
        change = cur_v - prev_v
        if biggest_gain is None or change > biggest_gain[1]:
            biggest_gain = (name, change)
        if biggest_loss is None or change < biggest_loss[1]:
            biggest_loss = (name, change)

    rows = [
        ["Total PA Enrollment", total_enrollment, f"Across {district_count:,} reporting districts"],
        ["Districts Reporting", district_count, f"Pennsylvania {cur_yr}"],
        ["Largest District", largest[2], largest[1]],
    ]
    if biggest_gain:
        rows.append(["Biggest Gain", biggest_gain[1], biggest_gain[0]])
    if biggest_loss:
        rows.append(["Biggest Decline", biggest_loss[1], biggest_loss[0]])
    return rows, cur_yr


ENROLLMENT_HEADERS = ["Metric", "Value", "Detail"]


# ─── Adequacy (Ready-to-Learn) overview ───────────────────────────────────────

def adequacy_overview_rows(cur):
    required = ("silver_rtl_2025_main", "silver_rtl_2025_adequacy", "silver_rtl_2026_proposed_main")
    if not all(table_exists(cur, t) for t in required):
        return []

    cur.execute(
        "SELECT m25.aun, m25.lea_name, "
        "CAST(m25.\"2025_26_ready_to_learn_block_grant_feb2026\" AS REAL) total_25, "
        "CAST(m25.\"2025_26_adequacy_supplement\" AS REAL) adequacy_25, "
        "CAST(m26.\"2026_27_proposed_ready_to_learn_block_grant_feb_2026\" AS REAL) total_26, "
        "CAST(a25.adequacy_gap AS REAL) adequacy_gap "
        "FROM silver_rtl_2025_main m25 "
        "LEFT JOIN silver_rtl_2025_adequacy a25 ON m25.aun = a25.aun "
        "LEFT JOIN silver_rtl_2026_proposed_main m26 ON m25.aun = m26.aun "
        "WHERE m25.aun IS NOT NULL AND m25.lea_name IS NOT NULL"
    )
    districts = cur.fetchall()
    if not districts:
        return []

    tot25 = tot26 = adeq25 = total_gap = 0.0
    top_dist = None
    top_gap_dist = None
    for aun, name, t25, a25, t26, gap in districts:
        tot25 += t25 or 0
        tot26 += t26 or 0
        adeq25 += a25 or 0
        g = gap or 0
        if g > 0:
            total_gap += g
            if top_gap_dist is None or g > top_gap_dist[1]:
                top_gap_dist = (name, g)
        if top_dist is None or (t25 or 0) > top_dist[1]:
            top_dist = (name, t25 or 0)

    delta = tot26 - tot25
    sign = "+" if delta >= 0 else ""
    rows = [
        ["2025-26 Total RTL", round(tot25, 2), "Ready-to-Learn Block Grant, statewide"],
        ["2026-27 Proposed Total RTL", round(tot26, 2), f"{sign}{round(delta, 2)} vs 2025-26 enacted"],
        ["Adequacy Supplement (2025-26)", round(adeq25, 2), "Statewide"],
        ["Total Adequacy Gap", round(total_gap, 2), "Sum of underfunded districts"],
    ]
    if top_gap_dist:
        rows.append(["Largest Gap District", round(top_gap_dist[1], 2), top_gap_dist[0]])
    if top_dist:
        rows.append(["Largest RTL Recipient", round(top_dist[1], 2), top_dist[0]])
    return rows


ADEQUACY_HEADERS = ["Metric", "Value ($)", "Detail"]


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()

    pssa_rows, pssa_cur_yr, pssa_prev_yr = statewide_exam_rows(cur, "pssa")
    keystone_rows, key_cur_yr, key_prev_yr = statewide_exam_rows(cur, "keystone")
    enrollment_rows, enroll_yr = enrollment_overview_rows(cur)
    adequacy_rows = adequacy_overview_rows(cur)

    conn.close()

    # Infogram's JSON feed format (see https://infogram.com/api/examples/live_tabs.json)
    # is a plain array of sheets, each sheet a list of rows, each row a list of
    # cells. There is no "title" key — the tab/sheet name is just the top-left
    # cell of that sheet's header row. Sheet names are kept stable (no year
    # embedded) so charts built in Infogram stay bound to the same tab across
    # future refreshes; the year itself travels inside each sheet's rows
    # instead (see EXAM_HEADERS and the "Detail" column of the overview sheets).
    def build_sheet(title, headers, rows):
        header_row = [title] + list(headers[1:])
        return [header_row] + rows

    def build_chart_sheet(title, rows):
        """Slim Subject + 4 percentages sheet — good for comparing subjects
        side-by-side on ONE proficiency band (e.g. Advanced % across subjects)."""
        header_row = [title] + CHART_HEADERS[1:]
        chart_rows = [[row[i] for i in CHART_COL_IDX] for row in rows]
        return [header_row] + chart_rows

    def build_breakdown_sheets(exam_label, rows):
        """One sheet per subject, transposed: Category (Advanced/Proficient/
        Basic/Below Basic) as rows, a single percent column — good for a pie
        chart or single-subject bar chart showing that subject's breakdown."""
        sheets = []
        for row in rows:
            subject, adv, prof, basic, bb = (row[i] for i in CHART_COL_IDX)
            title = f"{exam_label} {subject}"
            sheets.append([
                [title, "Percent of Students"],
                ["Advanced", adv],
                ["Proficient", prof],
                ["Basic", basic],
                ["Below Basic", bb],
            ])
        return sheets

    sheets = [
        build_chart_sheet("PSSA Statewide", pssa_rows),
        build_chart_sheet("Keystone Statewide", keystone_rows),
        *build_breakdown_sheets("PSSA", pssa_rows),
        *build_breakdown_sheets("Keystone", keystone_rows),
        build_sheet("PSSA Statewide Detail", EXAM_HEADERS, pssa_rows),
        build_sheet("Keystone Statewide Detail", EXAM_HEADERS, keystone_rows),
        build_sheet("Enrollment Overview", ENROLLMENT_HEADERS, enrollment_rows),
        build_sheet("Adequacy Payments Overview", ADEQUACY_HEADERS, adequacy_rows),
    ]

    OUTPUT_PATH.write_text(json.dumps(sheets, indent=2), encoding="utf-8")

    print("Export complete.")
    print(f"  Output file: {OUTPUT_PATH}")
    for sheet in sheets:
        print(f"  - {sheet[0][0]}: {len(sheet) - 1} rows")


if __name__ == "__main__":
    main()
