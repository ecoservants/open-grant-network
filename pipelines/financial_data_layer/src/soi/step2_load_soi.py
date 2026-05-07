import os
import re
import traceback
import zipfile
from io import BytesIO
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ── DB config ──────────────────────────────────────────────────────────────
MYSQL_HOST     = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT     = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB       = os.getenv("MYSQL_DB", "grant_tracker")
MYSQL_USER     = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

# ── SOI config ─────────────────────────────────────────────────────────────
SOI_DOWNLOAD_DIR = os.getenv("SOI_DOWNLOAD_DIR", "data/raw/soi")
SOI_TAX_YEARS    = os.getenv("SOI_TAX_YEARS", "2021,2022,2023").strip()

PIPELINE_NAME = "soi_financials"
SOURCE_NAME   = "irs_soi_extract"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)

EIN_REGEX = re.compile(r"^\d{9}$")

# ── Column candidates ──────────────────────────────────────────────────────
# IRS SOI column names vary by year — we try each candidate in order
SOI_COL_CANDIDATES = {
    "total_assets":        ["TOTASSETSEND", "TOTASTEND", "HLDASSETSINTERMPERMCD"],
    "total_revenue":       ["TOTREVENUE",   "TOTREVNUE", "TOTREV"],
    "total_contributions": ["TOTCNTRBGFTS", "TOTCONTRIB", "TOTCNTRBS"],
    "grants_paid":         ["GRNTSPAID",    "GRNTSTOTPD", "TOTGRNTS"],
    "tax_year":            ["TAX_PD",       "TAX_PERIOD", "TAXYEAR"],
}


# ── helpers ────────────────────────────────────────────────────────────────
def resolve_col(df_cols: list, candidates: list) -> str | None:
    for c in candidates:
        if c in df_cols:
            return c
    return None


def normalize_ein(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip().replace("-", "").zfill(9)
    return s if EIN_REGEX.match(s) else None


def safe_bigint(val):
    try:
        v = float(val)
        return int(v) if not pd.isna(v) else None
    except Exception:
        return None


def tax_year_from_period(val) -> int | None:
    """TAX_PD is YYYYMM — return the year portion."""
    try:
        s = str(val).strip()
        if len(s) >= 4:
            yr = int(s[:4])
            if 1990 <= yr <= 2099:
                return yr
    except Exception:
        pass
    return None


def open_soi_csv(zip_path: str) -> pd.DataFrame:
    """Extract CSV from zip and return as DataFrame."""
    if zip_path.lower().endswith(".zip"):
        with zipfile.ZipFile(zip_path, "r") as z:
            csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise RuntimeError(f"No CSV found inside {zip_path}")
            print(f"  Reading {csv_names[0]} from zip...")
            with z.open(csv_names[0]) as f:
                return pd.read_csv(BytesIO(f.read()), dtype=str, low_memory=False)
    else:
        return pd.read_csv(zip_path, dtype=str, low_memory=False)


def process_soi_file(zip_path: str, tax_year: int) -> list[dict]:
    df = open_soi_csv(zip_path)
    df.columns = [c.strip().upper() for c in df.columns]

    cols = list(df.columns)
    print(f"  Total rows   : {len(df)}")
    print(f"  First 15 cols: {cols[:15]}")

    # Resolve actual column names for this year's file
    col_assets  = resolve_col(cols, SOI_COL_CANDIDATES["total_assets"])
    col_revenue = resolve_col(cols, SOI_COL_CANDIDATES["total_revenue"])
    col_contrib = resolve_col(cols, SOI_COL_CANDIDATES["total_contributions"])
    col_grants  = resolve_col(cols, SOI_COL_CANDIDATES["grants_paid"])
    col_taxyear = resolve_col(cols, SOI_COL_CANDIDATES["tax_year"])

    print(f"  Column map   → assets:{col_assets} | revenue:{col_revenue} | "
          f"contrib:{col_contrib} | grants:{col_grants} | taxyear:{col_taxyear}")

    # Normalize EIN — vectorized
    out = pd.DataFrame()
    out["ein"] = df["EIN"].apply(normalize_ein)
    out = out[out["ein"].notna()].copy()
    print(f"  Valid EINs   : {len(out)}")

    # Tax year
    if col_taxyear:
        out["tax_year"] = (
            df.loc[out.index, col_taxyear]
            .apply(tax_year_from_period)
            .fillna(tax_year)
            .astype(int)
        )
    else:
        out["tax_year"] = tax_year

    # Financial columns
    out["total_assets"]        = df.loc[out.index, col_assets].apply(safe_bigint)  if col_assets  else None
    out["total_revenue"]       = df.loc[out.index, col_revenue].apply(safe_bigint) if col_revenue else None
    out["total_contributions"] = df.loc[out.index, col_contrib].apply(safe_bigint) if col_contrib else None
    out["grants_paid"]         = df.loc[out.index, col_grants].apply(safe_bigint)  if col_grants  else None
    out["source_file"]         = os.path.basename(zip_path)
    out["source_posting_date"] = None

    return out.to_dict("records")


# ── run log helpers ────────────────────────────────────────────────────────
def create_run_row(year: int) -> int:
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                INSERT INTO pipeline_runs
                  (pipeline_name, source_name, source_posting_date, status)
                VALUES (:p, :s, :d, 'STARTED')
            """),
            {"p": PIPELINE_NAME, "s": SOURCE_NAME, "d": f"{year}-12-31"},
        )
        run_id = res.lastrowid
        if run_id is None:
            run_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(run_id)


def mark_success(run_id: int, rows_read: int, rows_upserted: int):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs SET
                  status='SUCCESS', finished_at=CURRENT_TIMESTAMP,
                  rows_read=:rr, rows_upserted=:ru
                WHERE run_id=:rid
            """),
            {"rid": run_id, "rr": rows_read, "ru": rows_upserted},
        )


def mark_failed(run_id: int, err: str):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs SET
                  status='FAILED', finished_at=CURRENT_TIMESTAMP,
                  error_message=:e
                WHERE run_id=:rid
            """),
            {"rid": run_id, "e": err[:65000]},
        )


# ── upsert ─────────────────────────────────────────────────────────────────
def upsert_financials(rows: list[dict]) -> int:
    if not rows:
        return 0

    df = pd.DataFrame(rows)

    # Filter to only EINs that exist in organizations_master
    with engine.connect() as conn:
        master_eins = pd.read_sql(text("SELECT ein FROM organizations_master"), conn)

    df = df[df["ein"].isin(master_eins["ein"])].copy()
    print(f"  After master EIN filter       : {len(df)} rows")

    if df.empty:
        print("  No matching EINs — skipping upsert.")
        return 0

    # Deduplicate — keep most recent tax year per EIN
    df = df.sort_values("tax_year", ascending=False).drop_duplicates(
        subset=["ein"], keep="first"
    )
    print(f"  After dedup (latest tax year) : {len(df)} rows")

    # Truncate staging and load
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE organization_financials_staging"))

    df.to_sql(
        "organization_financials_staging",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )

    # Upsert staging → master using alias to avoid ambiguous column names
    with engine.begin() as conn:
        conn.execute(text("SET foreign_key_checks = 0"))
        result = conn.execute(text("""
            INSERT INTO organization_financials (
                ein, total_assets, total_revenue, total_contributions,
                grants_paid, tax_year, source_file, source_posting_date,
                created_at, updated_at
            )
            SELECT
                s.ein, s.total_assets, s.total_revenue, s.total_contributions,
                s.grants_paid, s.tax_year, s.source_file, s.source_posting_date,
                s.created_at, s.updated_at
            FROM organization_financials_staging s
            ON DUPLICATE KEY UPDATE
                total_assets        = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.total_assets,        organization_financials.total_assets),
                total_revenue       = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.total_revenue,       organization_financials.total_revenue),
                total_contributions = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.total_contributions, organization_financials.total_contributions),
                grants_paid         = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.grants_paid,         organization_financials.grants_paid),
                tax_year            = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.tax_year,            organization_financials.tax_year),
                source_file         = IF(s.tax_year >= IFNULL(organization_financials.tax_year, 0), s.source_file,         organization_financials.source_file),
                updated_at          = CURRENT_TIMESTAMP
        """))
        conn.execute(text("SET foreign_key_checks = 1"))
        return result.rowcount or 0


# ── main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    target_years = sorted(
        int(y.strip()) for y in SOI_TAX_YEARS.split(",") if y.strip()
    )
    print(f"SOI pipeline starting — years: {target_years}")

    for year in target_years:
        zip_path = None
        for ext in (".zip", ".csv"):
            candidate = os.path.join(SOI_DOWNLOAD_DIR, f"soi_{year}{ext}")
            if os.path.exists(candidate):
                zip_path = candidate
                break

        if not zip_path:
            print(f"SKIP: no file found for year {year} in {SOI_DOWNLOAD_DIR}")
            continue

        print(f"\n── Year {year}: {zip_path} ──")
        run_id = create_run_row(year)

        try:
            rows = process_soi_file(zip_path, year)
            print(f"  Parsed {len(rows)} valid EIN rows")

            upserted = upsert_financials(rows)
            print(f"  Upserted {upserted} rows into organization_financials")

            mark_success(run_id, rows_read=len(rows), rows_upserted=upserted)
            print(f"  RUN_ID {run_id} → SUCCESS")

        except Exception:
            err = traceback.format_exc()
            mark_failed(run_id, err)
            print(f"  RUN_ID {run_id} → FAILED")
            print(err)
            raise

    # Summary
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM organization_financials")
        ).scalar()
        with_grants = conn.execute(
            text("SELECT COUNT(*) FROM organization_financials WHERE grants_paid > 0")
        ).scalar()
        with_assets = conn.execute(
            text("SELECT COUNT(*) FROM organization_financials WHERE total_assets > 0")
        ).scalar()

    print(f"\n── Summary ──────────────────────────────")
    print(f"  Total rows in organization_financials : {total}")
    print(f"  Rows with grants_paid > 0             : {with_grants}")
    print(f"  Rows with total_assets > 0            : {with_assets}")
    print("Done.")


if __name__ == "__main__":
    run_pipeline()
