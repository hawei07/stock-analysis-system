-- 保存每次回答使用的报告期、搜索状态、来源和数据质量提示。
ALTER TABLE munger_chats
  ADD COLUMN meta_json JSON DEFAULT NULL AFTER content;
