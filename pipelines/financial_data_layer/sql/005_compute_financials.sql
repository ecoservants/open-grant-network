/* Part 2D: Financial Calculations
   Computes derived fields in organization_financials:
     - avg_giving_3yr
     - avg_assets_3yr
     - giving_trend
     - median_grant_proxy
     - filing_recency_score
   Run AFTER ProPublica filings pipeline has loaded organization_filings.
*/

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 1: 3-year average giving per EIN
-- Uses the 3 most recent filings with giving data
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
JOIN (
    SELECT
        ein,
        ROUND(AVG(total_giving)) AS avg_giving
    FROM (
        SELECT ein, total_giving,
               ROW_NUMBER() OVER (PARTITION BY ein ORDER BY tax_year DESC) AS rn
        FROM organization_filings
        WHERE total_giving IS NOT NULL AND total_giving > 0
    ) ranked
    WHERE rn <= 3
    GROUP BY ein
) calc ON calc.ein = f.ein
SET f.avg_giving_3yr = calc.avg_giving,
    f.updated_at     = CURRENT_TIMESTAMP;

SELECT CONCAT('avg_giving_3yr filled: ', COUNT(*)) AS result
FROM organization_financials
WHERE avg_giving_3yr IS NOT NULL AND avg_giving_3yr > 0;


-- ─────────────────────────────────────────────────────────────────────────
-- STEP 2: 3-year average assets per EIN
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
JOIN (
    SELECT
        ein,
        ROUND(AVG(total_assets)) AS avg_assets
    FROM (
        SELECT ein, total_assets,
               ROW_NUMBER() OVER (PARTITION BY ein ORDER BY tax_year DESC) AS rn
        FROM organization_filings
        WHERE total_assets IS NOT NULL AND total_assets > 0
    ) ranked
    WHERE rn <= 3
    GROUP BY ein
) calc ON calc.ein = f.ein
SET f.avg_assets_3yr = calc.avg_assets,
    f.updated_at     = CURRENT_TIMESTAMP;

SELECT CONCAT('avg_assets_3yr filled: ', COUNT(*)) AS result
FROM organization_financials
WHERE avg_assets_3yr IS NOT NULL AND avg_assets_3yr > 0;


-- STEP 3: Giving trend
UPDATE organization_financials f
JOIN (
    SELECT
        ein,
        CASE
            WHEN COUNT(*) < 2 THEN 'insufficient_data'
            WHEN MAX(CASE WHEN rn = 1 THEN total_giving END) >
                 MAX(CASE WHEN rn = 2 THEN total_giving END) * 1.10
                 THEN 'increasing'
            WHEN MAX(CASE WHEN rn = 1 THEN total_giving END) 
                 MAX(CASE WHEN rn = 2 THEN total_giving END) * 0.90
                 THEN 'decreasing'
            ELSE 'stable'
        END AS trend
    FROM (
        SELECT ein, total_giving,
               ROW_NUMBER() OVER (PARTITION BY ein ORDER BY tax_year DESC) AS rn
        FROM organization_filings
        WHERE total_giving IS NOT NULL AND total_giving > 0
    ) ranked
    WHERE rn <= 2
    GROUP BY ein
) calc ON calc.ein = f.ein
SET f.giving_trend = calc.trend,
    f.updated_at   = CURRENT_TIMESTAMP;


-- ─────────────────────────────────────────────────────────────────────────
-- STEP 4: Median grant proxy
-- Estimated typical grant size = avg_giving / 10 (rough heuristic)
-- Only set where avg_giving is available
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials
SET median_grant_proxy = ROUND(avg_giving_3yr / 10),
    updated_at         = CURRENT_TIMESTAMP
WHERE avg_giving_3yr IS NOT NULL AND avg_giving_3yr > 0;

SELECT CONCAT('estimated_grant_size (median_grant_proxy) filled: ', COUNT(*)) AS result
FROM organization_financials
WHERE median_grant_proxy IS NOT NULL AND median_grant_proxy > 0;

-- ─────────────────────────────────────────────────────────────────────────
-- STEP 5: Filing recency score (0-10)
-- Based on how recently the org filed vs current year (2024)
-- 10 = filed in 2023 or 2024
--  8 = filed in 2022
--  6 = filed in 2021
--  4 = filed in 2020
--  2 = filed in 2019
--  0 = older than 2019 or no filing
-- ─────────────────────────────────────────────────────────────────────────
UPDATE organization_financials f
JOIN (
    SELECT ein, MAX(tax_year) AS latest_year
    FROM organization_filings
    GROUP BY ein
) latest ON latest.ein = f.ein
SET f.filing_recency_score = CASE
    WHEN latest.latest_year IN (2023, 2024) THEN 10
    WHEN latest.latest_year = 2022          THEN 8
    WHEN latest.latest_year = 2021          THEN 6
    WHEN latest.latest_year = 2020          THEN 4
    WHEN latest.latest_year = 2019          THEN 2
    ELSE 0
END,
f.computed_at = CURRENT_TIMESTAMP,
f.updated_at  = CURRENT_TIMESTAMP;

-- Set 0 for orgs with no filings at all
UPDATE organization_financials
SET filing_recency_score = 0
WHERE filing_recency_score IS NULL;

SELECT filing_recency_score, COUNT(*) AS orgs
FROM organization_financials
GROUP BY filing_recency_score
ORDER BY filing_recency_score DESC;


-- ─────────────────────────────────────────────────────────────────────────
-- FINAL SUMMARY
-- ─────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                                              AS total_orgs,
    SUM(CASE WHEN avg_giving_3yr > 0   THEN 1 ELSE 0 END) AS has_avg_giving,
    SUM(CASE WHEN avg_assets_3yr > 0   THEN 1 ELSE 0 END) AS has_avg_assets,
    SUM(CASE WHEN giving_trend IS NOT NULL THEN 1 ELSE 0 END) AS has_trend,
    SUM(CASE WHEN filing_recency_score >= 6 THEN 1 ELSE 0 END) AS recently_filed,
    SUM(CASE WHEN filing_recency_score = 0  THEN 1 ELSE 0 END) AS no_filing_data
FROM organization_financials;
