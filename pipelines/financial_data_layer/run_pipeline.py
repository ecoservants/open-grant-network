"""
Grant Tracker — Master Pipeline Orchestrator
Part 9: Automation Schedule

Run modes:
  monthly     — BMF update + SOI update + ProPublica enrichment
  quarterly   — monthly + recompute scores + requalify
  annual      — quarterly + archive + recalculate 3yr averages
  full        — run everything from scratch
  scores_only — recompute scores only (lightweight)

Usage:
  python src/run_pipeline.py --mode monthly
  python src/run_pipeline.py --mode quarterly
  python src/run_pipeline.py --mode full
  python src/run_pipeline.py --mode scores_only
"""

import argparse
import os
import subprocess
import sys
import traceback
from datetime import datetime
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ── DB config ──────────────────────────────────────────────────────────────
MYSQL_HOST     = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT     = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB       = os.getenv("MYSQL_DB", "grant_tracker")
MYSQL_USER     = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)

PYTHON = sys.executable


# ── Pipeline step definitions ──────────────────────────────────────────────
STEPS = {
    # Part 1 — Master Organization Universe
    "bmf_discover":     "src/bmf/step3_discover_bmf_links.py",
    "bmf_download":     "src/bmf/step4_download_bmf_csvs.py",
    "bmf_load":         "src/bmf/step6_parse_load_with_runlog.py",

    # Part 2 — Financial Data Layer
    "soi_download":     "src/soi/step1_download_soi.py",
    "soi_load":         "src/soi/step2_load_soi.py",
    "xml990_index":     "src/xml990/step1_download_990_index.py",
    "propublica_enrich":"src/xml990/step2_propublica_filings.py",
    "propublica_search":"src/xml990/step3_propublica_search.py",

    # Part 3 — FAC
    "fac_load":         "src/fac/step1_load_fac.py",

    # Part 5 — Data Integrity
    "integrity":        "src/bmf/step7_data_integrity.py",

    # Part 7 — Keyword Intelligence
    "keywords":         "src/bmf/step8_keyword_intelligence.py",

    # Part 8 — Scoring
    "scores":           "src/bmf/step9_compute_scores.py",
}

# Schedule definitions
SCHEDULES = {
    "monthly": [
        "bmf_discover",
        "bmf_download",
        "bmf_load",
        "soi_download",
        "soi_load",
        "propublica_enrich",
        "propublica_search",
        "fac_load",
        "integrity",
    ],
    "quarterly": [
        "bmf_discover",
        "bmf_download",
        "bmf_load",
        "soi_download",
        "soi_load",
        "propublica_enrich",
        "propublica_search",
        "fac_load",
        "integrity",
        "keywords",
        "scores",
    ],
    "annual": [
        "bmf_discover",
        "bmf_download",
        "bmf_load",
        "soi_download",
        "soi_load",
        "xml990_index",
        "propublica_enrich",
        "propublica_search",
        "fac_load",
        "integrity",
        "keywords",
        "scores",
    ],
    "full": [
        "bmf_discover",
        "bmf_download",
        "bmf_load",
        "soi_download",
        "soi_load",
        "xml990_index",
        "propublica_enrich",
        "propublica_search",
        "fac_load",
        "integrity",
        "keywords",
        "scores",
    ],
    "scores_only": [
        "scores",
    ],
}


# ── Run a single step ──────────────────────────────────────────────────────
def run_step(step_name: str, script_path: str, stop_on_error: bool = True) -> bool:
    print(f"\n{'─'*60}")
    print(f"  STEP: {step_name}")
    print(f"  Script: {script_path}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*60}")

    if not os.path.exists(script_path):
        print(f"  WARNING: Script not found — {script_path}")
        return False

    result = subprocess.run(
        [PYTHON, script_path],
        capture_output=False,
    )

    if result.returncode != 0:
        print(f"\n  FAILED: {step_name} (exit code {result.returncode})")
        if stop_on_error:
            raise RuntimeError(f"Step failed: {step_name}")
        return False

    print(f"\n  DONE: {step_name}")
    return True


# ── Log orchestrator run ───────────────────────────────────────────────────
def log_orchestrator_run(mode: str, status: str, steps_run: list, error: str = None):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO pipeline_runs
                    (pipeline_name, source_name, status, error_message)
                VALUES (:p, :s, :st, :e)
            """), {
                "p":  f"orchestrator_{mode}",
                "s":  "orchestrator",
                "st": status,
                "e":  error[:65000] if error else None,
            })
    except Exception as e:
        print(f"  Warning: Could not log orchestrator run: {e}")


# ── Print final database summary ───────────────────────────────────────────
def print_db_summary():
    print(f"\n{'═'*60}")
    print("  DATABASE SUMMARY")
    print(f"{'═'*60}")

    queries = {
        "organizations_master":     "SELECT COUNT(*) FROM organizations_master",
        "organization_financials":  "SELECT COUNT(*) FROM organization_financials",
        "organization_filings":     "SELECT COUNT(*) FROM organization_filings",
        "organization_enrichment":  "SELECT COUNT(*) FROM organization_enrichment",
        "organization_scoring":     "SELECT COUNT(*) FROM organization_scoring",
        "organization_audit_flags": "SELECT COUNT(*) FROM organization_audit_flags",
        "organization_change_log":  "SELECT COUNT(*) FROM organization_change_log",
    }

    with engine.connect() as conn:
        for table, query in queries.items():
            try:
                count = conn.execute(text(query)).scalar()
                print(f"  {table:<35} : {count:>10,}")
            except Exception:
                print(f"  {table:<35} : {'N/A':>10}")

        # Score tier breakdown
        try:
            tiers = conn.execute(text("""
                SELECT score_tier, COUNT(*) as cnt
                FROM organization_scoring
                WHERE score_tier IS NOT NULL
                GROUP BY score_tier
                ORDER BY score_tier
            """)).fetchall()
            if tiers:
                print(f"\n  Score tiers:")
                for tier, cnt in tiers:
                    print(f"    Tier {tier}: {cnt:,} orgs")
        except Exception:
            pass

        # Pipeline runs
        try:
            runs = conn.execute(text("""
                SELECT pipeline_name, status, finished_at
                FROM pipeline_runs
                ORDER BY run_id DESC
                LIMIT 5
            """)).fetchall()
            if runs:
                print(f"\n  Last 5 pipeline runs:")
                for name, status, finished in runs:
                    print(f"    {name:<40} {status:<10} {str(finished)[:19]}")
        except Exception:
            pass

    print(f"{'═'*60}\n")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Grant Tracker Pipeline Orchestrator"
    )
    parser.add_argument(
        "--mode",
        choices=["monthly", "quarterly", "annual", "full", "scores_only"],
        default="monthly",
        help="Pipeline run mode (default: monthly)",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        default=True,
        help="Stop pipeline on first error (default: True)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Continue pipeline even if a step fails",
    )

    args = parser.parse_args()
    mode          = args.mode
    stop_on_error = not args.continue_on_error

    steps_to_run = SCHEDULES.get(mode, [])

    print(f"\n{'═'*60}")
    print(f"  GRANT TRACKER PIPELINE ORCHESTRATOR")
    print(f"  Mode     : {mode.upper()}")
    print(f"  Steps    : {len(steps_to_run)}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Stop on error: {stop_on_error}")
    print(f"{'═'*60}")

    steps_completed = []
    steps_failed    = []

    try:
        for step_name in steps_to_run:
            script_path = STEPS.get(step_name)
            if not script_path:
                print(f"  WARNING: Unknown step '{step_name}' — skipping")
                continue

            success = run_step(step_name, script_path, stop_on_error)
            if success:
                steps_completed.append(step_name)
            else:
                steps_failed.append(step_name)

        log_orchestrator_run(mode, "SUCCESS", steps_completed)

    except Exception:
        err = traceback.format_exc()
        log_orchestrator_run(mode, "FAILED", steps_completed, err)
        print(f"\n  ORCHESTRATOR FAILED")
        print(err)
        sys.exit(1)

    finally:
        print(f"\n{'═'*60}")
        print(f"  ORCHESTRATOR COMPLETE")
        print(f"  Mode      : {mode.upper()}")
        print(f"  Completed : {len(steps_completed)} steps")
        print(f"  Failed    : {len(steps_failed)} steps")
        print(f"  Finished  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'═'*60}")

        print_db_summary()


if __name__ == "__main__":
    main()
