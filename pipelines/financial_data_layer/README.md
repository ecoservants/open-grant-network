## Financial Data Layer Pipeline

Builds the financial intelligence layer on top of `organizations_master`, adding multi-year filing history, aggregated financials, federal funding flags, and computed scoring metrics.

**Depends on:** `pipelines/master_organization_universe` must be run first — `organizations_master` table must be populated.

---

## Tables This Pipeline Owns

| Table | Type | Description |
|---|---|---|
| `organization_financials` | Snapshot | Latest financial position per EIN — assets, revenue, 3yr averages, giving trend, recency score |
| `organization_filings` | Historical | One row per EIN + tax_year — multi-year filing history from ProPublica |
| `organization_audit_flags` | Snapshot | Latest FAC audit per EIN — federal funding indicators |

---

## Data Sources

| Source | What it provides |
|---|---|
| IRS SOI Extract | Total assets, revenue, contributions (2021–2023) |
| ProPublica API | Multi-year filing history, assets, revenue per EIN |
| Federal Audit Clearinghouse | Federal funding flags, single audit indicators |

---

## Assumptions

- All dollar amounts from IRS sources are whole numbers — stored as BIGINT
- `organization_financials` is a latest-snapshot table — one row per EIN representing the most recent financial position. For year-over-year history use `organization_filings`
- `organization_audit_flags` keeps the highest-expenditure FAC audit year per EIN. Full audit history is a future enhancement
- ProPublica API coverage is ~40% of master EINs — remaining orgs will be enriched via bulk 990 XML in a future pipeline

---

## How to Run

### Prerequisites
- MySQL 8.0+ with `grant_tracker` database
- `organizations_master` table populated (run Part 1 first)
- `.env` configured (see `.env.example`)
- Python venv: `source .venv/Scripts/activate`

### Step 1 — Schema
```sql
-- Run in MySQL Workbench:
sql/003_init_financial_layer.sql
```

### Step 2 — SOI Financial Data
```bash
python src/soi/step1_download_soi.py
python src/soi/step2_load_soi.py
```

### Step 3 — ProPublica Filings (~2 hours at 0.1s delay)
```bash
python src/xml990/step2_propublica_filings.py
```

### Step 4 — Financial Calculations
```sql
-- Run after Step 3 completes:
sql/005_compute_financials.sql
```

### Step 5 — FAC Federal Funding Flags
```bash
# Requires FAC_API_KEY in .env (free from https://api.data.gov/signup/)
python src/fac/step1_load_fac.py
```

### Step 6 — Validate
```sql
sql/004_fac_validation.sql
```

---

## Environment Variables

See `.env.example` for full list. Key variables:
```
SOI_TAX_YEARS=2021,2022,2023
PROPUBLICA_DELAY=0.1
PROPUBLICA_MAX_FILINGS=3
FAC_API_KEY=your_key_here # Get free key at https://api.data.gov/signup/
```
