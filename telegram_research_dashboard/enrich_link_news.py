"""기존 '기사 제목 미확인' 링크를 원문 제목과 기업명으로 점진 보강한다."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from article_metadata import TITLE_PLACEHOLDERS, enrich_news_item, fetch_article_title
from db import connect, initialize
from telegram_importer import link_companies


def run(limit: int) -> tuple[int, int]:
    initialize()
    placeholders = tuple(TITLE_PLACEHOLDERS)
    sql = """SELECT n.id,n.title,n.article_url,n.event_type,n.summary,n.confidence,n.needs_review
             FROM news_articles n
             LEFT JOIN article_metadata_attempts a ON a.news_id=n.id
             WHERE n.article_url IS NOT NULL AND n.title IN (?,?)
               AND (a.news_id IS NULL OR a.attempted_at < datetime('now','-30 days'))
             ORDER BY CASE WHEN a.news_id IS NULL THEN 0 ELSE 1 END,n.id DESC LIMIT ?"""
    checked = updated = 0
    with connect() as conn:
        rows = conn.execute(sql, (*placeholders, limit)).fetchall()
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as executor:
            titles = list(executor.map(fetch_article_title, (row["article_url"] for row in rows)))
        for row, fetched_title in zip(rows, titles):
            checked += 1
            item = {**dict(row), "companies": [], "company_name": None}
            enrich_news_item(item, lambda _url, title=fetched_title: title)
            success = int(item["title"] not in TITLE_PLACEHOLDERS)
            conn.execute(
                """INSERT INTO article_metadata_attempts(news_id,attempted_at,success)
                   VALUES(?,CURRENT_TIMESTAMP,?) ON CONFLICT(news_id) DO UPDATE SET
                   attempted_at=CURRENT_TIMESTAMP,success=excluded.success""",
                (row["id"], success),
            )
            if item["title"] in TITLE_PLACEHOLDERS:
                continue
            conn.execute(
                """UPDATE news_articles SET title=?,company_name=?,summary=?,confidence=?,needs_review=?
                   WHERE id=?""",
                (item["title"], item["company_name"], item["summary"], item["confidence"],
                 item["needs_review"], row["id"]),
            )
            conn.execute("DELETE FROM news_companies WHERE news_id=?", (row["id"],))
            link_companies(conn, "news_companies", "news_id", row["id"], item["companies"])
            updated += 1
        conn.commit()
    print(f"링크 기사 제목 보강: {updated:,}/{checked:,}건")
    return checked, updated


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--limit", type=int, default=200)
    args = cli.parse_args()
    run(max(1, args.limit))
