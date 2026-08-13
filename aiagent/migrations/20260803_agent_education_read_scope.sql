-- Run once per database as the schema owner.
-- The existing AI account receives SELECT on these views only.

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_education_read AS
SELECT
    education_id,
    company_id,
    title,
    video_url,
    category,
    type AS education_type,
    due_date
FROM education
WHERE is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_education_status_read AS
SELECT
    es.uid,
    es.education_id,
    e.company_id,
    es.user_name,
    es.status,
    es.completed_date
FROM education_status AS es
JOIN education AS e ON e.education_id = es.education_id
WHERE es.is_deleted = FALSE
  AND e.is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_education_user_read AS
SELECT uid, company_id, name, role, category
FROM `user`
WHERE company_id IS NOT NULL;

-- Apply separately with deployment-managed credentials:
-- GRANT SELECT ON boss_db.ai_education_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_education_status_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_education_user_read TO 'bp3_ai_reader'@'%';
