import json
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

# ── ProPublica config ──────────────────────────────────────────────────────
PROPUBLICA_BASE   = "https://projects.propublica.org/nonprofits/api/v2"
REQUEST_DELAY     = float(os.getenv("PROPUBLICA_DELAY", "0.5"))
MAX_FILINGS       = int(os.getenv("PROPUBLICA_MAX_FILINGS", "3"))
BATCH_SIZE        = int(os.getenv("PROPUBLICA_BATCH_SIZE", "500"))

PIPELINE_NAME = "propublica_filings"
SOURCE_NAME   = "propublica_api"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)


# ── Helpers ────────────────────────────────────────────────────────────────
def safe_int(val) -> int | None:
    try:
        if val is None or val == "":
            return None
        v = int(float(val))
        return v if v != 0 else None
    except Exception:
        return None


def fetch_org(ein: str, retries: int = 3) -> dict | None:
    url = f"{PROPUBLICA_BASE}/organizations/{ein}.json"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                wait = 10 * attempt
                print(f"    Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
        except Exception as e:
            time.sleep(2 * attempt)
    return None


def extract_filings(ein: str, api_response: dict) -> list[dict]:
    """
    Parse ProPublica API response into filing records.
    Confirmed field names from live API response:
      tax_prd_yr  — 4-digit tax year
      totrevenue  — total revenue
      totassetsend — total assets end of year
      totcntrbgfts — total contributions/grants received (best proxy for giving orgs)
      formtype    — 0=990, 1=990EZ, 2=990PF
    Website is on the organization object, not the filing.
    """
    records  = []
    filings  = api_response.get("filings_with_data", [])
    org_data = api_response.get("organization", {})

    # Website from org object
    website = None
    for ws_field in ["website", "url"]:
        ws = org_data.get(ws_field)
        if ws and isinstance(ws, str) and ws.startswith("http"):
            website = ws[:500]
            break

    for filing in filings[:MAX_FILINGS]:
        tax_year = safe_int(filing.get("tax_prd_yr"))
        if not tax_year or tax_year < 2000:
            continue

        total_assets  = safe_int(filing.get("totassetsend"))
        total_revenue = safe_int(filing.get("totrevenue"))

        # ProPublica summary doesn't have a direct grants_paid field.
        # For 990PF (private foundations, formtype=2), use totcntrbgfts
        # as a proxy for charitable distributions.
        # For 990/990EZ we leave total_giving as None —
        # it will be populated later from bulk XML when available.
        form_type   = filing.get("formtype")
        total_giving = None
        if form_type == 2:
            # 990PF filers — contributions field is closest to grants paid
            total_giving = safe_int(filing.get("totcntrbgfts"))

        object_id   = str(filing.get("object_id") or "")
        pdf_url     = str(filing.get("pdf_url") or "")

        records.append({
            "ein":                ein,
            "tax_year":           tax_year,
            "total_assets":       total_assets,
            "total_revenue":      total_revenue,
            "total_giving":       total_giving,
            "officer_names":      None,  # not in summary API
            "website":            website,
            "program_description": None,  # not in summary API
            "object_id":          object_id[:50] if object_id else None,
            "xml_index_url":      pdf_url[:1000] if pdf_url else None,
        })

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
def upsert_filings(records: list[dict]) -> int:
    if not records:
        return 0

    df = pd.DataFrame(records)
    df = df[df["ein"].notna() & df["tax_year"].notna()].copy()
    df["tax_year"] = df["tax_year"].astype(int)

    # Deduplicate — keep one row per (ein, tax_year)
    df = df.sort_values("tax_year", ascending=False).drop_duplicates(
        subset=["ein", "tax_year"], keep="first"
    )

    if df.empty:
        return 0

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE organization_filings_staging"))

    df.to_sql(
        "organization_filings_staging",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )

    with engine.begin() as conn:
        conn.execute(text("SET foreign_key_checks = 0"))
        result = conn.execute(text("""
            INSERT INTO organization_filings (
                ein, tax_year, total_assets, total_revenue, total_giving,
                officer_names, website, program_description,
                object_id, xml_index_url, created_at, updated_at
            )
            SELECT
                s.ein, s.tax_year, s.total_assets, s.total_revenue, s.total_giving,
                s.officer_names, s.website, s.program_description,
                s.object_id, s.xml_index_url, s.created_at, s.updated_at
            FROM organization_filings_staging s
            ON DUPLICATE KEY UPDATE
                total_assets        = COALESCE(s.total_assets,        organization_filings.total_assets),
                total_revenue       = COALESCE(s.total_revenue,       organization_filings.total_revenue),
                total_giving        = COALESCE(s.total_giving,        organization_filings.total_giving),
                website             = COALESCE(s.website,             organization_filings.website),
                object_id           = COALESCE(s.object_id,           organization_filings.object_id),
                xml_index_url       = COALESCE(s.xml_index_url,       organization_filings.xml_index_url),
                updated_at          = CURRENT_TIMESTAMP
        """))
        conn.execute(text("SET foreign_key_checks = 1"))
        return result.rowcount or 0


def backfill_financials():
    """Push best total_giving into organization_financials.grants_paid."""
    with engine.begin() as conn:
        conn.execute(text("SET foreign_key_checks = 0"))
        conn.execute(text("""
            UPDATE organization_financials f
            JOIN (
                SELECT ein, MAX(total_giving) AS best_giving
                FROM organization_filings
                WHERE total_giving IS NOT NULL AND total_giving > 0
                GROUP BY ein
            ) best ON best.ein = f.ein
            SET f.grants_paid  = best.best_giving,
                f.updated_at   = CURRENT_TIMESTAMP
            WHERE f.grants_paid IS NULL OR f.grants_paid = 0
        """))
        conn.execute(text("SET foreign_key_checks = 1"))

    with engine.connect() as conn:
        filled = conn.execute(
            text("SELECT COUNT(*) FROM organization_financials WHERE grants_paid > 0")
        ).scalar()
    print(f"  grants_paid filled in organization_financials: {filled:,}")


# ── Main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    print("ProPublica filings pipeline starting...")

    with engine.connect() as conn:
        master_df = pd.read_sql(text("SELECT ein FROM organizations_master"), conn)
    all_eins = master_df["ein"].tolist()

    print(f"  Master EINs        : {len(all_eins):,}")
    print(f"  Batch flush size   : {BATCH_SIZE}")
    print(f"  Max filings / org  : {MAX_FILINGS}")
    print(f"  Request delay      : {REQUEST_DELAY}s")
    print(f"  Est. time (full)   : ~{len(all_eins) * REQUEST_DELAY / 3600:.1f} hours\n")

    run_id = create_run_row()

    try:
        all_records = []
        ok_count    = 0
        not_found   = 0
        total       = len(all_eins)

        for i, ein in enumerate(all_eins, 1):
            if i % 250 == 0 or i == total:
                print(f"  [{i}/{total}]  found={ok_count}  not_found={not_found}  "
                      f"pending_records={len(all_records)}")

            resp = fetch_org(ein)
            time.sleep(REQUEST_DELAY)

            if resp is None:
                not_found += 1
                continue

            records = extract_filings(ein, resp)
            if records:
                all_records.extend(records)
                ok_count += 1
            else:
                not_found += 1

            # Flush every BATCH_SIZE records
            if len(all_records) >= BATCH_SIZE:
                flushed = upsert_filings(all_records)
                print(f"  Flushed {flushed} rows → organization_filings")
                all_records = []

        # Final flush
        if all_records:
            flushed = upsert_filings(all_records)
            print(f"  Final flush: {flushed} rows → organization_filings")

        # Backfill grants_paid
        backfill_financials()

        # Summary
        with engine.connect() as conn:
            total_filings = conn.execute(
                text("SELECT COUNT(*) FROM organization_filings")
            ).scalar()
            with_giving = conn.execute(
                text("SELECT COUNT(*) FROM organization_filings WHERE total_giving > 0")
            ).scalar()
            with_website = conn.execute(
                text("SELECT COUNT(*) FROM organization_filings WHERE website IS NOT NULL")
            ).scalar()
            with_assets = conn.execute(
                text("SELECT COUNT(*) FROM organization_filings WHERE total_assets > 0")
            ).scalar()

        mark_success(run_id, rows_read=ok_count, rows_upserted=total_filings)

        print(f"\n── Summary ──────────────────────────────────────")
        print(f"  EINs found in ProPublica    : {ok_count:,}")
        print(f"  EINs not found              : {not_found:,}")
        print(f"  Total rows in filings table : {total_filings:,}")
        print(f"  Filings with total_giving   : {with_giving:,}")
        print(f"  Filings with website        : {with_website:,}")
        print(f"  Filings with total_assets   : {with_assets:,}")
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
