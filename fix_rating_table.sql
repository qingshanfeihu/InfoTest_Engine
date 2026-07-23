-- 修改 sys_chat_rating 表结构以修复评分提交失败问题
-- 问题：thread_id 字段定义为 NOT NULL，但实际可能为空
-- 解决：允许 thread_id 为 NULL，并调整字段长度以匹配 sys_dialog_chat 表

-- 1. 修改字段长度
ALTER TABLE ist_audit.sys_chat_rating ALTER COLUMN session_id TYPE VARCHAR(120);
ALTER TABLE ist_audit.sys_chat_rating ALTER COLUMN conversation_id TYPE VARCHAR(120);
ALTER TABLE ist_audit.sys_chat_rating ALTER COLUMN run_id TYPE VARCHAR(64);
ALTER TABLE ist_audit.sys_chat_rating ALTER COLUMN thread_id TYPE VARCHAR(256);

-- 2. 允许 thread_id 为 NULL
ALTER TABLE ist_audit.sys_chat_rating ALTER COLUMN thread_id DROP NOT NULL;

-- 验证修改
SELECT column_name, data_type, character_maximum_length, is_nullable 
FROM information_schema.columns 
WHERE table_schema = 'ist_audit' AND table_name = 'sys_chat_rating';