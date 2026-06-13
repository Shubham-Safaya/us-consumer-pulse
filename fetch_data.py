"""
US Consumer Pulse — daily data refresh.

Pulls free, public-domain US government statistics (no API keys, no PII):
- BLS Public API v1: CPI (all items, food, gasoline, shelter), unemployment,
  labor-force participation, average hourly earnings, retail-trade employment.
- Census ACS (optional): median household income + population by state.
  Census occasionally rejects anonymous calls; on any failure we keep the
  previous values in data/data.json so the dashboard never breaks.

All sources are US government works (public domain, 17 U.S.C. § 105) and the
output is aggregate statistics only — no personal information anywhere.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "data.json"

# Public-domain snapshot: US Census ACS 1-year median household income by state, 2023
# (17 U.S.C. § 105). Used when no CENSUS_API_KEY is set. Updates ~annually, so a
# static snapshot is honest; set the key to pull live instead. Population in millions.
ACS_2023_SNAPSHOT = [
    ("District of Columbia", 108210, 0.7), ("Massachusetts", 99858, 7.0),
    ("New Jersey", 99781, 9.3), ("Maryland", 98678, 6.2),
    ("New Hampshire", 96838, 1.4), ("California", 95521, 38.9),
    ("Hawaii", 95322, 1.4), ("Washington", 94605, 7.8),
    ("Utah", 93421, 3.4), ("Colorado", 92911, 5.9),
    ("Connecticut", 91665, 3.6), ("Virginia", 89931, 8.7),
    ("Alaska", 88121, 0.7), ("Minnesota", 85086, 5.7),
    ("New York", 82095, 19.6), ("Rhode Island", 81854, 1.1),
    ("Oregon", 80426, 4.2),
]

BLS_SERIES = {
    "CUUR0000SA0": "cpi_all",
    "CUUR0000SAF1": "cpi_food",
    "CUUR0000SETB01": "cpi_gas",
    "CUUR0000SAH1": "cpi_shelter",
    "LNS14000000": "unemployment_rate",
    "LNS11300000": "participation_rate",
    "CES0500000003": "avg_hourly_earnings",
    "CES4200000001": "retail_employment",
}

MONTH_NUM = {"M01": 1, "M02": 2, "M03": 3, "M04": 4, "M05": 5, "M06": 6,
             "M07": 7, "M08": 8, "M09": 9, "M10": 10, "M11": 11, "M12": 12}


def fetch_bls() -> dict:
    """One keyless POST for all series, ~3 years of monthly history."""
    this_year = date.today().year
    body = json.dumps({
        "seriesid": list(BLS_SERIES.keys()),
        "startyear": str(this_year - 3),
        "endyear": str(this_year),
    }).encode()
    req = urllib.request.Request(
        "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read())

    out = {}
    for series in payload["Results"]["series"]:
        key = BLS_SERIES.get(series["seriesID"])
        if not key:
            continue
        points = []
        for row in series["data"]:
            if row["period"] not in MONTH_NUM:
                continue
            try:
                value = float(row["value"])
            except (TypeError, ValueError):  # BLS uses "-" for missing months
                continue
            points.append({
                "date": f"{row['year']}-{MONTH_NUM[row['period']]:02d}",
                "value": value,
            })
        points.sort(key=lambda p: p["date"])
        out[key] = points
    return out


def yoy(points: list[dict]) -> list[dict]:
    """Year-over-year % change series from an index/level series."""
    by_date = {p["date"]: p["value"] for p in points}
    result = []
    for p in points:
        y, m = p["date"].split("-")
        prev = by_date.get(f"{int(y) - 1}-{m}")
        if prev:
            result.append({"date": p["date"], "value": round((p["value"] / prev - 1) * 100, 2)})
    return result


def fetch_census_states() -> list[dict]:
    """Median household income + population by state.

    Census now requires a (free) API key. If CENSUS_API_KEY is set we pull live
    ACS 1-year data; otherwise we return the bundled public-domain 2023 snapshot,
    which is honest because these figures only update once a year.
    """
    key = os.getenv("CENSUS_API_KEY", "").strip()
    if key:
        url = ("https://api.census.gov/data/2023/acs/acs1"
               f"?get=NAME,B19013_001E,B01003_001E&for=state:*&key={key}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.loads(r.read())
        states = []
        for name, income, pop, _fips in rows[1:]:
            try:
                states.append({"state": name, "median_income": int(income),
                               "population": int(pop)})
            except (TypeError, ValueError):
                continue
        states.sort(key=lambda s: s["median_income"], reverse=True)
        return states

    # No key: bundled public-domain snapshot (population millions -> people)
    return [{"state": n, "median_income": inc, "population": int(pop * 1_000_000)}
            for n, inc, pop in ACS_2023_SNAPSHOT]


def main():
    previous = {}
    if DATA_PATH.exists():
        try:
            previous = json.loads(DATA_PATH.read_text())
        except Exception:
            previous = {}

    data = {"updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

    try:
        bls = fetch_bls()
        data["series"] = bls
        data["derived"] = {
            "inflation_yoy": yoy(bls.get("cpi_all", [])),
            "food_inflation_yoy": yoy(bls.get("cpi_food", [])),
            "gas_inflation_yoy": yoy(bls.get("cpi_gas", [])),
            "shelter_inflation_yoy": yoy(bls.get("cpi_shelter", [])),
            "wage_growth_yoy": yoy(bls.get("avg_hourly_earnings", [])),
        }
        # Real wage growth = wage YoY minus CPI YoY (consumer purchasing power)
        cpi = {p["date"]: p["value"] for p in data["derived"]["inflation_yoy"]}
        data["derived"]["real_wage_growth"] = [
            {"date": p["date"], "value": round(p["value"] - cpi[p["date"]], 2)}
            for p in data["derived"]["wage_growth_yoy"] if p["date"] in cpi
        ]
        print(f"BLS OK: {len(bls)} series")
    except Exception as e:
        print(f"BLS failed ({e}); keeping previous series")
        data["series"] = previous.get("series", {})
        data["derived"] = previous.get("derived", {})

    try:
        data["states"] = fetch_census_states()
        src = "live API" if os.getenv("CENSUS_API_KEY", "").strip() else "2023 public-domain snapshot"
        data["states_source"] = src
        print(f"Census OK ({src}): {len(data['states'])} states")
    except Exception as e:
        print(f"Census live call failed ({e}); using bundled snapshot")
        data["states"] = [{"state": n, "median_income": inc, "population": int(p * 1_000_000)}
                          for n, inc, p in ACS_2023_SNAPSHOT]
        data["states_source"] = "2023 public-domain snapshot (fallback)"

    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, indent=1))
    print(f"Wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
