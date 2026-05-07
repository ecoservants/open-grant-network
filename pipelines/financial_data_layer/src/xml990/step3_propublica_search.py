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
PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"
REQUEST_DELAY   = float(os.getenv("PROPUBLICA_DELAY", "0.5"))
SEARCH_TERMS    = [
    t.strip() for t in
    os.getenv(
        "PROPUBLICA_SEARCH_TERMS",
        "foundation,charitable trust,community foundation,family foundation"
    ).split(",")
    if t.strip()
]
SEARCH_STATES   = set(
    s.strip().upper() for s in
    os.getenv("PROPUBLICA_SEARCH_STATES", "WA,OR,ID").split(",")
    if s.strip()
)

PIPELINE_NAME = "propublica_search_enrichment"
SOURCE_NAME   = "propublica_search_api"

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


def clean_website(url) -> str | None:
    if not url:
        return None
    url = str(url).strip()
    if url.startswith("http"):
        return url[:500]
    return None


def safe_int(val) -> int | None:
    try:
        v = int(float(val))
        return v if v > 0 else None
    except Exception:
        return None


# ── ProPublica search API ──────────────────────────────────────────────────
def search_propublica(term: str, page: int = 0) -> dict | None:
    """
    Search ProPublica nonprofit API.
    Note: state filter causes 500 errors — we filter by state after fetching.
    """
    url = (
        f"{PROPUBLICA_BASE}/search.json"
        f"?q={requests.utils.quote(term)}"
        f"&page={page}"
    )
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            print(f"    Rate limited — waiting 10s...")
            time.sleep(10)
            return search_propublica(term, page)
        print(f"    HTTP {r.status_code} for term='{term}' page={page}")
    except Exception as e:
        print(f"    Search error: {e}")
    return None


def fetch_all_search_results(term: str) -> list[dict]:
    """
    Paginate through all search results for a term.
    Filters to SEARCH_STATES after fetching since state param causes API errors.
    """
    all_orgs = []
    page     = 0

    while True:
        resp = search_propublica(term, page)
        time.sleep(REQUEST_DELAY)

        if not resp:
            break

        orgs = resp.get("organizations", [])
        if not orgs:
            break

        # Filter to our target states
        filtered = [
            o for o in orgs
            if str(o.get("state", "")).upper() in SEARCH_STATES
        ]
        all_orgs.extend(filtered)

        print(f"    Page {page}: {len(orgs)} results, {len(filtered)} in target states")

        # ProPublica returns 25 per page — if less we're done
        if len(orgs) < 25:
            break

        page += 1

        # Safety limit
        if page >= 40:
            print(f"    Hit page limit (40) for term='{term}'")
            break

    return all_orgs


# ── Extract enrichment data ────────────────────────────────────────────────
def extract_enrichment(org: dict) -> dict | None:
    ein = normalize_ein(org.get("ein"))
    if not ein:
        return None

    return {
        "ein":           ein,
        "website":       clean_website(org.get("website")),
        "ntee_code":     org.get("ntee_code") or org.get("raw_ntee_code"),
        "total_revenue": safe_int(org.get("income_amount") or org.get("revenue_amount")),
        "total_assets":  safe_int(org.get("asset_amount")),
        "org_name":      str(org.get("name") or "").strip().upper() or None,
        "city":          org.get("city"),
        "state":         org.get("state"),
    }


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


# ── Apply enrichment ───────────────────────────────────────────────────────
def apply_enrichment(records: list[dict]) -> int:
    if not records:
        return 0

    updated = 0
    with engine.begin() as conn:
        conn.execute(text("SET foreign_key_checks = 0"))
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))

        for rec in records:
            ein = rec["ein"]

            # Fill website in organization_filings where missing
            if rec.get("website"):
                conn.execute(text("""
                    UPDATE organization_filings
                    SET website = :ws, updated_at = CURRENT_TIMESTAMP
                    WHERE ein = :ein AND (website IS NULL OR website = '')
                """), {"ws": rec["website"], "ein": ein})

            # Fill NTEE code in organizations_master where missing
            if rec.get("ntee_code"):
                conn.execute(text("""
                    UPDATE organizations_master
                    SET ntee_code = :ntee, updated_at = CURRENT_TIMESTAMP
                    WHERE ein = :ein AND (ntee_code IS NULL OR ntee_code = '')
                """), {"ntee": rec["ntee_code"], "ein": ein})

            # Fill missing financials in organization_financials
            if rec.get("total_assets") or rec.get("total_revenue"):
                conn.execute(text("""
                    UPDATE organization_financials
                    SET
                        total_assets  = COALESCE(total_assets,  :ta),
                        total_revenue = COALESCE(total_revenue, :tr),
                        updated_at    = CURRENT_TIMESTAMP
                    WHERE ein = :ein
                """), {
                    "ta":  rec.get("total_assets"),
                    "tr":  rec.get("total_revenue"),
                    "ein": ein,
                })

            updated += 1

        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
        conn.execute(text("SET foreign_key_checks = 1"))

    return updated


# ── Main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    print("ProPublica search enrichment pipeline starting...")
    print(f"  Search terms : {SEARCH_TERMS}")
    print(f"  Target states: {SEARCH_STATES}")

    # Load master EINs
    with engine.connect() as conn:
        master_df = pd.read_sql(text("SELECT ein FROM organizations_master"), conn)
    master_eins = set(master_df["ein"].tolist())
    print(f"  Master EINs  : {len(master_eins):,}")

    run_id = create_run_row()

    try:
        all_records    = []
        seen_eins      = set()
        total_searched = 0

        for term in SEARCH_TERMS:
            print(f"\n  Searching: '{term}'...")
            orgs = fetch_all_search_results(term)
            total_searched += len(orgs)
            print(f"  '{term}' → {len(orgs)} orgs in target states")

            for org in orgs:
                rec = extract_enrichment(org)
                if not rec:
                    continue
                ein = rec["ein"]

                # Only enrich orgs in our master table
                if ein not in master_eins:
                    continue

                # Deduplicate across search terms
                if ein in seen_eins:
                    continue
                seen_eins.add(ein)
                all_records.append(rec)

        print(f"\n  Total state-filtered results : {total_searched:,}")
        print(f"  Matched to master EINs       : {len(all_records):,}")

        # Apply enrichment
        updated = apply_enrichment(all_records)
        print(f"  Records enriched             : {updated:,}")

        mark_success(run_id, rows_read=total_searched, rows_upserted=updated)

        # Summary
        with engine.connect() as conn:
            with_website = conn.execute(
                text("SELECT COUNT(*) FROM organization_filings WHERE website IS NOT NULL")
            ).scalar()
            with_ntee = conn.execute(
                text("""
                    SELECT COUNT(*) FROM organizations_master
                    WHERE ntee_code IS NOT NULL AND ntee_code != ''
                """)
            ).scalar()

        print(f"\n── Summary ──────────────────────────────────────")
        print(f"  Filings with website now  : {with_website:,}")
        print(f"  Orgs with NTEE code       : {with_ntee:,}")
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
