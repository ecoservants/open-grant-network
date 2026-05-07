/* Part 5: Deduplication & Data Integrity Controls
   Detects and flags suspicious entries, normalizes fields,
   and maintains a change log of updates.
*/

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 1: Check for invalid EIN formats
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) AS invalid_ein_count
FROM organizations_master
WHERE ein IS NULL
   OR CHAR_LENGTH(ein) <> 9
   OR ein NOT REGEXP '^[0-9]{9}$';

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 2: Check for duplicate EINs
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    ein,
    COUNT(*) AS count
FROM organizations_master
GROUP BY ein
HAVING COUNT(*) > 1
ORDER BY count DESC
LIMIT 20;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 3: Check for missing org names
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) AS missing_name_count
FROM organizations_master
WHERE org_name IS NULL OR TRIM(org_name) = '';

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 4: Normalize state abbreviations
-- Fix any lowercase or non-standard state codes
-- ─────────────────────────────────────────────────────────────────────────
SET SQL_SAFE_UPDATES = 0;

UPDATE organizations_master
SET state = UPPER(TRIM(state)),
    updated_at = CURRENT_TIMESTAMP
WHERE state != UPPER(TRIM(state))
   OR state != TRIM(state);

SELECT CONCAT('State normalization complete') AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 5: Normalize website URLs in organization_filings
-- Ensure all websites start with http:// or https://
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_filings
SET website = CONCAT('http://', website),
    updated_at = CURRENT_TIMESTAMP
WHERE website IS NOT NULL
  AND website != ''
  AND website NOT LIKE 'http%';

SELECT CONCAT('Website normalization complete') AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 6: Normalize ZIP codes
-- Strip to 5 digits where possible
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organizations_master
SET zip = LEFT(TRIM(zip), 5),
    updated_at = CURRENT_TIMESTAMP
WHERE zip IS NOT NULL
  AND CHAR_LENGTH(TRIM(zip)) > 5;

SELECT CONCAT('ZIP normalization complete') AS result;

SET SQL_SAFE_UPDATES = 1;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 7: Flag suspicious entries
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    'Missing state'        AS issue_type,
    COUNT(*)               AS count
FROM organizations_master
WHERE state IS NULL OR TRIM(state) = ''
UNION ALL
SELECT
    'Missing ZIP'          AS issue_type,
    COUNT(*)               AS count
FROM organizations_master
WHERE zip IS NULL OR TRIM(zip) = ''
UNION ALL
SELECT
    'Missing NTEE code'    AS issue_type,
    COUNT(*)               AS count
FROM organizations_master
WHERE ntee_code IS NULL OR TRIM(ntee_code) = ''
UNION ALL
SELECT
    'Missing ruling date'  AS issue_type,
    COUNT(*)               AS count
FROM organizations_master
WHERE ruling_date IS NULL
UNION ALL
SELECT
    'Revoked status'       AS issue_type,
    COUNT(*)               AS count
FROM organizations_master
WHERE status_code IN ('20','22','23','24','28');

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 8: Final integrity summary
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                                                          AS total_orgs,
    SUM(CASE WHEN state IS NOT NULL AND state != '' THEN 1 ELSE 0 END) AS has_state,
    SUM(CASE WHEN zip IS NOT NULL AND zip != ''     THEN 1 ELSE 0 END) AS has_zip,
    SUM(CASE WHEN ntee_code IS NOT NULL AND ntee_code != '' THEN 1 ELSE 0 END) AS has_ntee,
    SUM(CASE WHEN ruling_date IS NOT NULL THEN 1 ELSE 0 END)          AS has_ruling_date,
    SUM(CASE WHEN CHAR_LENGTH(ein) = 9 THEN 1 ELSE 0 END)            AS valid_ein
FROM organizations_master;
