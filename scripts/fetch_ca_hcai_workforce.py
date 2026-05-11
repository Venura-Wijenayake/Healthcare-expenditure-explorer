"""Fetch CA HCAI Health Workforce License Renewal Survey aggregates.

Pulls California Department of Health Care Access and Information (HCAI)
"Physicians Actively Working by Specialty and Activity Hours" — weighted
aggregates from the HCAI Health Workforce License Renewal Survey. Each
licensee is asked to estimate weekly hours spent in five activity
categories (Patient Care / Research / Administration / Training / Other);
HCAI weights survey responses up to all active licensees in the state.

Output: data/ca_hcai_physicians.csv with one row per
(county, specialty, activity_category, activity_hours_bucket).

IMPORTANT — scope narrowing from spec:
    The original task asked for three datasets (physicians + NPs + PAs).
    HCAI does NOT publish "Actively Working by Specialty and Activity
    Hours" datasets for Nurse Practitioners or Physician Assistants.
    Their NP/PA workforce numbers appear only inside cross-cutting
    multi-profession aggregates (Languages, Education, Race/Ethnicity)
    at coarser Region granularity, not the county × specialty structure
    of the physician file. We deliberately do NOT fabricate ca_hcai_
    nurse_practitioners / ca_hcai_physician_assistants from those
    cross-cutting files because the shape and semantics don't match.
    See the PR handoff for details on the recommended pivot.

Source dataset:
    https://data.chhs.ca.gov/dataset/physician-survey
    "Physicians Actively Working by Specialty and Activity Hours"
    Five XLSX resources — one per activity category — combined here.

License: open public data, attribute HCAI.
Refresh: annual (HCAI publishes after each license renewal cycle).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ca_hcai_physicians.csv"
TMP = ROOT / "tmp" / "hcai"

# Five XLSX resources covering the five activity categories. Each has
# the same schema (County, Specialty, "<Activity> Activity", Estimated
# Count); we tag with `activity_category` so they stack cleanly.
RESOURCES: list[tuple[str, str]] = [
    ("Patient Care",
     "https://data.chhs.ca.gov/dataset/58deeba2-8c6b-4f10-a1c1-37549750f28c/"
     "resource/2183fa79-9f97-4556-901e-919726489f28/download/patient-activity-hours.xlsx"),
    ("Research",
     "https://data.chhs.ca.gov/dataset/58deeba2-8c6b-4f10-a1c1-37549750f28c/"
     "resource/47dea241-eaec-41a7-8abe-69ddede36a19/download/research-hours.xlsx"),
    ("Administration",
     "https://data.chhs.ca.gov/dataset/58deeba2-8c6b-4f10-a1c1-37549750f28c/"
     "resource/0e7b06a5-2015-423a-8f36-839a2fbabb40/download/admin-hours.xlsx"),
    ("Training",
     "https://data.chhs.ca.gov/dataset/58deeba2-8c6b-4f10-a1c1-37549750f28c/"
     "resource/c8a35ae6-6a1f-4506-9333-39eb068d8142/download/training-hours.xlsx"),
    ("Other",
     "https://data.chhs.ca.gov/dataset/58deeba2-8c6b-4f10-a1c1-37549750f28c/"
     "resource/bba0ad3b-b683-4ffa-8bfb-9829c8d097f2/download/other-hours.xlsx"),
]


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"  GET {url.rsplit('/', 1)[-1]}")
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
    return dest


def read_activity_xlsx(path: Path, activity_category: str) -> pd.DataFrame:
    """Read one activity-category XLSX and normalize column names.

    Each file ships with a sheet named after its activity (e.g.
    "Patient Activity Hours"); the per-activity bucket column is also
    named uniquely (e.g. "Patient Activity"). Normalize to a shared
    schema so the frames stack.
    """
    xl = pd.ExcelFile(path)
    # The data sheet is the first one (not "Metadata"). Pick by name.
    data_sheet = next(s for s in xl.sheet_names if s != "Metadata")
    df = pd.read_excel(xl, sheet_name=data_sheet)
    # Find the per-activity bucket column — anything other than the
    # three stable columns is the activity-hours bucket.
    stable = {"County", "Specialty", "Estimated Count"}
    bucket_col = next(c for c in df.columns if c not in stable)
    df = df.rename(columns={bucket_col: "activity_hours_bucket"})
    df["activity_category"] = activity_category
    df = df.rename(columns={
        "County": "county",
        "Specialty": "specialty",
        "Estimated Count": "estimated_count",
    })
    df["state"] = "CA"
    return df[["state", "county", "specialty", "activity_category",
               "activity_hours_bucket", "estimated_count"]]


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {len(RESOURCES)} CA HCAI physician activity XLSX files")
    frames: list[pd.DataFrame] = []
    for activity, url in RESOURCES:
        fname = url.rsplit("/", 1)[-1]
        path = TMP / fname
        download(url, path)
        df = read_activity_xlsx(path, activity)
        print(f"  {activity:14}  rows={len(df):,}")
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    combined["estimated_count"] = pd.to_numeric(
        combined["estimated_count"], errors="coerce"
    ).fillna(0).astype("int64")
    combined = combined.sort_values(
        ["county", "specialty", "activity_category", "activity_hours_bucket"]
    ).reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT, index=False)

    total = combined["estimated_count"].sum()
    print(f"\nWrote {OUT} "
          f"({OUT.stat().st_size/1e6:.2f} MB, {len(combined):,} rows)")
    print(f"  total estimated physician-instances (sum across "
          f"activity_category × hours): {total:,}")
    print(f"  counties:   {combined['county'].nunique()}")
    print(f"  specialties: {combined['specialty'].nunique()}")
    print(f"  activity categories: "
          f"{combined['activity_category'].nunique()}  "
          f"({sorted(combined['activity_category'].unique().tolist())})")
    print()
    print("Patient Care only — total physicians by specialty (top 5):")
    pc = combined[combined["activity_category"] == "Patient Care"]
    print(pc.groupby("specialty")["estimated_count"].sum()
            .sort_values(ascending=False).head().to_string())
    print()
    print("Patient Care only — top 5 counties by physician count:")
    print(pc.groupby("county")["estimated_count"].sum()
            .sort_values(ascending=False).head().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
