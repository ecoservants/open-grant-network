/* Step 1: Creating DB and core tables for EO BMF Master Universe */

CREATE DATABASE IF NOT EXISTS grant_tracker
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE grant_tracker;

/* Storing one row per EIN, the unified master universe */
CREATE TABLE IF NOT EXISTS organizations_master (
  ein                 CHAR(9)      NOT NULL,
  org_name            VARCHAR(255) NOT NULL,

  street              VARCHAR(255) NULL,
  city                VARCHAR(100) NULL,
  state               CHAR(2)      NULL,
  zip                 VARCHAR(10)  NULL,

  subsection_code     CHAR(2)      NULL,
  foundation_code     CHAR(2)      NULL,
  ntee_code           VARCHAR(4)   NULL,
  status_code         VARCHAR(10)  NULL,
  ruling_date         DATE         NULL,

  source_file         VARCHAR(255) NULL,
  source_posting_date DATE         NULL,

  created_at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (ein),

  KEY idx_state (state),
  KEY idx_ntee (ntee_code),
  KEY idx_subsection (subsection_code),
  KEY idx_foundation (foundation_code),
  KEY idx_status (status_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

/* Staging table for safe reruns and clean upserts */
CREATE TABLE IF NOT EXISTS organizations_master_staging LIKE organizations_master;

/* Tracking pipeline runs and QA counts, useful for debugging and future automation */
CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id              BIGINT       NOT NULL AUTO_INCREMENT,
  pipeline_name       VARCHAR(100) NOT NULL,        /* e.g. bmf_master */
  source_name         VARCHAR(100) NOT NULL,        /* e.g. irs_eo_bmf */
  source_posting_date DATE         NULL,

  started_at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at         TIMESTAMP    NULL,

  status              ENUM('STARTED','SUCCESS','FAILED') NOT NULL DEFAULT 'STARTED',
  error_message       TEXT         NULL,

  rows_read           BIGINT       NULL,
  rows_valid_ein      BIGINT       NULL,
  rows_after_filter   BIGINT       NULL,
  rows_excluded       BIGINT       NULL,
  rows_upserted       BIGINT       NULL,
  distinct_ein_loaded BIGINT       NULL,

  PRIMARY KEY (run_id),
  KEY idx_pipeline_name (pipeline_name),
  KEY idx_posting_date (source_posting_date),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;