/* Part 3: FAC validation queries */
SELECT COUNT(*) AS audit_flag_rows FROM organization_audit_flags;

SELECT 
    receives_federal_funding,
    COUNT(*) AS orgs
FROM organization_audit_flags
GROUP BY receives_federal_funding;

SELECT 
    audit_year,
    COUNT(*) AS orgs,
    SUM(COALESCE(federal_expenditure_amount, 0)) AS total_federal_expenditure
FROM organization_audit_flags
WHERE audit_year IS NOT NULL
GROUP BY audit_year
ORDER BY audit_year DESC;
