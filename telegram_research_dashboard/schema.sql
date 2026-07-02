PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS telegram_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  posted_at TEXT NOT NULL,
  edited_at TEXT,
  text TEXT NOT NULL DEFAULT '',
  source_url TEXT,
  media_type TEXT,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  ticker TEXT,
  industry TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL UNIQUE REFERENCES telegram_messages(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  report_type TEXT NOT NULL DEFAULT '기업분석',
  weekly_folder TEXT,
  company_name TEXT,
  securities_firm TEXT,
  analyst TEXT,
  opinion TEXT,
  target_price INTEGER,
  previous_target_price INTEGER,
  target_change TEXT,
  original_url TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  needs_review INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS news_articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL REFERENCES telegram_messages(id) ON DELETE CASCADE,
  source_index INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL,
  company_name TEXT,
  industry TEXT,
  publisher TEXT,
  article_url TEXT,
  event_type TEXT NOT NULL DEFAULT '기타',
  sentiment TEXT NOT NULL DEFAULT '중립',
  importance TEXT NOT NULL DEFAULT '보통',
  summary TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  needs_review INTEGER NOT NULL DEFAULT 1,
  UNIQUE(message_id, source_index)
);

CREATE TABLE IF NOT EXISTS report_companies (
  report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  PRIMARY KEY(report_id, company_id)
);

CREATE TABLE IF NOT EXISTS news_companies (
  news_id INTEGER NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  PRIMARY KEY(news_id, company_id)
);

CREATE TABLE IF NOT EXISTS article_metadata_attempts (
  news_id INTEGER PRIMARY KEY REFERENCES news_articles(id) ON DELETE CASCADE,
  attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  success INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_posted_at ON telegram_messages(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_company ON reports(company_name);
CREATE INDEX IF NOT EXISTS idx_news_company ON news_articles(company_name);
CREATE INDEX IF NOT EXISTS idx_report_companies_company ON report_companies(company_id);
CREATE INDEX IF NOT EXISTS idx_news_companies_company ON news_companies(company_id);
