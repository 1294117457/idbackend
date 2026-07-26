-- 添加 title 列到 agent_sessions 表（2026-07-24）
-- 为已存在的会话设置默认值
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS title VARCHAR(200) NOT NULL DEFAULT '新会话';
