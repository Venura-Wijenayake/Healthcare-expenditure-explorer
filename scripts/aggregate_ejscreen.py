"""Stream-aggregate EPA EJSCREEN block-group CSVs (2015-2024) to county level.

For each year, the BG CSV is read in chunks, indicators are population-weighted
to the county level (first 5 digits of the 12-digit block-group GEOID), and all
years are concatenated into a single tidy CSV with a `year` column.
"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
OUTPUT = DATA_DIR / "epa_ejscreen.csv"

# (year, outer_zip, inner_zip_path_or_None, inner_csv_name_or_None, direct_csv_path_or_None)
SOURCES = [
    (2015, "data/ejscreen_2015.zip", "2015/EJSCREEN_20150505.csv.zip", "EJSCREEN_20150505.csv", None),
    (2016, "data/ejscreen_2016.zip", "2016/EJSCREEN_V3_USPR_090216_CSV.zip", "EJSCREEN_Full_V3_USPR_TSDFupdate.csv", None),
    (2017, "data/ejscreen_2017.zip", None, None, "2017/EJSCREEN_2017_USPR_Public.csv"),
    (2018, "data/ejscreen_2018.zip", "2018/EJSCREEN_2018_USPR_csv.zip", "EJSCREEN_Full_USPR_2018.csv", None),
    (2019, "data/ejscreen_2019.zip", "2019/EJSCREEN_2019_USPR.csv.zip", "EJSCREEN_2019_USPR.csv", None),
    (2020, "data/ejscreen_2020.zip", "2020/EJSCREEN_2020_USPR.csv.zip", "EJSCREEN_2020_USPR.csv", None),
    (2021, "data/ejscreen_2021.zip", "2021/EJSCREEN_2021_USPR.csv.zip", "EJSCREEN_2021_USPR.csv", None),
    (2022, "data/ejscreen_2022.zip", "2022/EJSCREEN_2022_with_AS_CNMI_GU_VI.csv.zip", "EJSCREEN_2022_Full_with_AS_CNMI_GU_VI.csv", None),
    (2023, "data/ejscreen_2023.zip", "2023/2.22_September_UseMe/EJSCREEN_2023_BG_with_AS_CNMI_GU_VI.csv.zip", "EJSCREEN_2023_BG_with_AS_CNMI_GU_VI.csv", None),
    (2024, "data/ejscreen_2024.zip", "2024/2.32_August_UseMe/EJSCREEN_2024_BG_with_AS_CNMI_GU_VI.csv.zip", "EJSCREEN_2024_BG_with_AS_CNMI_GU_VI.csv", None),
]

INDICATORS = [
    "pm25",
    "ozone",
    "diesel_pm",
    "traffic_proximity",
    "lead_paint",
    "superfund_proximity",
    "wastewater_discharge",
    "demographic_index",
    "low_income_pct",
    "people_of_color_pct",
]


def col_map(year: int) -> dict[str, str]:
    if year == 2015:
        return {
            "geoid": "FIPS",
            "pop": "pop",
            "pm25": "pm",
            "ozone": "o3",
            "diesel_pm": "dpm",
            "traffic_proximity": "traffic.score",
            "lead_paint": "pctpre1960",
            "superfund_proximity": "proximity.npl",
            "wastewater_discharge": "proximity.npdes",
            "demographic_index": "VDI.eo",
            "low_income_pct": "pctlowinc",
            "people_of_color_pct": "pctmin",
        }
    if year <= 2022:
        return {
            "geoid": "ID",
            "pop": "ACSTOTPOP",
            "pm25": "PM25",
            "ozone": "OZONE",
            "diesel_pm": "DSLPM",
            "traffic_proximity": "PTRAF",
            "lead_paint": "PRE1960PCT",
            "superfund_proximity": "PNPL",
            "wastewater_discharge": "PWDIS",
            "demographic_index": "VULEOPCT",
            "low_income_pct": "LOWINCPCT",
            "people_of_color_pct": "MINORPCT",
        }
    return {
        "geoid": "ID",
        "pop": "ACSTOTPOP",
        "pm25": "PM25",
        "ozone": "OZONE",
        "diesel_pm": "DSLPM",
        "traffic_proximity": "PTRAF",
        "lead_paint": "PRE1960PCT",
        "superfund_proximity": "PNPL",
        "wastewater_discharge": "PWDIS",
        "demographic_index": "DEMOGIDX_2",
        "low_income_pct": "LOWINCPCT",
        "people_of_color_pct": "PEOPCOLORPCT",
    }


def open_bg_csv_stream(outer_zip: str, inner_zip: str | None, inner_csv: str | None, direct_csv: str | None):
    """Return (file_obj, [contexts_to_close]). file_obj yields raw bytes of the BG CSV."""
    z_outer = zipfile.ZipFile(outer_zip)
    if direct_csv:
        f = z_outer.open(direct_csv)
        return f, [f, z_outer]
    # Inner zip contains the CSV. Read inner zip into BytesIO so zipfile can open it.
    inner_bytes = z_outer.read(inner_zip)
    z_outer.close()
    z_inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
    f = z_inner.open(inner_csv)
    return f, [f, z_inner]


def aggregate_year(year: int) -> pd.DataFrame:
    src = next(s for s in SOURCES if s[0] == year)
    _, outer, inner_zip, inner_csv, direct_csv = src
    cmap = col_map(year)

    print(f"[{year}] opening {outer}", flush=True)
    f, ctxs = open_bg_csv_stream(outer, inner_zip, inner_csv, direct_csv)

    needed_cols = list(cmap.values())
    accum: pd.DataFrame | None = None
    rows_seen = 0
    t0 = time.time()

    try:
        reader = pd.read_csv(
            f,
            chunksize=200_000,
            low_memory=False,
            encoding="latin-1",
            usecols=lambda c: c in needed_cols or c.lstrip("﻿ï»¿") in needed_cols,
            dtype={cmap["geoid"]: str},
            on_bad_lines="warn",
        )
        for chunk in reader:
            chunk.columns = [c.lstrip("﻿ï»¿") for c in chunk.columns]
            rows_seen += len(chunk)

            geoid = chunk[cmap["geoid"]].astype(str).str.strip()
            geoid = geoid.str.zfill(12)
            county = geoid.str[:5]

            pop = pd.to_numeric(chunk[cmap["pop"]], errors="coerce").fillna(0.0)

            part = pd.DataFrame({"_county": county, "_pop": pop})
            for ind in INDICATORS:
                src_col = cmap[ind]
                vals = pd.to_numeric(chunk[src_col], errors="coerce")
                # Some EJSCREEN files use sentinel like -999 for missing.
                vals = vals.where(vals > -900)
                weight = pop.where(vals.notna(), 0.0)
                part[f"_w_{ind}"] = (vals * pop).fillna(0.0)
                part[f"_p_{ind}"] = weight

            # Drop block groups without a valid 5-digit county FIPS.
            part = part[part["_county"].str.len() == 5]
            part = part[part["_county"].str.isdigit()]

            grouped = part.groupby("_county", sort=False).sum(numeric_only=True)
            accum = grouped if accum is None else accum.add(grouped, fill_value=0)

            if rows_seen % 1_000_000 == 0 or rows_seen < 200_001:
                elapsed = time.time() - t0
                print(f"[{year}] {rows_seen:>10,} rows  {elapsed:6.1f}s  counties={len(accum)}", flush=True)
    finally:
        for c in ctxs:
            try:
                c.close()
            except Exception:
                pass

    if accum is None:
        raise RuntimeError(f"No data for {year}")

    out = pd.DataFrame(index=accum.index)
    out["population"] = accum["_pop"]
    for ind in INDICATORS:
        w = accum[f"_w_{ind}"]
        p = accum[f"_p_{ind}"]
        out[ind] = np.where(p > 0, w / p, np.nan)

    out = out.reset_index().rename(columns={"_county": "county_fips"})
    out.insert(0, "year", year)
    print(f"[{year}] done. counties={len(out)} rows_seen={rows_seen:,} elapsed={time.time()-t0:.1f}s", flush=True)
    return out


def main() -> int:
    pieces: list[pd.DataFrame] = []
    for year, *_rest in SOURCES:
        pieces.append(aggregate_year(year))
    final = pd.concat(pieces, ignore_index=True)
    final = final.sort_values(["year", "county_fips"]).reset_index(drop=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(OUTPUT, index=False)
    print(f"\nWrote {OUTPUT}  shape={final.shape}", flush=True)
    print("Columns:", list(final.columns), flush=True)
    print("Years:", sorted(final['year'].unique().tolist()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
