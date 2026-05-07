import os
import traceback
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

PIPELINE_NAME = "scoring_system"
SOURCE_NAME   = "internal_scoring"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)


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


# ── Scoring functions ──────────────────────────────────────────────────────
def initialize_scoring_rows():
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT IGNORE INTO organization_scoring (ein)
            SELECT ein FROM organization_financials
        """))
    print("  Scoring rows initialized.")


def compute_asset_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            JOIN organization_financials f ON f.ein = s.ein
            SET s.score_assets = CASE
                WHEN f.total_assets >= 100000000 THEN 25
                WHEN f.total_assets >= 50000000  THEN 22
                WHEN f.total_assets >= 10000000  THEN 18
                WHEN f.total_assets >= 5000000   THEN 14
                WHEN f.total_assets >= 1000000   THEN 10
                WHEN f.total_assets >= 500000    THEN 6
                WHEN f.total_assets >= 100000    THEN 3
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Asset scores computed.")


def compute_giving_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            JOIN organization_financials f ON f.ein = s.ein
            SET s.score_giving = CASE
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 10000000 THEN 25
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 5000000  THEN 22
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 1000000  THEN 18
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 500000   THEN 14
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 100000   THEN 10
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 50000    THEN 6
                WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 10000    THEN 3
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Giving scores computed.")


def compute_trend_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            JOIN organization_financials f ON f.ein = s.ein
            SET s.score_trend = CASE
                WHEN f.giving_trend = 'increasing'        THEN 10
                WHEN f.giving_trend = 'stable'            THEN 6
                WHEN f.giving_trend = 'decreasing'        THEN 2
                WHEN f.giving_trend = 'insufficient_data' THEN 3
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Trend scores computed.")


def compute_recency_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            JOIN organization_financials f ON f.ein = s.ein
            SET s.score_recency = LEAST(f.filing_recency_score, 10)
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Recency scores computed.")


def compute_website_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            SET s.score_website = CASE
                WHEN EXISTS (
                    SELECT 1 FROM organization_filings f
                    WHERE f.ein = s.ein
                    AND f.website IS NOT NULL AND f.website != ''
                ) THEN 5
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Website scores computed.")


def compute_federal_penalty():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            SET s.score_federal_penalty = CASE
                WHEN EXISTS (
                    SELECT 1 FROM organization_audit_flags a
                    WHERE a.ein = s.ein
                    AND a.receives_federal_funding = 1
                    AND a.federal_expenditure_amount >= 10000000
                ) THEN 15
                WHEN EXISTS (
                    SELECT 1 FROM organization_audit_flags a
                    WHERE a.ein = s.ein
                    AND a.receives_federal_funding = 1
                ) THEN 8
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Federal penalty scores computed.")


def compute_grant_activity_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            SET s.score_grant_activity = CASE
                WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) >= 3 THEN 10
                WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) = 2  THEN 6
                WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) = 1  THEN 3
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Grant activity scores computed.")


def compute_qualification_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            JOIN organization_financials f ON f.ein = s.ein
            SET s.score_qualification = CASE
                WHEN f.qualification_status = 'priority'  THEN 15
                WHEN f.qualification_status = 'qualified' THEN 10
                WHEN f.qualification_status = 'raw'       THEN 3
                ELSE 0
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Qualification scores computed.")


def compute_composite_scores():
    with engine.begin() as conn:
        conn.execute(text("SET SQL_SAFE_UPDATES = 0"))
        conn.execute(text("""
            UPDATE organization_scoring s
            SET s.composite_score = GREATEST(0,
                COALESCE(s.score_assets, 0)
                + COALESCE(s.score_giving, 0)
                + COALESCE(s.score_trend, 0)
                + COALESCE(s.score_recency, 0)
                + COALESCE(s.score_website, 0)
                - COALESCE(s.score_federal_penalty, 0)
                + COALESCE(s.score_grant_activity, 0)
                + COALESCE(s.score_qualification, 0)
            ),
            s.computed_at = CURRENT_TIMESTAMP
        """))
        # Assign tiers
        conn.execute(text("""
            UPDATE organization_scoring s
            SET s.score_tier = CASE
                WHEN s.composite_score >= 70 THEN 'A'
                WHEN s.composite_score >= 50 THEN 'B'
                WHEN s.composite_score >= 30 THEN 'C'
                ELSE 'D'
            END
        """))
        conn.execute(text("SET SQL_SAFE_UPDATES = 1"))
    print("  Composite scores and tiers computed.")


def print_summary():
    with engine.connect() as conn:
        tier_summary = pd.read_sql(text("""
            SELECT
                score_tier,
                COUNT(*)             AS org_count,
                MIN(composite_score) AS min_score,
                MAX(composite_score) AS max_score,
                AVG(composite_score) AS avg_score
            FROM organization_scoring
            GROUP BY score_tier
            ORDER BY score_tier
        """), conn)

        top_orgs = pd.read_sql(text("""
            SELECT
                s.ein,
                m.org_name,
                m.state,
                f.qualification_status,
                s.composite_score,
                s.score_tier
            FROM organization_scoring s
            JOIN organizations_master m ON m.ein = s.ein
            JOIN organization_financials f ON f.ein = s.ein
            ORDER BY s.composite_score DESC
            LIMIT 10
        """), conn)

        total = conn.execute(
            text("SELECT COUNT(*) FROM organization_scoring")
        ).scalar()

    print(f"\n── Score Tier Summary ───────────────────────────")
    print(tier_summary.to_string(index=False))
    print(f"\n── Top 10 Grantmakers ───────────────────────────")
    print(top_orgs.to_string(index=False))
    print(f"\n  Total scored orgs : {total:,}")

    return total


# ── Main ───────────────────────────────────────────────────────────────────
def run_pipeline():
    print("Scoring system pipeline starting...")
    run_id = create_run_row()

    try:
        print("\n── Computing component scores ────────────────")
        initialize_scoring_rows()
        compute_asset_scores()
        compute_giving_scores()
        compute_trend_scores()
        compute_recency_scores()
        compute_website_scores()
        compute_federal_penalty()
        compute_grant_activity_scores()
        compute_qualification_scores()
        compute_composite_scores()

        total = print_summary()

        mark_success(run_id, rows_read=total, rows_upserted=total)
        print(f"\n  RUN_ID {run_id} → SUCCESS")
        print("Done.")

    except Exception:
        err = traceback.format_exc()
        mark_failed(run_id, err)
        print(f"  RUN_ID {run_id} → FAILED")
        print(err)
        raise


if __name__ == "__main__":
    run_pipeline()
