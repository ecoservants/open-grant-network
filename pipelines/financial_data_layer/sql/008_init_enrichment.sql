/* Part 7: Intelligence & Keyword Layer
   Creates organization_enrichment table to store structured
   mission tags, program areas, geographic focus, and funding type
   keywords extracted from NTEE codes and 990 filing descriptions.
*/

USE grant_tracker;

-- ─────────────────────────────────────────────────────────────────────────
-- TABLE: organization_enrichment
-- One row per EIN — structured keyword and mission metadata
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organization_enrichment (
    ein                     CHAR(9)         NOT NULL,

    -- Mission and program keywords
    mission_keywords        TEXT            NULL,  -- JSON array
    program_area_keywords   TEXT            NULL,  -- JSON array
    geographic_focus        TEXT            NULL,  -- JSON array
    funding_type_keywords   TEXT            NULL,  -- JSON array
    exclusion_keywords      TEXT            NULL,  -- JSON array

    -- NTEE derived fields
    ntee_major_group        CHAR(1)         NULL,  -- e.g. A, B, E, T
    ntee_major_label        VARCHAR(100)    NULL,  -- e.g. Arts, Education, Health
    ntee_full_label         VARCHAR(255)    NULL,  -- full NTEE description

    -- Program description source
    program_description_raw TEXT            NULL,  -- raw text from 990
    description_source      VARCHAR(50)     NULL,  -- propublica, xml990, manual

    created_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (ein),
    CONSTRAINT fk_enr_ein FOREIGN KEY (ein) REFERENCES organizations_master (ein)
        ON UPDATE CASCADE ON DELETE CASCADE,

    KEY idx_enr_ntee_major  (ntee_major_group),
    KEY idx_enr_updated     (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'organization_enrichment table ready' AS result;

-- ─────────────────────────────────────────────────────────────────────────
-- NTEE Major Group Reference
-- Used to map single-letter NTEE prefix to human-readable label
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ntee_major_groups (
    major_group     CHAR(1)         NOT NULL,
    label           VARCHAR(100)    NOT NULL,
    description     TEXT            NULL,
    PRIMARY KEY (major_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Insert NTEE major group reference data
INSERT IGNORE INTO ntee_major_groups (major_group, label, description) VALUES
('A', 'Arts, Culture & Humanities',    'Museums, performing arts, historical societies'),
('B', 'Education',                      'Schools, universities, libraries, student services'),
('C', 'Environment',                    'Conservation, pollution control, natural resources'),
('D', 'Animal Related',                 'Animal protection, wildlife, veterinary'),
('E', 'Health',                         'Hospitals, clinics, health services, mental health'),
('F', 'Mental Health & Crisis',         'Mental health treatment, substance abuse, crisis'),
('G', 'Disease & Disorder Research',    'Disease research, patient support groups'),
('H', 'Medical Research',               'Medical and scientific research institutions'),
('I', 'Crime & Legal Services',         'Crime prevention, legal aid, rehabilitation'),
('J', 'Employment',                     'Job training, employment services, labor'),
('K', 'Food, Agriculture & Nutrition',  'Food banks, farming, nutrition programs'),
('L', 'Housing & Shelter',              'Affordable housing, homeless services'),
('M', 'Public Safety',                  'Disaster relief, fire, emergency services'),
('N', 'Recreation & Sports',            'Parks, sports leagues, camps, recreation'),
('O', 'Youth Development',              'Youth programs, scouting, mentoring'),
('P', 'Human Services',                 'Social services, family services, aging'),
('Q', 'International',                  'International relief, development, peace'),
('R', 'Civil Rights & Advocacy',        'Civil rights, social action, advocacy'),
('S', 'Community Improvement',          'Community development, neighborhood associations'),
('T', 'Philanthropy & Grantmaking',     'Foundations, grantmaking, fundraising'),
('U', 'Science & Technology',           'Scientific research, technology transfer'),
('V', 'Social Science Research',        'Policy research, think tanks'),
('W', 'Public Affairs & Society',       'Government, public policy, civic organizations'),
('X', 'Religion',                       'Religious congregations, faith organizations'),
('Y', 'Mutual Benefit',                 'Credit unions, insurance, pension funds'),
('Z', 'Unknown',                        'Unclassified organizations');

SELECT 'NTEE major groups reference data loaded' AS result;
