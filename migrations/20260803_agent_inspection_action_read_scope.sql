-- Run once per database as the schema owner.
-- The AI account receives SELECT on these views only, never on base tables.

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_inspection_read AS
SELECT inspection_id, company_id, category_id, uid, name, location, cycle, content
FROM inspection
WHERE is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_inspection_history_read AS
SELECT inspection_history_id, company_id, inspection_id, uid, user_name,
       name, location, date, status, is_action_required, content
FROM inspection_history
WHERE is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_action_history_read AS
SELECT
    action_history_id, company_id, inspection_history_id, category_id,
    handler_uid, handler_name, approver_uid, approver_name, action_name,
    type AS source_type,
    CASE
        WHEN type = '게시판' THEN board_id
        WHEN type = '이벤트' THEN event_id
        WHEN type = '점검이력' THEN inspection_history_id
        ELSE NULL
    END AS source_id,
    location, created_at, completed_at, action_status, content,
    approval_status, approval_date, rejection_reason
FROM action_history
WHERE is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_event_category_read AS
SELECT category_id, company_id, category, category_name, level
FROM event_category
WHERE is_deleted = FALSE;

CREATE OR REPLACE SQL SECURITY DEFINER VIEW ai_user_display_read AS
SELECT uid, company_id, name, role
FROM `user`;

-- Apply separately with deployment-managed credentials:
-- GRANT SELECT ON boss_db.ai_inspection_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_inspection_history_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_action_history_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_event_category_read TO 'bp3_ai_reader'@'%';
-- GRANT SELECT ON boss_db.ai_user_display_read TO 'bp3_ai_reader'@'%';
