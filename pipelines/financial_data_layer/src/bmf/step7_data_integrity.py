import os
import traceback
from datetime import datetime
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

PIPELINE_NAME = "data_integrity"
SOURCE_NAME   = "internal"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)


# ── Create change log table if not exists ─────────────────────────────────
def ensure_change_log():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS organization_change_log (
                log_id          BIGINT          NOT NULL AUTO_INCREMENT,
                ein             CHAR(9)         NOT NULL,
                field_changed   VARCHAR(100)    NOT NULL,
                old_value       TEXT            NULL,
                new_value       TEXT            NULL,
                change_reason   VARCHAR(255)    NULL,
                changed_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                pipeline_name   VARCHAR(100)    NULL,
                PRIMARY KEY (log_id),
                KEY idx_cl_ein   (ein),
                KEY idx_cl_field (field_changed),
                KEY idx_cl_time  (changed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
    print("  change_log table ready.")


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


# ── Integrity checks ───────────────────────────────────────────────────────
def check_invalid_eins() -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM organizations_master
            WHERE ein IS NULL
               OR CHAR_LENGTH(ein) <> 9
               OR ein NOT REGEXP '^[0-9]{9}$'
        """)).scalar()
    return result or 0


def check_duplicate_eins() -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT ein FROM organizations_master
                GROUP BY ein HAVING COUNT(*) > 1
            ) dupes
        """)).scalar()
    return result or 0


def check_missing_names() -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM organizations_master
            WHERE org_name IS NULL OR TRIM(org_name) = ''
        """)).scalar()
    return result or 0


def check_missing_ntee() -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM organizations_master
            WHERE ntee_code IS NULL OR TRIM(ntee_code) = ''
        """)).scalar()
    return result or 0


def check_revoked() -> int:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM organizations_master
            WHERE status_code IN ('20','22','23','24','28')
        """)).scalar()
    return result or 0


# ── Normalization with change logging ─────────────────────────────────────
def normalize_states() -> int:
    """Normalize state codes to uppercase and log changes."""
    with engine.connect() as conn:
        dirty = pd.read_sql(text("""
            SELECT ein, state FROM organizations_master
            WHERE state != UPPER(TRIM(state))
               OR state != TRIM(state)
        """), conn)

    if dirty.empty:
        return 0

    log_rows = []
    for _, row in dirty.iterrows():
        log_rows.append({
            "ein":           row["ein"],
            "field_changed": "state",
            "old_value":     row["state"],
            "new_value":     str(row["state"]).strip().upper(),
            "change_reason": "state normalization",
            "pipeline_name": PIPELINE_NAME,
        })

    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organizations_master
            SET state = UPPER(TRIM(state)), updated_at = CURRENT_TIMESTAMP
            WHERE state != UPPER(TRIM(state)) OR state != TRIM(state)
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))

    if log_rows:
        pd.DataFrame(log_rows).to_sql(
            "organization_change_log", engine,
            if_exists="append", index=False, method="multi", chunksize=1000
        )

    return len(log_rows)


def normalize_zips() -> int:
    """Normalize ZIP codes to 5 digits and log changes."""
    with engine.connect() as conn:
        dirty = pd.read_sql(text("""
            SELECT ein, zip FROM organizations_master
            WHERE zip IS NOT NULL AND CHAR_LENGTH(TRIM(zip)) > 5
        """), conn)

    if dirty.empty:
        return 0

    log_rows = []
    for _, row in dirty.iterrows():
        log_rows.append({
            "ein":           row["ein"],
            "field_changed": "zip",
            "old_value":     row["zip"],
            "new_value":     str(row["zip"]).strip()[:5],
            "change_reason": "zip normalization to 5 digits",
            "pipeline_name": PIPELINE_NAME,
        })

    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organizations_master
            SET zip = LEFT(TRIM(zip), 5), updated_at = CURRENT_TIMESTAMP
            WHERE zip IS NOT NULL AND CHAR_LENGTH(TRIM(zip)) > 5
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))

    if log_rows:
        pd.DataFrame(log_rows).to_sql(
            "organization_change_log", engine,
            if_exists="append", index=False, method="multi", chunksize=1000
        )

    return len(log_rows)


def normalize_websites() -> int:
    """Add http:// prefix to websites missing it and log changes."""
    with engine.connect() as conn:
        dirty = pd.read_sql(text("""
            SELECT ein, tax_year, website FROM organization_filings
            WHERE website IS NOT NULL
              AND website != ''
              AND website NOT LIKE 'http%'
        """), conn)

    if dirty.empty:
        return 0

    log_rows = []
    for _, row in dirty.iterrows():
        log_rows.append({
            "ein":           row["ein"],
            "field_changed": "website",
            "old_value":     row["website"],
            "new_value":     "http://" + str(row["website"]),
            "change_reason": "website url normalization",
            "pipeline_name": PIPELINE_NAME,
        })

    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_filings
            SET website = CONCAT('http://', website),
                updated_at = CURRENT_TIMESTAMP
            WHERE website IS NOT NULL
              AND website != ''
              AND website NOT LIKE 'http%'
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))

    if log_rows:
        pd.DataFrame(log_rows).to_sql(
            "organization_change_log", engine,
            if_exists="append", index=False, method="multi", chunksize=1000
        )

    return len(log_rows)


# ── Main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    print("Data integrity pipeline starting...")

    ensure_change_log()
    run_id = create_run_row()

    try:
        # Run integrity checks
        print("\n── Integrity Checks ──────────────────────────")
        invalid_eins   = check_invalid_eins()
        duplicate_eins = check_duplicate_eins()
        missing_names  = check_missing_names()
        missing_ntee   = check_missing_ntee()
        revoked        = check_revoked()

        print(f"  Invalid EINs    : {invalid_eins:,}")
        print(f"  Duplicate EINs  : {duplicate_eins:,}")
        print(f"  Missing names   : {missing_names:,}")
        print(f"  Missing NTEE    : {missing_ntee:,}")
        print(f"  Revoked orgs    : {revoked:,}")

        # Run normalizations with change logging
        print("\n── Normalizations ────────────────────────────")
        state_changes   = normalize_states()
        zip_changes     = normalize_zips()
        website_changes = normalize_websites()

        print(f"  State changes logged   : {state_changes:,}")
        print(f"  ZIP changes logged     : {zip_changes:,}")
        print(f"  Website changes logged : {website_changes:,}")

        total_changes = state_changes + zip_changes + website_changes

        # Change log summary
        with engine.connect() as conn:
            log_total = conn.execute(
                text("SELECT COUNT(*) FROM organization_change_log")
            ).scalar()
            log_by_field = pd.read_sql(text("""
                SELECT field_changed, COUNT(*) AS changes
                FROM organization_change_log
                GROUP BY field_changed
                ORDER BY changes DESC
            """), conn)

        mark_success(run_id, rows_read=65019, rows_upserted=total_changes)

        print(f"\n── Summary ───────────────────────────────────")
        print(f"  Total change log entries : {log_total:,}")
        print(f"  Changes by field:")
        print(log_by_field.to_string(index=False))
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
