USE grant_tracker;

SELECT COUNT(*) AS master_rows FROM organizations_master;

SELECT COUNT(*) AS bad_ein
FROM organizations_master
WHERE ein IS NULL OR CHAR_LENGTH(ein) <> 9;

SELECT subsection_code, COUNT(*) c
FROM organizations_master
GROUP BY subsection_code
ORDER BY c DESC;

SELECT status_code, COUNT(*) c
FROM organizations_master
GROUP BY status_code
ORDER BY c DESC
LIMIT 20;

SELECT state, COUNT(*) c
FROM organizations_master
GROUP BY state
ORDER BY c DESC
LIMIT 20;

SELECT run_id, pipeline_name, source_posting_date, status, rows_read, rows_after_filter, distinct_ein_loaded, started_at, finished_at
FROM pipeline_runs
ORDER BY run_id DESC
LIMIT 5;