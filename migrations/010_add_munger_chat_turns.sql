-- Associate the user question and assistant answer belonging to one turn.
ALTER TABLE munger_chats
  ADD COLUMN turn_id VARCHAR(40) NULL AFTER content;

ALTER TABLE munger_chats
  ADD KEY idx_munger_chat_turn (stock_code, turn_id, id);
