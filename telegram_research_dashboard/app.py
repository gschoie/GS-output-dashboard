from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from db import connect, initialize

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def rows(sql: str, params=()) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self.api(parsed.path, parse_qs(parsed.query))
        relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        target = (STATIC / relative).resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            return self.send_error(403)
        if not target.is_file():
            target = STATIC / "index.html"
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def api(self, path: str, query: dict):
        search = query.get("q", [""])[0].strip()
        company = query.get("company", [""])[0].strip()
        report_type = query.get("type", [""])[0].strip()
        weekly_folder = query.get("weekly", [""])[0].strip()
        like = f"%{search}%"
        company_like = f"%{company}%"
        if path == "/api/summary":
            stats = rows("""SELECT
              (SELECT COUNT(*) FROM reports) reports,
              (SELECT COUNT(*) FROM news_articles) news,
              (SELECT COUNT(*) FROM reports WHERE target_change='상향') upgrades,
              ((SELECT MAX(imported_at) FROM telegram_messages) || 'Z') updated_at,
              ((SELECT COUNT(*) FROM reports WHERE needs_review=1) +
               (SELECT COUNT(*) FROM news_articles WHERE needs_review=1) +
               (SELECT COUNT(*) FROM telegram_messages m WHERE NOT EXISTS
                 (SELECT 1 FROM reports r WHERE r.message_id=m.id) AND NOT EXISTS
                 (SELECT 1 FROM news_articles n WHERE n.message_id=m.id))) reviews""")[0]
            return self.send_json(stats)
        if path == "/api/reports":
            data = rows("""SELECT r.*,m.posted_at,m.text,m.source_url,m.channel_id,m.message_id telegram_message_id,
                COALESCE((SELECT group_concat(c.name, ', ') FROM report_companies rc
                  JOIN companies c ON c.id=rc.company_id WHERE rc.report_id=r.id),r.company_name) companies_label
                FROM reports r JOIN telegram_messages m ON m.id=r.message_id
                WHERE (r.title LIKE ? OR COALESCE(r.company_name,'') LIKE ? OR m.text LIKE ? OR EXISTS(
                  SELECT 1 FROM report_companies rc JOIN companies c ON c.id=rc.company_id
                  WHERE rc.report_id=r.id AND c.name LIKE ?))
                AND (?='' OR EXISTS(SELECT 1 FROM report_companies rc JOIN companies c ON c.id=rc.company_id
                  WHERE rc.report_id=r.id AND c.name=?))
                AND (?='' OR r.report_type=?)
                AND (?='' OR r.weekly_folder=?) ORDER BY m.posted_at DESC LIMIT 10000""",
                (like, like, like, like, company, company, report_type, report_type,
                 weekly_folder, weekly_folder))
            return self.send_json(data)
        if path == "/api/news":
            data = rows("""SELECT n.*,m.posted_at,m.text,m.source_url,m.channel_id,m.message_id telegram_message_id,
                COALESCE((SELECT group_concat(c.name, ', ') FROM news_companies nc
                  JOIN companies c ON c.id=nc.company_id WHERE nc.news_id=n.id),n.company_name) companies_label
                FROM news_articles n JOIN telegram_messages m ON m.id=n.message_id
                WHERE (n.title LIKE ? OR COALESCE(n.company_name,'') LIKE ? OR m.text LIKE ? OR EXISTS(
                  SELECT 1 FROM news_companies nc JOIN companies c ON c.id=nc.company_id
                  WHERE nc.news_id=n.id AND c.name LIKE ?))
                AND (?='' OR EXISTS(SELECT 1 FROM news_companies nc JOIN companies c ON c.id=nc.company_id
                  WHERE nc.news_id=n.id AND c.name=?))
                ORDER BY m.posted_at DESC LIMIT 20000""",
                (like, like, like, like, company, company))
            return self.send_json(data)
        if path == "/api/companies":
            return self.send_json(rows("""SELECT c.name,COUNT(*) mentions FROM (
                SELECT company_id FROM report_companies
                UNION ALL SELECT company_id FROM news_companies
              ) x JOIN companies c ON c.id=x.company_id
              GROUP BY c.id,c.name ORDER BY mentions DESC,c.name LIMIT 300"""))
        if path == "/api/report-companies":
            return self.send_json(rows("""SELECT c.name,COUNT(*) mentions FROM report_companies rc
              JOIN reports r ON r.id=rc.report_id JOIN companies c ON c.id=rc.company_id
              WHERE r.report_type!='위클리' AND c.name NOT LIKE '%투자증권%'
              GROUP BY c.id,c.name ORDER BY mentions DESC,c.name LIMIT 300"""))
        return self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    initialize()
    port = int(os.getenv("PORT", "8765"))
    print(f"대시보드: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
