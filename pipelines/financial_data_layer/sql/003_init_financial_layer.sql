/* Part 2: Financial Data Layer
   Tables: organization_financials, organization_filings, organization_audit_flags
   All linked to organizations_master via EIN primary key
*/

/* ─────────────────────────────────────────────
   TABLE: organization_financials
   One row per EIN — aggregated/computed financials
   Populated from SOI extract + computed from filings
   ───────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS organization_financials (
  ein                     CHAR(9)         NOT NULL,

  /* Raw SOI fields */
  total_assets            BIGINT          NULL,
  total_revenue           BIGINT          NULL,
  total_contributions     BIGINT          NULL,
  grants_paid             BIGINT          NULL,
  tax_year                SMALLINT        NULL,

  /* Computed fields (populated after filings are loaded) */
  avg_giving_3yr          BIGINT          NULL,
  avg_assets_3yr          BIGINT          NULL,
  giving_trend            ENUM('increasing','decreasing','stable','insufficient_data') NULL,
  median_grant_proxy      BIGINT          NULL,
  filing_recency_score    TINYINT UNSIGNED NULL,   /* 0–10 */

  source_file             VARCHAR(255)    NULL,
  source_posting_date     DATE            NULL,
  computed_at             TIMESTAMP       NULL,
  created_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (ein),
  CONSTRAINT fk_fin_ein FOREIGN KEY (ein) REFERENCES organizations_master (ein)
    ON UPDATE CASCADE ON DELETE CASCADE,

  KEY idx_fin_tax_year    (tax_year),
  KEY idx_fin_grants_paid (grants_paid),
  KEY idx_fin_assets      (total_assets),
  KEY idx_fin_trend       (giving_trend)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


/* ─────────────────────────────────────────────
   TABLE: organization_filings
   Many rows per EIN — one per tax year from 990 XML
   Composite PK: (ein, tax_year)
   ───────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS organization_filings (
  ein                     CHAR(9)         NOT NULL,
  tax_year                SMALLINT        NOT NULL,

  total_assets            BIGINT          NULL,
  total_revenue           BIGINT          NULL,
  total_giving            BIGINT          NULL,

  officer_names           TEXT            NULL,   /* JSON array stored as text */
  website                 VARCHAR(500)    NULL,
  program_description     TEXT            NULL,

  xml_index_url           VARCHAR(1000)   NULL,
  object_id               VARCHAR(50)     NULL,   /* IRS 990 object ID for tracing */

  created_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (ein, tax_year),
  CONSTRAINT fk_fil_ein FOREIGN KEY (ein) REFERENCES organizations_master (ein)
    ON UPDATE CASCADE ON DELETE CASCADE,

  KEY idx_fil_tax_year    (tax_year),
  KEY idx_fil_giving      (total_giving),
  KEY idx_fil_assets      (total_assets)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


/* ─────────────────────────────────────────────
   TABLE: organization_audit_flags
   One row per EIN — FAC federal funding indicators
   Populated from Federal Audit Clearinghouse data
   ───────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS organization_audit_flags (
  ein                         CHAR(9)         NOT NULL,

  receives_federal_funding     TINYINT(1)      NOT NULL DEFAULT 0,
  single_audit_required        TINYINT(1)      NOT NULL DEFAULT 0,
  federal_expenditure_amount   BIGINT          NULL,
  audit_year                   SMALLINT        NULL,

  source_file                  VARCHAR(255)    NULL,
  created_at                   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (ein),
  CONSTRAINT fk_aud_ein FOREIGN KEY (ein) REFERENCES organizations_master (ein)
    ON UPDATE CASCADE ON DELETE CASCADE,

  KEY idx_aud_federal    (receives_federal_funding),
  KEY idx_aud_audit_year (audit_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


/* ─────────────────────────────────────────────
   STAGING TABLE: organization_financials_staging
   Mirror of organization_financials for safe upserts
   ───────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS organization_financials_staging
  LIKE organization_financials;

/* Drop the FK on staging — staging rows may not yet exist in master */
ALTER TABLE organization_financials_staging
  DROP FOREIGN KEY IF EXISTS fk_fin_ein;


/* ─────────────────────────────────────────────
   STAGING TABLE: organization_filings_staging
   Mirror of organization_filings for safe upserts
   ───────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS organization_filings_staging
  LIKE organization_filings;

ALTER TABLE organization_filings_staging
  DROP FOREIGN KEY IF EXISTS fk_fil_ein;
