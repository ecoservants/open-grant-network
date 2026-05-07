import json
import os
import re
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

PIPELINE_NAME = "keyword_intelligence"
SOURCE_NAME   = "internal_ntee_enrichment"

safe_pw   = quote_plus(MYSQL_PASSWORD)
MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{safe_pw}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine    = create_engine(MYSQL_URL)


# ── NTEE keyword mapping ───────────────────────────────────────────────────
# Maps NTEE major group to structured mission + funding type keywords
NTEE_KEYWORD_MAP = {
    "A": {
        "mission":       ["arts", "culture", "humanities", "museum", "performing arts", "history"],
        "funding_type":  ["arts grants", "cultural programs", "heritage preservation"],
        "exclusions":    ["religious", "political"],
    },
    "B": {
        "mission":       ["education", "schools", "university", "library", "student services", "literacy"],
        "funding_type":  ["scholarships", "education grants", "research funding", "tuition support"],
        "exclusions":    ["religious education"],
    },
    "C": {
        "mission":       ["environment", "conservation", "wildlife", "sustainability", "climate", "nature"],
        "funding_type":  ["conservation grants", "environmental programs", "green initiatives"],
        "exclusions":    ["fossil fuels", "extractive industries"],
    },
    "D": {
        "mission":       ["animals", "wildlife", "veterinary", "animal protection", "pet welfare"],
        "funding_type":  ["animal welfare grants", "wildlife conservation"],
        "exclusions":    ["animal testing"],
    },
    "E": {
        "mission":       ["health", "hospital", "clinic", "healthcare", "medical", "wellness"],
        "funding_type":  ["health grants", "medical services", "patient care", "clinical programs"],
        "exclusions":    ["political", "religious"],
    },
    "F": {
        "mission":       ["mental health", "substance abuse", "crisis intervention", "counseling", "behavioral health"],
        "funding_type":  ["mental health grants", "substance abuse programs", "crisis services"],
        "exclusions":    [],
    },
    "G": {
        "mission":       ["disease research", "patient support", "medical research", "health advocacy"],
        "funding_type":  ["disease research grants", "patient assistance", "clinical trials"],
        "exclusions":    [],
    },
    "H": {
        "mission":       ["medical research", "scientific research", "biomedical", "public health research"],
        "funding_type":  ["research grants", "scientific programs", "biomedical funding"],
        "exclusions":    [],
    },
    "I": {
        "mission":       ["crime prevention", "legal aid", "rehabilitation", "justice", "prisoner reentry"],
        "funding_type":  ["legal services", "crime prevention programs", "reentry support"],
        "exclusions":    [],
    },
    "J": {
        "mission":       ["employment", "job training", "workforce development", "labor", "vocational"],
        "funding_type":  ["workforce grants", "job training programs", "employment services"],
        "exclusions":    [],
    },
    "K": {
        "mission":       ["food", "agriculture", "nutrition", "food bank", "hunger", "farming"],
        "funding_type":  ["food assistance", "nutrition programs", "agricultural grants"],
        "exclusions":    [],
    },
    "L": {
        "mission":       ["housing", "shelter", "homeless", "affordable housing", "community development"],
        "funding_type":  ["housing grants", "shelter programs", "homeless services"],
        "exclusions":    [],
    },
    "M": {
        "mission":       ["public safety", "disaster relief", "emergency services", "fire", "rescue"],
        "funding_type":  ["emergency grants", "disaster relief", "public safety programs"],
        "exclusions":    [],
    },
    "N": {
        "mission":       ["recreation", "sports", "parks", "camps", "leisure", "athletics"],
        "funding_type":  ["recreation grants", "sports programs", "youth athletics"],
        "exclusions":    [],
    },
    "O": {
        "mission":       ["youth development", "mentoring", "scouting", "after school", "youth programs"],
        "funding_type":  ["youth grants", "mentoring programs", "after school funding"],
        "exclusions":    [],
    },
    "P": {
        "mission":       ["human services", "social services", "family services", "aging", "disability"],
        "funding_type":  ["human services grants", "social programs", "family support"],
        "exclusions":    [],
    },
    "Q": {
        "mission":       ["international", "global development", "relief", "humanitarian", "peace"],
        "funding_type":  ["international grants", "global programs", "humanitarian aid"],
        "exclusions":    [],
    },
    "R": {
        "mission":       ["civil rights", "advocacy", "social justice", "equity", "voting rights"],
        "funding_type":  ["advocacy grants", "civil rights programs", "social justice funding"],
        "exclusions":    ["partisan political"],
    },
    "S": {
        "mission":       ["community development", "neighborhood", "economic development", "civic"],
        "funding_type":  ["community grants", "neighborhood programs", "economic development"],
        "exclusions":    [],
    },
    "T": {
        "mission":       ["philanthropy", "grantmaking", "foundation", "fundraising", "charity"],
        "funding_type":  ["general grants", "capacity building", "nonprofit support"],
        "exclusions":    [],
    },
    "U": {
        "mission":       ["science", "technology", "research", "innovation", "STEM"],
        "funding_type":  ["science grants", "technology programs", "STEM funding"],
        "exclusions":    [],
    },
    "V": {
        "mission":       ["social science", "policy research", "think tank", "public policy"],
        "funding_type":  ["research grants", "policy programs"],
        "exclusions":    [],
    },
    "W": {
        "mission":       ["public affairs", "government", "civic", "public policy", "democracy"],
        "funding_type":  ["civic grants", "public affairs programs"],
        "exclusions":    ["partisan political"],
    },
    "X": {
        "mission":       ["religion", "faith", "spiritual", "church", "interfaith"],
        "funding_type":  ["religious programs", "faith-based grants"],
        "exclusions":    [],
    },
    "Y": {
        "mission":       ["mutual benefit", "credit union", "insurance", "pension", "membership"],
        "funding_type":  ["member benefits", "cooperative programs"],
        "exclusions":    [],
    },
    "Z": {
        "mission":       ["unclassified"],
        "funding_type":  [],
        "exclusions":    [],
    },
}

# Geographic keyword patterns
GEO_PATTERNS = [
    r"\b(washington|oregon|idaho|pacific northwest|northwest)\b",
    r"\b(seattle|portland|boise|spokane|tacoma|eugene)\b",
    r"\b(statewide|regional|local|national|international|global)\b",
    r"\b(rural|urban|suburban|metropolitan)\b",
]


def extract_geo_keywords(text: str) -> list[str]:
    """Extract geographic focus keywords from program description."""
    if not text:
        return []
    text_lower = text.lower()
    found = set()
    for pattern in GEO_PATTERNS:
        matches = re.findall(pattern, text_lower)
        found.update(matches)
    return sorted(found)


def extract_program_keywords(text: str) -> list[str]:
    """Extract meaningful program area keywords from description text."""
    if not text:
        return []

    # Remove common stop words and short tokens
    stop_words = {
        "the", "and", "or", "in", "of", "to", "a", "an", "for", "with",
        "that", "this", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "our", "its", "by", "at",
        "from", "on", "as", "we", "us", "their", "they", "it", "not", "but",
        "all", "any", "both", "each", "few", "more", "most", "other", "some",
        "such", "than", "too", "very", "just", "through", "provide", "support",
        "program", "programs", "services", "service", "organization", "community"
    }

    words = re.findall(r"\b[a-z]{4,}\b", text.lower())
    keywords = [w for w in words if w not in stop_words]

    # Count frequency and return top keywords
    from collections import Counter
    counts = Counter(keywords)
    return [word for word, _ in counts.most_common(10)]


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


# ── Main pipeline ──────────────────────────────────────────────────────────
def run_pipeline():
    print("Keyword intelligence pipeline starting...")

    run_id = create_run_row()

    try:
        # Load master orgs with NTEE codes
        with engine.connect() as conn:
            orgs = pd.read_sql(text("""
                SELECT
                    m.ein,
                    m.ntee_code,
                    m.state,
                    m.city,
                    f.program_description
                FROM organizations_master m
                LEFT JOIN organization_filings f ON f.ein = m.ein
                WHERE m.ntee_code IS NOT NULL AND m.ntee_code != ''
                GROUP BY m.ein, m.ntee_code, m.state, m.city, f.program_description
            """), conn)

        print(f"  Orgs with NTEE codes : {len(orgs):,}")

        records = []
        for _, row in orgs.iterrows():
            ein      = row["ein"]
            ntee     = str(row["ntee_code"] or "").strip().upper()
            desc     = str(row["program_description"] or "")
            state    = str(row["state"] or "")
            city     = str(row["city"] or "")

            # Get major group (first letter of NTEE code)
            major_group = ntee[0] if ntee else "Z"
            ntee_data   = NTEE_KEYWORD_MAP.get(major_group, NTEE_KEYWORD_MAP["Z"])

            # Build keyword sets
            mission_kw   = ntee_data["mission"]
            funding_kw   = ntee_data["funding_type"]
            exclusion_kw = ntee_data["exclusions"]

            # Program area keywords from description
            program_kw = extract_program_keywords(desc)

            # Geographic focus
            geo_kw = extract_geo_keywords(desc)
            if state:
                geo_kw.append(state.lower())
            if city:
                geo_kw.append(city.lower())
            geo_kw = sorted(set(geo_kw))

            # Get NTEE label
            with engine.connect() as conn:
                ntee_row = conn.execute(text("""
                    SELECT label FROM ntee_major_groups WHERE major_group = :mg
                """), {"mg": major_group}).fetchone()
            ntee_label = ntee_row[0] if ntee_row else "Unknown"

            records.append({
                "ein":                  ein,
                "mission_keywords":     json.dumps(mission_kw),
                "program_area_keywords": json.dumps(program_kw),
                "geographic_focus":     json.dumps(geo_kw),
                "funding_type_keywords": json.dumps(funding_kw),
                "exclusion_keywords":   json.dumps(exclusion_kw),
                "ntee_major_group":     major_group,
                "ntee_major_label":     ntee_label,
                "ntee_full_label":      f"{major_group} - {ntee_label}",
                "program_description_raw": desc[:5000] if desc else None,
                "description_source":   "propublica" if desc else "ntee_only",
            })

        print(f"  Records to enrich    : {len(records):,}")

        # Upsert into organization_enrichment
        if records:
            df = pd.DataFrame(records)

            with engine.begin() as conn:
                conn.execute(text("SET foreign_key_checks = 0"))

            # Load in chunks
            chunk_size = 1000
            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i:i+chunk_size]
                chunk.to_sql(
                    "organization_enrichment",
                    engine,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=500,
                )
                print(f"  Loaded chunk {i//chunk_size + 1}: {len(chunk)} rows")

            with engine.begin() as conn:
                conn.execute(text("SET foreign_key_checks = 1"))

        mark_success(run_id, rows_read=len(orgs), rows_upserted=len(records))

        # Summary
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM organization_enrichment")
            ).scalar()
            by_group = pd.read_sql(text("""
                SELECT ntee_major_label, COUNT(*) AS orgs
                FROM organization_enrichment
                GROUP BY ntee_major_label
                ORDER BY orgs DESC
                LIMIT 10
            """), conn)

        print(f"\n── Summary ──────────────────────────────────────")
        print(f"  Total enriched orgs  : {total:,}")
        print(f"\n  Top 10 by NTEE group:")
        print(by_group.to_string(index=False))
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
