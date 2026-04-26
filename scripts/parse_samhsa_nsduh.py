"""Parse the 41 SAMHSA NSDUH 2022-2023 state-prevalence CSV tables into one tidy CSV.

Each input table has 4-5 metadata header rows, then a column-header row whose
columns alternate (group)-Estimate / CI-Lower / CI-Upper. Some tables vary in
age groups; one table (Tab23) has measure-named groups instead of age bands.
Output is long-format:
    table_id, measure, state, group, estimate_pct, ci_lower_pct, ci_upper_pct
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

SRC_DIR = Path("data/_samhsa_tmp")
OUTPUT = Path("data/samhsa_nsduh.csv")
YEARS = "2022_2023"


def parse_pct(s):
    if s is None:
        return None
    s = str(s).strip().rstrip("%").replace(",", "")
    if s == "" or s == "*" or s.lower() in {"na", "nan", "n/a"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_header_row(rows: list[list[str]]) -> int | None:
    for i, r in enumerate(rows[:15]):
        cells = [c.strip().lower() for c in r]
        if "state" in cells and any("estimate" in c for c in cells):
            return i
    return None


def extract_measure(title: str) -> str:
    if title is None:
        return ""
    m = re.match(r"\s*Table\s+\d+[\.:\s]\s*(.+?)(?:\s*[:;,]\s*Among|\s*[:;,]\s*by\s|\s*Annual\s|$)", title, flags=re.IGNORECASE)
    return (m.group(1) if m else title).strip()


def parse_columns(header: list[str]) -> list[tuple[str, str]]:
    """Return list of (group_label, kind) for each column. kind in {state, est, lo, hi, order, other}."""
    out = []
    for c in header:
        c0 = c.strip()
        cl = c0.lower()
        if cl in {"order", "rank"}:
            out.append(("", "order"))
        elif cl == "state":
            out.append(("", "state"))
        elif "(lower)" in cl or "ci (lower)" in cl or "lower)" in cl:
            grp = re.sub(r"\s*95%?\s*CI\s*\(?Lower\)?", "", c0, flags=re.IGNORECASE).strip()
            out.append((grp, "lo"))
        elif "(upper)" in cl or "ci (upper)" in cl or "upper)" in cl:
            grp = re.sub(r"\s*95%?\s*CI\s*\(?Upper\)?", "", c0, flags=re.IGNORECASE).strip()
            out.append((grp, "hi"))
        elif "estimate" in cl:
            grp = re.sub(r"\s*\(?Estimate\)?\s*", "", c0, flags=re.IGNORECASE).strip()
            out.append((grp, "est"))
        else:
            out.append((c0, "other"))
    return out


def parse_table(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="latin-1", newline="") as f:
        rows = list(csv.reader(f))
    title = rows[0][0] if rows and rows[0] else ""
    measure = extract_measure(title)
    hdr_idx = find_header_row(rows)
    if hdr_idx is None:
        return pd.DataFrame()
    header = rows[hdr_idx]
    col_meta = parse_columns(header)

    state_col = next((i for i, m in enumerate(col_meta) if m[1] == "state"), None)
    if state_col is None:
        return pd.DataFrame()

    # Group estimate/lo/hi columns by group label
    by_group: dict[str, dict[str, int]] = {}
    for i, (grp, kind) in enumerate(col_meta):
        if kind in {"est", "lo", "hi"}:
            by_group.setdefault(grp, {})[kind] = i

    records = []
    for r in rows[hdr_idx + 1 :]:
        if not r or len(r) <= state_col:
            continue
        state = r[state_col].strip()
        if not state or state.lower().startswith("note") or state.lower().startswith("source"):
            continue
        for grp, idx_map in by_group.items():
            est = parse_pct(r[idx_map["est"]]) if "est" in idx_map and idx_map["est"] < len(r) else None
            lo = parse_pct(r[idx_map["lo"]]) if "lo" in idx_map and idx_map["lo"] < len(r) else None
            hi = parse_pct(r[idx_map["hi"]]) if "hi" in idx_map and idx_map["hi"] < len(r) else None
            if est is None and lo is None and hi is None:
                continue
            records.append({
                "table_id": path.stem.replace("NSDUHsaeExcelTab", "Tab").replace("-2023", ""),
                "measure": measure,
                "state": state,
                "group": grp,
                "estimate_pct": est,
                "ci_lower_pct": lo,
                "ci_upper_pct": hi,
            })
    return pd.DataFrame(records)


def main() -> None:
    files = sorted(SRC_DIR.glob("NSDUHsaeExcelTab*-2023.csv"))
    pieces = [parse_table(f) for f in files]
    final = pd.concat(pieces, ignore_index=True)
    final.insert(0, "years", YEARS)
    final = final.sort_values(["table_id", "state", "group"]).reset_index(drop=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(OUTPUT, index=False)
    print(f"Wrote {OUTPUT}  shape={final.shape}")
    print("Columns:", list(final.columns))
    print("Tables:", final["table_id"].nunique(), "distinct measures:", final["measure"].nunique())
    print("Distinct states/regions:", final["state"].nunique())
    print("Distinct groups:", sorted(final["group"].unique().tolist())[:20])


if __name__ == "__main__":
    main()
