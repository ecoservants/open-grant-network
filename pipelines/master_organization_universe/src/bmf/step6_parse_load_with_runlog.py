import os
import re
import traceback
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# MySQL connection parts from .env
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB = os.getenv("MYSQL_DB", "grant_tracker")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

# EO BMF settings from .env
DOWNLOAD_DIR = os.getenv("BMF_DOWNLOAD_DIR", "data/raw/bmf")
POSTING_DATE = (os.getenv("BMF_POSTING_DATE") or "").strip()
SUBSECTION_TARGETS = set(
    s.strip() for s in (os.getenv("BMF_SUBSECTION_TARGET") or "03,04").split(",") if s.strip()
)
EXCLUDED_STATUS = set(
    s.strip() for s in (os.getenv("BMF_EXCLUDED_STATUS_CODES") or "").split(",") if s.strip()
)

PIPELINE_NAME = "bmf_master"
SOURCE_NAME = "irs_eo_bmf"

if not POSTING_DATE:
    raise ValueError("BMF_POSTING_DATE is missing in .env, example: 2026-02-10")

DATA_FOLDER = os.path.join(DOWNLOAD_DIR, POSTING_DATE)
if not os.path.isdir(DATA_FOLDER):
    raise FileNotFoundError(f"Data folder not found: {DATA_FOLDER}")

# Build SQLAlchemy URL safely (password may contain special characters like @)
safe_pw = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine = create_engine(MYSQL_URL)

EIN_REGEX = re.compile(r"^\d{9}$")


def normalize_ein(val):
    if pd.isna(val):
        return None
    s = str(val).strip().replace("-", "")
    return s if EIN_REGEX.match(s) else None


def normalize_name(val):
    if pd.isna(val):
        return ""
    return re.sub(r"\s+", " ", str(val).strip()).upper()


def normalize_state(val):
    if pd.isna(val):
        return None
    s = str(val).strip().upper()
    return s if len(s) == 2 else None


def parse_ruling_date(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    try:
        return datetime.strptime(s, "%Y%m").date()
    except Exception:
        return None


def safe_get_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype="object")


def create_run_row() -> int:
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                INSERT INTO pipeline_runs (pipeline_name, source_name, source_posting_date, status)
                VALUES (:p, :s, :d, 'STARTED')
            """),
            {"p": PIPELINE_NAME, "s": SOURCE_NAME, "d": POSTING_DATE},
        )
        run_id = res.lastrowid
        if run_id is None:
            run_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        if run_id is None:
            raise RuntimeError("Could not determine run_id after INSERT into pipeline_runs")
        return int(run_id)


def mark_run_failed(run_id: int, err_msg: str):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs
                SET status='FAILED',
                    finished_at=CURRENT_TIMESTAMP,
                    error_message=:e
                WHERE run_id=:rid
            """),
            {"rid": run_id, "e": err_msg[:65000]},
        )


def mark_run_success(
    run_id: int,
    rows_read: int,
    rows_valid_ein: int,
    rows_after_filter: int,
    rows_excluded: int,
    rows_upserted: int,
    distinct_ein_loaded: int,
):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs
                SET status='SUCCESS',
                    finished_at=CURRENT_TIMESTAMP,
                    rows_read=:rr,
                    rows_valid_ein=:rve,
                    rows_after_filter=:raf,
                    rows_excluded=:rex,
                    rows_upserted=:rup,
                    distinct_ein_loaded=:ded
                WHERE run_id=:rid
            """),
            {
                "rid": run_id,
                "rr": rows_read,
                "rve": rows_valid_ein,
                "raf": rows_after_filter,
                "rex": rows_excluded,
                "rup": rows_upserted,
                "ded": distinct_ein_loaded,
            },
        )


def process_file(path: str):
    total_read = 0
    total_valid_ein = 0
    total_after_filter = 0
    total_excluded = 0

    for chunk in pd.read_csv(path, dtype=str, chunksize=100_000, low_memory=False):
        total_read += len(chunk)
        chunk.columns = [c.strip().upper() for c in chunk.columns]

        out = pd.DataFrame(index=chunk.index)
        out["ein"] = safe_get_series(chunk, "EIN").apply(normalize_ein)
        out["org_name"] = safe_get_series(chunk, "NAME").apply(normalize_name)

        out["street"] = safe_get_series(chunk, "STREET").replace({"nan": ""})
        out["city"] = safe_get_series(chunk, "CITY").replace({"nan": ""})
        out["state"] = safe_get_series(chunk, "STATE").apply(normalize_state)
        out["zip"] = safe_get_series(chunk, "ZIP").replace({"nan": ""})

        out["subsection_code"] = safe_get_series(chunk, "SUBSECTION").str.zfill(2)
        out["foundation_code"] = safe_get_series(chunk, "FOUNDATION").str.zfill(2)
        out["ntee_code"] = safe_get_series(chunk, "NTEE_CD").replace({"nan": ""})
        out["status_code"] = safe_get_series(chunk, "STATUS").replace({"nan": ""})
        out["ruling_date"] = safe_get_series(chunk, "RULING_DATE").apply(parse_ruling_date)

        out = out[out["ein"].notna()]
        total_valid_ein += len(out)

        out = out[out["subsection_code"].isin(SUBSECTION_TARGETS)]

        before = len(out)
        if EXCLUDED_STATUS:
            out = out[~out["status_code"].isin(EXCLUDED_STATUS)]
        total_excluded += before - len(out)

        total_after_filter += len(out)

        out["source_file"] = os.path.basename(path)
        out["source_posting_date"] = POSTING_DATE

        # Reduced chunksize from 5000 to 1000 to avoid MySQL max packet
        # size errors when loading all 50 states in production mode
        out.to_sql(
            "organizations_master_staging",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=100,
        )

    return total_read, total_valid_ein, total_after_filter, total_excluded


def run_pipeline():
    run_id = create_run_row()

    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE organizations_master_staging"))

        totals = [0, 0, 0, 0]

        csv_files = sorted([f for f in os.listdir(DATA_FOLDER) if f.lower().endswith(".csv") and not f.lower().startswith("eo1") and not f.lower().startswith("eo2") and not f.lower().startswith("eo3") and not f.lower().startswith("eo4")])
        if not csv_files:
            raise RuntimeError(f"No CSV files found in {DATA_FOLDER}")

        for file in csv_files:
            print("Processing:", file)
            r = process_file(os.path.join(DATA_FOLDER, file))
            totals = [a + b for a, b in zip(totals, r)]

        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO organizations_master (
                    ein, org_name, street, city, state, zip,
                    subsection_code, foundation_code, ntee_code, status_code, ruling_date,
                    source_file, source_posting_date, created_at, updated_at
                )
                SELECT
                    ein, org_name, street, city, state, zip,
                    subsection_code, foundation_code, ntee_code, status_code, ruling_date,
                    source_file, source_posting_date, created_at, updated_at
                FROM organizations_master_staging
                ON DUPLICATE KEY UPDATE
                    org_name = VALUES(org_name),
                    street = VALUES(street),
                    city = VALUES(city),
                    state = VALUES(state),
                    zip = VALUES(zip),
                    subsection_code = VALUES(subsection_code),
                    foundation_code = VALUES(foundation_code),
                    ntee_code = VALUES(ntee_code),
                    status_code = VALUES(status_code),
                    ruling_date = VALUES(ruling_date),
                    source_file = VALUES(source_file),
                    source_posting_date = VALUES(source_posting_date),
                    updated_at = CURRENT_TIMESTAMP
            """))

            rc = result.rowcount
            rows_upserted = int(rc) if isinstance(rc, int) else 0

            ded = conn.execute(text("SELECT COUNT(*) FROM organizations_master")).scalar()
            distinct_ein_loaded = int(ded) if isinstance(ded, (int, float)) else 0

        mark_run_success(
            run_id=run_id,
            rows_read=int(totals[0]),
            rows_valid_ein=int(totals[1]),
            rows_after_filter=int(totals[2]),
            rows_excluded=int(totals[3]),
            rows_upserted=rows_upserted,
            distinct_ein_loaded=distinct_ein_loaded,
        )

        print("RUN_ID:", run_id)
        print("Rows read:", totals[0])
        print("Valid EIN:", totals[1])
        print("After filters:", totals[2])
        print("Excluded:", totals[3])
        print("Upsert rowcount:", rows_upserted)
        print("Master distinct EIN:", distinct_ein_loaded)
        print("Done.")

    except Exception:
        err_msg = traceback.format_exc()
        mark_run_failed(run_id, err_msg)
        print("FAILED. RUN_ID:", run_id)
        print(err_msg)
        raise


if __name__ == "__main__":
    run_pipeline()
