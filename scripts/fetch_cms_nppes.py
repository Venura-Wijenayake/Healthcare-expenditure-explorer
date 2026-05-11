"""Fetch the CMS NPPES monthly provider directory (V2 format).

NPPES (National Plan and Provider Enumeration System) is the FOIA-disclosable
national provider directory — individual-level records for ~7M healthcare
providers (active + deactivated). It's the foundational dataset for any
"provider supply by state x specialty" analysis and the universal key (NPI)
for joining to claims / quality / Open Payments.

Source:
    https://download.cms.gov/nppes/NPI_Files.html
    File: NPPES_Data_Dissemination_<MONTH>_<YYYY>_V2.zip  (V1 deprecated
    March 2026 — do not use)
    Size: ~1.1 GB zipped, ~10 GB main CSV when extracted

Pipeline:
    1. Scrape the index for the current month's V2 zip.
    2. Stream-download (chunks to disk, no full-file memory load).
    3. Extract the npidata_pfile_<dates>.csv (ignore the Other-Name,
       Practice-Location, and Endpoint reference files — those are
       separate ingestions if/when we need them).
    4. DuckDB streaming COPY with schema reduction — pulls ~20 of 330
       columns straight into ZSTD-compressed parquet without ever
       materializing the full frame in pandas.
    5. (Optional) upload to R2 + upsert dataset_registry. Use --no-upload
       to stop after the local parquet is produced.

Output: tmp/nppes/cms_nppes.parquet (gitignored). No CSV lands in data/
because the schema-reduced parquet is the canonical artifact; the
full 10GB CSV is intentionally not committed anywhere.

License: FOIA-disclosed public data, attribute CMS.
Refresh: monthly (CMS re-issues the full file each month).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp" / "nppes"
INDEX_URL = "https://download.cms.gov/nppes/NPI_Files.html"
BASE_URL = "https://download.cms.gov/nppes/"

# Schema reduction: ~20 of 330 columns. NPPES uses double-quoted column
# headers with spaces — we map them to snake_case for downstream
# usability. Order matters: this is also the parquet column order.
COLUMN_MAP: list[tuple[str, str]] = [
    ("NPI",                                                                  "npi"),
    ("Entity Type Code",                                                     "entity_type_code"),
    ("Provider Enumeration Date",                                            "enumeration_date"),
    ("Last Update Date",                                                     "last_update_date"),
    ("NPI Deactivation Date",                                                "deactivation_date"),
    ("NPI Reactivation Date",                                                "reactivation_date"),
    ("Provider Last Name (Legal Name)",                                      "provider_last_name"),
    ("Provider First Name",                                                  "provider_first_name"),
    ("Provider Middle Name",                                                 "provider_middle_name"),
    ("Provider Credential Text",                                             "provider_credential_text"),
    ("Provider Organization Name (Legal Business Name)",                     "provider_organization_name"),
    ("Provider Other Organization Name",                                     "provider_other_organization_name"),
    ("Provider First Line Business Practice Location Address",               "practice_address_line1"),
    ("Provider Business Practice Location Address City Name",                "practice_city"),
    ("Provider Business Practice Location Address State Name",               "practice_state"),
    ("Provider Business Practice Location Address Postal Code",              "practice_postal_code"),
    ("Provider Business Practice Location Address Country Code (If outside U.S.)", "practice_country_code"),
    ("Healthcare Provider Taxonomy Code_1",                                  "taxonomy_code"),
    ("Healthcare Provider Primary Taxonomy Switch_1",                        "taxonomy_primary_switch"),
    ("Provider License Number_1",                                            "license_number"),
    ("Provider License Number State Code_1",                                 "license_state_code"),
    # NPPES historically called this "Provider Sex Code" in the file; many
    # CMS docs call it "Provider Gender Code". The header is the former.
    ("Provider Sex Code",                                                    "provider_sex_code"),
    ("Is Sole Proprietor",                                                   "is_sole_proprietor"),
]


def find_latest_monthly_zip(html: str) -> str:
    """Return the URL of the most recent monthly V2 zip.

    The index page lists one monthly file per month plus several weekly
    incrementals. We want the monthly only (full-replacement file).
    """
    pattern = re.compile(
        r'NPPES_Data_Dissemination_([A-Z][a-z]+)_(\d{4})_V2\.zip',
    )
    matches = sorted(set(pattern.findall(html)),
                     key=lambda m: (int(m[1]), _month_index(m[0])),
                     reverse=True)
    if not matches:
        raise RuntimeError("No monthly V2 zip matched on the NPI_Files index page")
    month, year = matches[0]
    name = f"NPPES_Data_Dissemination_{month}_{year}_V2.zip"
    return BASE_URL + name, name


def _month_index(month_name: str) -> int:
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    try:
        return months.index(month_name) + 1
    except ValueError:
        return 0


def stream_download(url: str, dest: Path, chunk: int = 4 * 1024 * 1024) -> int:
    """Stream a large URL to dest in 4 MB chunks. Returns bytes written.

    Chunks keep memory flat; the response body is never materialized
    fully in memory. requests.iter_content already releases each chunk
    once it lands on disk.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  cached: {dest} ({dest.stat().st_size/1e9:.2f} GB)")
        return dest.stat().st_size
    total = 0
    last_print = 0
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for buf in r.iter_content(chunk_size=chunk):
                if not buf:
                    continue
                f.write(buf)
                total += len(buf)
                if total - last_print >= 100 * 1024 * 1024:  # progress every 100 MB
                    print(f"    downloaded {total/1e9:.2f} GB...")
                    last_print = total
    print(f"  wrote {dest} ({total/1e9:.2f} GB)")
    return total


def extract_main_csv(zip_path: Path, dest_dir: Path) -> Path:
    """Pull the npidata_pfile_*.csv out of the zip; skip ref files.

    The zip also contains othername_pfile, pl_pfile (practice locations),
    and endpoint_pfile reference files we don't need for v1.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        candidates = [
            n for n in z.namelist()
            if n.startswith("npidata_pfile_") and n.endswith(".csv")
            and "fileheader" not in n.lower()
        ]
        if not candidates:
            raise RuntimeError(f"No npidata_pfile_*.csv in {zip_path}; "
                               f"namelist={z.namelist()[:10]}")
        # Pick the largest; the smaller one (if any) is a header preview.
        target = max(candidates, key=lambda n: z.getinfo(n).file_size)
        out = dest_dir / Path(target).name
        if out.exists() and out.stat().st_size == z.getinfo(target).file_size:
            print(f"  cached: {out} ({out.stat().st_size/1e9:.2f} GB)")
            return out
        print(f"  extracting {target} ({z.getinfo(target).file_size/1e9:.2f} GB)")
        with z.open(target) as src, out.open("wb") as f:
            shutil.copyfileobj(src, f, length=4 * 1024 * 1024)
    print(f"  wrote {out} ({out.stat().st_size/1e9:.2f} GB)")
    return out


def csv_to_parquet(csv_path: Path, parquet_path: Path) -> int:
    """DuckDB streaming COPY: ~330-col CSV -> ~20-col ZSTD parquet.

    `all_varchar=true` on the reader avoids dtype-inference surprises
    across 7M rows (some columns have legitimately-empty values that
    DuckDB would otherwise type-flip on); downstream consumers can cast
    as needed.

    DuckDB streams chunks through the projection — peak memory is small
    and bounded by the engine's vector size, not the full 10 GB CSV.
    """
    import duckdb

    select_clauses = [
        f'"{src}" AS {dst}' for src, dst in COLUMN_MAP
    ]
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_uri = str(csv_path).replace("\\", "/")
    pq_uri = str(parquet_path).replace("\\", "/")

    sql = f"""
    COPY (
        SELECT {", ".join(select_clauses)}
        FROM read_csv_auto(
            '{csv_uri}',
            all_varchar=true,
            sample_size=10000,
            parallel=true,
            ignore_errors=false
        )
    ) TO '{pq_uri}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con = duckdb.connect(":memory:")
    # Bound memory to ~4 GB so the streaming COPY doesn't try to build
    # a giant hash partition in RAM even if a downstream reorder happens.
    con.execute("PRAGMA memory_limit='4GB'")
    con.execute(sql)
    n = con.execute(
        "SELECT COUNT(*) FROM read_parquet(?)", [pq_uri]
    ).fetchone()[0]
    return int(n)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-upload", action="store_true",
                   help="Build local parquet only; skip R2 upload + registry upsert.")
    p.add_argument("--keep-csv", action="store_true",
                   help="Keep the extracted 10 GB CSV after parquet conversion. "
                        "Default cleans up to reclaim disk.")
    args = p.parse_args(argv)

    TMP.mkdir(parents=True, exist_ok=True)

    print("[1/5] Scraping NPPES index for the latest V2 monthly zip")
    html = requests.get(INDEX_URL, timeout=60).text
    url, fname = find_latest_monthly_zip(html)
    print(f"      latest: {fname}")
    print(f"      url:    {url}")

    zip_path = TMP / fname
    print(f"\n[2/5] Stream-downloading the zip")
    stream_download(url, zip_path)

    print(f"\n[3/5] Extracting npidata_pfile_*.csv")
    csv_path = extract_main_csv(zip_path, TMP)

    parquet_path = TMP / "cms_nppes.parquet"
    print(f"\n[4/5] Streaming CSV -> ZSTD parquet (schema-reduced to {len(COLUMN_MAP)} columns)")
    rows = csv_to_parquet(csv_path, parquet_path)
    pq_mb = parquet_path.stat().st_size / 1e6
    csv_gb = csv_path.stat().st_size / 1e9
    print(f"      rows:    {rows:,}")
    print(f"      CSV:     {csv_gb:.2f} GB")
    print(f"      Parquet: {pq_mb:.1f} MB ({100*(1-pq_mb*1e6/csv_path.stat().st_size):.0f}% reduction)")

    if not args.keep_csv:
        print(f"\n      cleaning up CSV {csv_path.name} to reclaim disk")
        csv_path.unlink()

    if args.no_upload:
        print(f"\n[5/5] --no-upload set; parquet at {parquet_path}")
        return 0

    print(f"\n[5/5] Uploading to R2 + upserting dataset_registry")
    sys.path.insert(0, str(ROOT))
    from infra import load_secrets, get_postgres_conn, make_r2
    from scripts.migrate_to_neon_r2 import upsert_dataset_registry

    secrets = load_secrets()
    r2 = make_r2(secrets)
    bucket = secrets.r2_bucket_name
    parquet_key = "cms_nppes.parquet"

    print(f"      -> r2://{bucket}/{parquet_key}")
    # boto3 's3 transfer manager auto-multipart-uploads for files >8MB;
    # we just hand it the file path.
    r2.upload_file(str(parquet_path), bucket, parquet_key,
                   ExtraArgs={"ContentType": "application/vnd.apache.parquet"})

    conn = get_postgres_conn(secrets)
    try:
        upsert_dataset_registry(
            conn, dataset_key="cms_nppes", storage_location="r2",
            granularity="individual_provider", parquet_path=parquet_key,
            year_start=None, year_end=None, row_count=int(rows),
        )
    finally:
        conn.close()
    print(f"      dataset_registry: row_count={rows:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
