-- Persist the analysis contract used for each chat message so retries and
-- historical rendering keep the original Skill/model configuration.
ALTER TABLE munger_chats
  ADD COLUMN skill_id VARCHAR(40) DEFAULT NULL AFTER meta_json;

ALTER TABLE munger_chats
  ADD COLUMN skill_version VARCHAR(40) DEFAULT NULL AFTER skill_id;

ALTER TABLE munger_chats
  ADD COLUMN model_id VARCHAR(100) DEFAULT NULL AFTER skill_version;

ALTER TABLE munger_chats
  ADD COLUMN prompt_version VARCHAR(40) DEFAULT NULL AFTER model_id;

ALTER TABLE munger_chats
  ADD COLUMN analysis_config_json JSON DEFAULT NULL AFTER prompt_version;

ALTER TABLE munger_chats
  ADD KEY idx_munger_chat_skill (stock_code, skill_id, id);
