/* Part 6: Grantmaker Qualification Filtering
   Adds qualification_status field to organization_financials
   and applies qualification rules to categorize grantmakers.

   Qualification status values:
   - raw       : not yet evaluated
   - qualified : meets basic thresholds
   - priority  : high-value grantmaker
   - excluded  : does not meet criteria

   Note: grants_paid filter relaxed to assets-only since grants_paid
   is not yet populated — will tighten when 990 XML parsing is complete.
*/

USE grant_tracker;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 1: Add qualification_status column (safe for reruns)
-- ─────────────────────────────────────────────────────────────────────────
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'grant_tracker'
    AND TABLE_NAME = 'organization_financials'
    AND COLUMN_NAME = 'qualification_status'
);

SET @sql = IF(@col_exists = 0,
    "ALTER TABLE organization_financials ADD COLUMN qualification_status ENUM('raw','qualified','priority','excluded') NOT NULL DEFAULT 'raw'",
    "SELECT 'column already exists' AS result"
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add index (safe for reruns)
SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'grant_tracker'
    AND TABLE_NAME = 'organization_financials'
    AND INDEX_NAME = 'idx_qual_status'
);

SET @sql2 = IF(@idx_exists = 0,
    'ALTER TABLE organization_financials ADD INDEX idx_qual_status (qualification_status)',
    "SELECT 'index already exists' AS result"
);

PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

SELECT 'qualification_status column ready' AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 2: Reset all to raw for clean rerun
-- ─────────────────────────────────────────────────────────────────────────
SET SQL_SAFE_UPDATES = 0;

UPDATE organization_financials
SET qualification_status = 'raw',
    updated_at = CURRENT_TIMESTAMP;

SELECT CONCAT('Reset to raw: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 3: Mark excluded orgs
-- No meaningful assets OR no recent filing data
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
SET f.qualification_status = 'excluded',
    f.updated_at = CURRENT_TIMESTAMP
WHERE
    (f.total_assets IS NULL OR f.total_assets < 100000)
    OR f.filing_recency_score = 0;

SELECT CONCAT('Excluded orgs marked: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 4: Mark qualified orgs
-- Assets > $1M AND filed within last 2 years (recency score >= 6)
-- Note: grants_paid filter will be added when 990 XML data is available
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
SET f.qualification_status = 'qualified',
    f.updated_at = CURRENT_TIMESTAMP
WHERE f.qualification_status = 'raw'
  AND f.total_assets >= 1000000
  AND f.filing_recency_score >= 6;

SELECT CONCAT('Qualified orgs marked: ', ROW_COUNT()) AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 5: Mark priority orgs
-- Assets > $10M AND very recent filing (recency score >= 8)
-- Note: giving trend filter will be added when grants_paid is populated
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
SET f.qualification_status = 'priority',
    f.updated_at = CURRENT_TIMESTAMP
WHERE f.qualification_status = 'qualified'
  AND f.total_assets >= 10000000
  AND f.filing_recency_score >= 8;

SELECT CONCAT('Priority orgs marked: ', ROW_COUNT()) AS result;

SET SQL_SAFE_UPDATES = 1;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 6: Summary by qualification status
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    qualification_status,
    COUNT(*)                  AS org_count,
    AVG(total_assets)         AS avg_assets,
    AVG(grants_paid)          AS avg_grants_paid,
    AVG(filing_recency_score) AS avg_recency_score
FROM organization_financials
GROUP BY qualification_status
ORDER BY org_count DESC;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 7: Top 20 qualified + priority orgs
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    m.ein,
    m.org_name,
    m.state,
    m.ntee_code,
    f.qualification_status,
    f.total_assets,
    f.grants_paid,
    f.avg_giving_3yr,
    f.giving_trend,
    f.filing_recency_score
FROM organization_financials f
JOIN organizations_master m ON m.ein = f.ein
WHERE f.qualification_status IN ('qualified', 'priority')
ORDER BY f.total_assets DESC
LIMIT 20;
