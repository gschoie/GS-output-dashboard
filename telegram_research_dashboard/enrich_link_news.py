"""기존 '기사 제목 미확인' 링크를 원문 제목과 기업명으로 점진 보강한다."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from article_metadata import TITLE_PLACEHOLDERS, enrich_news_item, fetch_article_metadata
from db import connect, initialize
from telegram_importer import link_companies


def run(limit: int, force_all: bool = False) -> tuple[int, int]:
    initialize()
    placeholders = tuple(TITLE_PLACEHOLDERS)
    scope = "1=1" if force_all else """(n.title IN (?,?) OR COALESCE(n.company_name,'')=''
                    OR NOT EXISTS (SELECT 1 FROM news_companies nc WHERE nc.news_id=n.id))"""
    attempts = "1=1" if force_all else "(a.news_id IS NULL OR a.attempted_at < datetime('now','-30 days'))"
    sql = f"""SELECT n.id,n.title,n.article_url,n.event_type,n.summary,n.confidence,n.needs_review
             FROM news_articles n
             LEFT JOIN article_metadata_attempts a ON a.news_id=n.id
             WHERE n.article_url IS NOT NULL
               AND {scope} AND {attempts}
             ORDER BY CASE WHEN a.news_id IS NULL THEN 0 ELSE 1 END,n.id DESC LIMIT ?"""
    checked = updated = 0
    with connect() as conn:
        rows = conn.execute(sql, (limit,) if force_all else (*placeholders, limit)).fetchall()
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as executor:
            metadata = list(executor.map(fetch_article_metadata, (row["article_url"] for row in rows)))
        for row, fetched in zip(rows, metadata):
            checked += 1
            item = {**dict(row), "companies": [], "company_name": None}
            enrich_news_item(item, lambda _url, value=fetched: value)
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
    cli.add_argument("--all", action="store_true")
    args = cli.parse_args()
    run(max(1, args.limit), args.all)
