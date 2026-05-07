import os
import re
import time
import traceback
from urllib.parse import quote_plus

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ── DB config ──────────────────────────────────────────────────────────────
MYSQL_HOST     = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT     = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB       = os.getenv("MYSQL_DB", "grant_tracker")
MYSQL_USER     = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

# ── FAC config ─────────────────────────────────────────────────────────────
FAC_DOWNLOAD_DIR = os.getenv("FAC_DOWNLOAD_DIR", "data/raw/fac")
FAC_API_KEY      = os.getenv("FAC_API_KEY", "")
FAC_API_BASE     = "https://api.fac.gov"
FAC_GENERAL_URL  = f"{FAC_API_BASE}/general"

PIPELINE_NAME = "fac_audit_flags"
SOURCE_NAME   = "federal_audit_clearinghouse"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)

EIN_REGEX = re.compile(r"^\d{9}$")


# ── helpers ────────────────────────────────────────────────────────────────
def normalize_ein(val) -> str | None:
    if not val:
        return None
    s = str(val).strip().replace("-", "").zfill(9)
    return s if EIN_REGEX.match(s) else None


def safe_bigint(val) -> int | None:
    try:
        v = float(str(val).replace(",", ""))
        return int(v) if v > 0 else None
    except Exception:
        return None


# ── FAC API fetch ──────────────────────────────────────────────────────────
def fetch_fac_data(master_eins: set) -> list[dict]:
    """
    Fetch FAC general audit data via API with proper key.
    Paginates through all results and matches to master EINs.
    """
    if not FAC_API_KEY:
        raise ValueError("FAC_API_KEY not set in .env")

    headers = {
        "X-API-Key": FAC_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    records = []
    limit   = 1000
    offset  = 0
    total_fetched = 0

    print(f"  Using API key: {FAC_API_KEY[:8]}...")
    print(f"  Endpoint: {FAC_GENERAL_URL}")

    while True:
        url = f"{FAC_GENERAL_URL}?limit={limit}&offset={offset}"

        try:
            r = requests.get(url, headers=headers, timeout=60)

            if r.status_code == 200:
                rows = r.json()

                if not rows:
                    print(f"  No more results at offset {offset}")
                    break

                total_fetched += len(rows)

                for row in rows:
                    # EIN field in FAC API
                    ein_raw = (
                        row.get("auditee_ein") or
                        row.get("ein") or
                        row.get("EIN") or ""
                    )
                    ein = normalize_ein(ein_raw)
                    if not ein or ein not in master_eins:
                        continue

                    # Federal expenditure amount
                    fed_exp = safe_bigint(
                        row.get("total_amount_expended") or
                        row.get("federal_expenditures") or
                        row.get("amount_expended") or 0
                    )

                    # Audit year
                    audit_year = None
                    for yr_field in ["audit_year", "fy_end_date", "fiscal_year_end_date"]:
                        val = row.get(yr_field, "")
                        if val:
                            try:
                                audit_year = int(str(val)[:4])
                                break
                            except Exception:
                                pass

                    # Single audit required flag
                    # If they're in FAC they received >$750k federal funds
                    records.append({
                        "ein":                      ein,
                        "receives_federal_funding":  1,
                        "single_audit_required":     1,
                        "federal_expenditure_amount": fed_exp,
                        "audit_year":               audit_year,
                        "source_file":              "fac_api",
                    })

                offset += limit
                matched = len(records)
                print(f"  Offset {offset:,} | Total fetched: {total_fetched:,} | Matched: {matched:,}")

                # If fewer rows than limit returned we're done
                if len(rows) < limit:
                    break

                time.sleep(0.1)

            elif r.status_code == 429:
                print("  Rate limited — waiting 10s...")
                time.sleep(10)

            elif r.status_code == 403:
                print(f"  403 Forbidden — check API key")
                print(f"  Response: {r.text[:200]}")
                break

            else:
                print(f"  HTTP {r.status_code}: {r.text[:200]}")
                break

        except Exception as e:
            print(f"  Exception: {e}")
            time.sleep(5)
            break

    return records


# ── Run log helpers ────────────────────────────────────────────────────────
def create_run_row() -> int:
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                INSERT INTO pipeline_runs (pipeline_name, source_name, status)
                VALUES (:p, :s, 'STARTED')
            """),
            {"p": PIPELINE_NAME, "s": SOURCE_NAME},
        )
        run_id = res.lastrowid or conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(run_id)


def mark_success(run_id: int, rows_read: int, rows_upserted: int):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs SET status='SUCCESS',
                  finished_at=CURRENT_TIMESTAMP,
                  rows_read=:rr, rows_upserted=:ru
                WHERE run_id=:rid
            """),
            {"rid": run_id, "rr": rows_read, "ru": rows_upserted},
        )


def mark_failed(run_id: int, err: str):
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE pipeline_runs SET status='FAILED',
                  finished_at=CURRENT_TIMESTAMP, error_message=:e
                WHERE run_id=:rid
            """),
            {"rid": run_id, "e": err[:65000]},
        )


# ── Upsert ─────────────────────────────────────────────────────────────────
def upsert_flags(records: list[dict]) -> int:
    if not records:
        return 0

    df = pd.DataFrame(records)
    df = df[df["ein"].notna()].copy()

    # Keep highest expenditure per EIN
    df = df.sort_values("federal_expenditure_amount", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["ein"], keep="first")

    if df.empty:
        return 0

    # Truncate and reload
    with engine.begin() as conn:
        conn.execute(text("SET foreign_key_checks = 0"))
        conn.execute(text("TRUNCATE TABLE organization_audit_flags"))
        conn.execute(text("SET foreign_key_checks = 1"))

    df.to_sql(
        "organization_audit_flags",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    return len(df)


# ── Main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    print("FAC audit flags pipeline starting...")
    os.makedirs(FAC_DOWNLOAD_DIR, exist_ok=True)

    # Load master EINs
    with engine.connect() as conn:
        master_df = pd.read_sql(text("SELECT ein FROM organizations_master"), conn)
    master_eins = set(master_df["ein"].tolist())
    print(f"  Master EINs : {len(master_eins):,}")

    run_id = create_run_row()

    try:
        records = fetch_fac_data(master_eins)
        print(f"\n  FAC records matched to master : {len(records):,}")

        if records:
            upserted = upsert_flags(records)
            print(f"  Upserted : {upserted:,} rows into organization_audit_flags")
        else:
            upserted = 0
            print("  No matching FAC records found.")

        mark_success(run_id, rows_read=len(records), rows_upserted=upserted)

        # Summary
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM organization_audit_flags")
            ).scalar()
            fed_orgs = conn.execute(
                text("SELECT COUNT(*) FROM organization_audit_flags WHERE receives_federal_funding = 1")
            ).scalar()
            total_exp = conn.execute(
                text("SELECT SUM(federal_expenditure_amount) FROM organization_audit_flags")
            ).scalar()

        print(f"\n── Summary ──────────────────────────────────")
        print(f"  Rows in organization_audit_flags : {total:,}")
        print(f"  Orgs with federal funding        : {fed_orgs:,}")
        print(f"  Total federal expenditure        : ${(total_exp or 0):,.0f}")
        print(f"  RUN_ID {run_id} → SUCCESS")
        print("Done.")

    except Exception:
        err = traceback.format_exc()
        mark_failed(run_id, err)
        print(f"  RUN_ID {run_id} → FAILED")
        print(err)
        raise


if __name__ == "__main__":
    run_pipeline()
