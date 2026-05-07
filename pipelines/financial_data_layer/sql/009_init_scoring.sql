/* Part 8: Scoring System
   Creates organization_scoring table and computes composite
   grantmaker scores for proposal targeting and prioritization.

   Score components:
   - Asset size weight        (0-25 points)
   - Annual giving weight     (0-25 points)
   - Growth trend bonus       (0-10 points)
   - Filing recency bonus     (0-10 points)
   - Website presence bonus   (0-5 points)
   - Federal dependency penalty (0 to -15 points)
   - Grant activity history   (0-10 points)
   - Qualification status     (0-15 points)

   Max possible score: 100 points
*/

USE grant_tracker;

-- ─────────────────────────────────────────────────────────────────────────
-- TABLE: organization_scoring
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organization_scoring (
    ein                         CHAR(9)         NOT NULL,

    -- Component scores
    score_assets                TINYINT UNSIGNED NULL,  -- 0-25
    score_giving                TINYINT UNSIGNED NULL,  -- 0-25
    score_trend                 TINYINT UNSIGNED NULL,  -- 0-10
    score_recency               TINYINT UNSIGNED NULL,  -- 0-10
    score_website               TINYINT UNSIGNED NULL,  -- 0-5
    score_federal_penalty       TINYINT UNSIGNED NULL,  -- 0-15 (subtracted)
    score_grant_activity        TINYINT UNSIGNED NULL,  -- 0-10
    score_qualification         TINYINT UNSIGNED NULL,  -- 0-15

    -- Final composite score
    composite_score             SMALLINT UNSIGNED NULL, -- 0-100
    score_tier                  ENUM('A','B','C','D') NULL, -- A=top, D=bottom
    score_rank                  INT UNSIGNED    NULL,   -- rank within universe

    computed_at                 TIMESTAMP       NULL,
    created_at                  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (ein),
    CONSTRAINT fk_scr_ein FOREIGN KEY (ein) REFERENCES organizations_master (ein)
        ON UPDATE CASCADE ON DELETE CASCADE,

    KEY idx_scr_composite   (composite_score),
    KEY idx_scr_tier        (score_tier),
    KEY idx_scr_rank        (score_rank)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'organization_scoring table ready' AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 1: Initialize scoring rows for all orgs in financials
-- ─────────────────────────────────────────────────────────────────────────
INSERT IGNORE INTO organization_scoring (ein)
SELECT ein FROM organization_financials;

SELECT CONCAT('Scoring rows initialized: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 2: Score — Asset size (0-25 points)
-- ─────────────────────────────────────────────────────────────────────────
SET SQL_SAFE_UPDATES = 0;

UPDATE organization_scoring s
JOIN organization_financials f ON f.ein = s.ein
SET s.score_assets = CASE
    WHEN f.total_assets >= 100000000  THEN 25   -- $100M+
    WHEN f.total_assets >= 50000000   THEN 22   -- $50M+
    WHEN f.total_assets >= 10000000   THEN 18   -- $10M+
    WHEN f.total_assets >= 5000000    THEN 14   -- $5M+
    WHEN f.total_assets >= 1000000    THEN 10   -- $1M+
    WHEN f.total_assets >= 500000     THEN 6    -- $500K+
    WHEN f.total_assets >= 100000     THEN 3    -- $100K+
    ELSE 0
END;

SELECT CONCAT('Asset scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 3: Score — Annual giving (0-25 points)
-- Uses grants_paid if available, else avg_giving_3yr
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
JOIN organization_financials f ON f.ein = s.ein
SET s.score_giving = CASE
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 10000000  THEN 25  -- $10M+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 5000000   THEN 22  -- $5M+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 1000000   THEN 18  -- $1M+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 500000    THEN 14  -- $500K+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 100000    THEN 10  -- $100K+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 50000     THEN 6   -- $50K+
    WHEN COALESCE(f.grants_paid, f.avg_giving_3yr, 0) >= 10000     THEN 3   -- $10K+
    ELSE 0
END;

SELECT CONCAT('Giving scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 4: Score — Growth trend bonus (0-10 points)
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
JOIN organization_financials f ON f.ein = s.ein
SET s.score_trend = CASE
    WHEN f.giving_trend = 'increasing'        THEN 10
    WHEN f.giving_trend = 'stable'            THEN 6
    WHEN f.giving_trend = 'decreasing'        THEN 2
    WHEN f.giving_trend = 'insufficient_data' THEN 3
    ELSE 0
END;

SELECT CONCAT('Trend scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 5: Score — Filing recency bonus (0-10 points)
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
JOIN organization_financials f ON f.ein = s.ein
SET s.score_recency = LEAST(f.filing_recency_score, 10);

SELECT CONCAT('Recency scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 6: Score — Website presence bonus (0-5 points)
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
SET s.score_website = CASE
    WHEN EXISTS (
        SELECT 1 FROM organization_filings f
        WHERE f.ein = s.ein
        AND f.website IS NOT NULL
        AND f.website != ''
    ) THEN 5
    ELSE 0
END;

SELECT CONCAT('Website scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 7: Score — Federal dependency penalty (0-15 points subtracted)
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
SET s.score_federal_penalty = CASE
    WHEN EXISTS (
        SELECT 1 FROM organization_audit_flags a
        WHERE a.ein = s.ein
        AND a.receives_federal_funding = 1
        AND a.federal_expenditure_amount >= 10000000
    ) THEN 15  -- heavily federal dependent
    WHEN EXISTS (
        SELECT 1 FROM organization_audit_flags a
        WHERE a.ein = s.ein
        AND a.receives_federal_funding = 1
    ) THEN 8   -- some federal funding
    ELSE 0
END;

SELECT CONCAT('Federal penalty scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 8: Score — Grant activity history (0-10 points)
-- Based on number of years with filing data
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
SET s.score_grant_activity = CASE
    WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) >= 3 THEN 10
    WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) = 2  THEN 6
    WHEN (SELECT COUNT(*) FROM organization_filings f WHERE f.ein = s.ein) = 1  THEN 3
    ELSE 0
END;

SELECT CONCAT('Grant activity scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 9: Score — Qualification status bonus (0-15 points)
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
JOIN organization_financials f ON f.ein = s.ein
SET s.score_qualification = CASE
    WHEN f.qualification_status = 'priority'  THEN 15
    WHEN f.qualification_status = 'qualified' THEN 10
    WHEN f.qualification_status = 'raw'       THEN 3
    WHEN f.qualification_status = 'excluded'  THEN 0
    ELSE 0
END;

SELECT CONCAT('Qualification scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 10: Compute composite score
-- Sum all components minus federal penalty
-- ─────────────────────────────────────────────────────────────────────────
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
s.computed_at = CURRENT_TIMESTAMP;

SELECT CONCAT('Composite scores computed: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 11: Assign score tiers
-- A = top 10%, B = next 20%, C = next 30%, D = bottom 40%
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_scoring s
SET s.score_tier = CASE
    WHEN s.composite_score >= 70 THEN 'A'
    WHEN s.composite_score >= 50 THEN 'B'
    WHEN s.composite_score >= 30 THEN 'C'
    ELSE 'D'
END;

SELECT CONCAT('Score tiers assigned: ', ROW_COUNT()) AS result;

SET SQL_SAFE_UPDATES = 1;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 12: Summary
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    score_tier,
    COUNT(*)                    AS org_count,
    MIN(composite_score)        AS min_score,
    MAX(composite_score)        AS max_score,
    AVG(composite_score)        AS avg_score
FROM organization_scoring
GROUP BY score_tier
ORDER BY score_tier;

-- Top 20 grantmakers by composite score
SELECT
    s.ein,
    m.org_name,
    m.state,
    m.ntee_code,
    f.qualification_status,
    s.composite_score,
    s.score_tier,
    s.score_assets,
    s.score_giving,
    s.score_recency,
    s.score_federal_penalty
FROM organization_scoring s
JOIN organizations_master m ON m.ein = s.ein
JOIN organization_financials f ON f.ein = s.ein
ORDER BY s.composite_score DESC
LIMIT 20;
