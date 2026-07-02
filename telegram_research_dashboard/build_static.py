"""SQLite 데이터와 화면 자산을 한 개의 독립 HTML 파일로 묶는다."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import connect, initialize


ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.getenv("DASHBOARD_OUTPUT", ROOT.parent / "GS_최광식_리서치_대시보드.html"))


def records(conn, sql: str) -> list[dict]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    initialize()
    with connect() as conn:
        summary = dict(conn.execute("""SELECT
          (SELECT COUNT(*) FROM reports) reports,
          (SELECT COUNT(*) FROM news_articles) news,
          (SELECT COUNT(*) FROM reports WHERE target_change='상향') upgrades,
          ((SELECT COUNT(*) FROM reports WHERE needs_review=1) +
           (SELECT COUNT(*) FROM news_articles WHERE needs_review=1) +
           (SELECT COUNT(*) FROM telegram_messages m WHERE NOT EXISTS
             (SELECT 1 FROM reports r WHERE r.message_id=m.id) AND NOT EXISTS
             (SELECT 1 FROM news_articles n WHERE n.message_id=m.id))) reviews""").fetchone())
        summary["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
        reports = records(conn, """SELECT r.*,m.posted_at,m.source_url,
          COALESCE((SELECT group_concat(c.name, ', ') FROM report_companies rc
            JOIN companies c ON c.id=rc.company_id WHERE rc.report_id=r.id),r.company_name) companies_label
          FROM reports r JOIN telegram_messages m ON m.id=r.message_id ORDER BY m.posted_at DESC""")
        news = records(conn, """SELECT n.*,m.posted_at,m.source_url,
          COALESCE((SELECT group_concat(c.name, ', ') FROM news_companies nc
            JOIN companies c ON c.id=nc.company_id WHERE nc.news_id=n.id),n.company_name) companies_label
          FROM news_articles n JOIN telegram_messages m ON m.id=n.message_id ORDER BY m.posted_at DESC""")
        companies = records(conn, """SELECT c.name,COUNT(*) mentions FROM (
          SELECT company_id FROM report_companies UNION ALL SELECT company_id FROM news_companies
          ) x JOIN companies c ON c.id=x.company_id GROUP BY c.id,c.name
          ORDER BY mentions DESC,c.name""")
        report_companies = records(conn, """SELECT c.name,COUNT(*) mentions FROM report_companies rc
          JOIN reports r ON r.id=rc.report_id JOIN companies c ON c.id=rc.company_id
          WHERE r.report_type!='위클리' AND c.name NOT LIKE '%투자증권%'
          GROUP BY c.id,c.name ORDER BY mentions DESC,c.name""")
        for report in reports:
            report["company_names"] = [row[0] for row in conn.execute(
                """SELECT c.name FROM report_companies rc JOIN companies c ON c.id=rc.company_id
                   WHERE rc.report_id=? ORDER BY c.name""", (report["id"],)
            )]
        for article in news:
            article["company_names"] = [row[0] for row in conn.execute(
                """SELECT c.name FROM news_companies nc JOIN companies c ON c.id=nc.company_id
                   WHERE nc.news_id=? ORDER BY c.name""", (article["id"],)
            )]

    tone_path = ROOT / "data" / "daol_tone_history.json"
    tone = json.loads(tone_path.read_text(encoding="utf-8")) if tone_path.exists() else {"months": [], "report_count": 0}
    payload = json.dumps(
        {"summary": summary, "reports": reports, "news": news, "companies": companies,
         "reportCompanies": report_companies, "tone": tone},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/styles.css">', f"<style>{css}</style>")
    html = html.replace(
        '<script src="/app.js"></script>',
        f"<script>window.__DASHBOARD_DATA__={payload};</script>\n<script>{javascript}</script>",
    )
    OUTPUT.write_text(html, encoding="utf-8")
    union_report = ROOT / "static" / "hhiun_board_report.html"
    if union_report.exists():
        shutil.copy2(union_report, OUTPUT.parent / "hhiun_board_report.html")
    if tone_path.exists():
        (OUTPUT.parent / "daol_tone_history.json").write_text(
            json.dumps(tone, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    print(f"생성 완료: {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    return OUTPUT


if __name__ == "__main__":
    build()
