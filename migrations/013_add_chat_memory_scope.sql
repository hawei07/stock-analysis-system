-- Keep long-term summaries isolated by analysis Skill. Existing summaries are
-- shared so they remain available as a backward-compatible fallback.
ALTER TABLE munger_chat_memory
  ADD COLUMN memory_scope VARCHAR(40) NOT NULL DEFAULT 'shared' AFTER stock_code;

ALTER TABLE munger_chat_memory
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (stock_code, memory_scope);
