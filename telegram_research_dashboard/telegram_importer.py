"""공개 Telegram 채널의 과거 메시지를 사용자 계정으로 동기화한다."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import timezone

from article_metadata import TITLE_PLACEHOLDERS, enrich_news_item
from db import connect, initialize
from parser import classify, extract_companies, parse_news_items, parse_report


def load_dotenv() -> None:
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as file:
        for raw in file:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


async def find_channel(client, selector: str):
    selector = selector.strip()
    public_link = re.fullmatch(r"https?://(?:www\.)?t\.me/([A-Za-z0-9_]+)/*", selector)
    if public_link:
        selector = "@" + public_link.group(1)
    if selector.lstrip("-").isdigit() or selector.startswith("@"):
        return await client.get_entity(int(selector) if selector.lstrip("-").isdigit() else selector)
    async for dialog in client.iter_dialogs():
        if dialog.name.strip().casefold() == selector.strip().casefold():
            return dialog.entity
    raise RuntimeError(f"공개 채널 주소 또는 대화 목록에서 채널을 찾지 못했습니다: {selector}")


def store_message(conn, channel_id: str, message) -> bool:
    text = message.message or ""
    posted_at = message.date.astimezone(timezone.utc).isoformat()
    edited_at = message.edit_date.astimezone(timezone.utc).isoformat() if message.edit_date else None
    public_name = channel_id.lstrip("@")
    source_url = None if public_name.lstrip("-").isdigit() else f"https://t.me/{public_name}/{message.id}"
    cursor = conn.execute(
        """INSERT INTO telegram_messages(channel_id,message_id,posted_at,edited_at,text,source_url,media_type)
           VALUES(?,?,?,?,?,?,?) ON CONFLICT(channel_id,message_id) DO UPDATE SET
           posted_at=excluded.posted_at, edited_at=excluded.edited_at, text=excluded.text,
           source_url=excluded.source_url,media_type=excluded.media_type""",
        (channel_id, message.id, posted_at, edited_at, text, source_url,
         type(message.media).__name__ if message.media else None),
    )
    row = conn.execute(
        "SELECT id FROM telegram_messages WHERE channel_id=? AND message_id=?", (channel_id, message.id)
    ).fetchone()
    kind = classify(text)
    cached_titles = {
        item["article_url"]: item["title"]
        for item in conn.execute(
            "SELECT article_url,title FROM news_articles WHERE message_id=? AND article_url IS NOT NULL",
            (row["id"],),
        )
    }
    conn.execute("DELETE FROM reports WHERE message_id=?", (row["id"],))
    conn.execute("DELETE FROM news_articles WHERE message_id=?", (row["id"],))
    if kind == "report":
        data = parse_report(text)
        companies = data.pop("companies")
        report_cursor = conn.execute(
            """INSERT INTO reports(message_id,title,report_type,weekly_folder,company_name,securities_firm,analyst,opinion,target_price,
               previous_target_price,target_change,original_url,confidence,needs_review)
               VALUES(:message_id,:title,:report_type,:weekly_folder,:company_name,:securities_firm,:analyst,:opinion,:target_price,:previous_target_price,
               :target_change,:original_url,:confidence,:needs_review)
               """,
            {"message_id": row["id"], **data},
        )
        link_companies(conn, "report_companies", "report_id", report_cursor.lastrowid, companies)
    elif kind == "news":
        for source_index, data in enumerate(parse_news_items(text)):
            cached_title = cached_titles.get(data.get("article_url"))
            if data.get("title") in TITLE_PLACEHOLDERS and cached_title not in TITLE_PLACEHOLDERS and cached_title:
                data["title"] = cached_title
                data["summary"] = cached_title
                data["companies"] = extract_companies(cached_title)
                data["company_name"] = ", ".join(data["companies"]) if data["companies"] else None
            data = enrich_news_item(data)
            companies = data.pop("companies")
            news_cursor = conn.execute(
                """INSERT INTO news_articles(message_id,source_index,title,company_name,industry,publisher,article_url,event_type,summary,confidence,needs_review)
                   VALUES(:message_id,:source_index,:title,:company_name,:industry,:publisher,:article_url,:event_type,:summary,:confidence,:needs_review)""",
                {"message_id": row["id"], "source_index": source_index, **data},
            )
            link_companies(conn, "news_companies", "news_id", news_cursor.lastrowid, companies)
    return cursor.rowcount > 0


def link_companies(conn, relation_table: str, owner_column: str, owner_id: int, names: list[str]) -> None:
    allowed = {("report_companies", "report_id"), ("news_companies", "news_id")}
    if (relation_table, owner_column) not in allowed:
        raise ValueError("지원하지 않는 기업 관계 테이블")
    for name in dict.fromkeys(names):
        conn.execute("INSERT INTO companies(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (name,))
        company_id = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()["id"]
        conn.execute(
            f"INSERT OR IGNORE INTO {relation_table}({owner_column},company_id) VALUES(?,?)",
            (owner_id, company_id),
        )


async def sync(limit: int | None) -> None:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit("먼저 `pip install -r requirements.txt`를 실행해 주세요.") from exc

    load_dotenv()
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    selector = os.getenv("TELEGRAM_CHANNEL")
    if not all((api_id, api_hash, selector)):
        raise SystemExit(".env에 TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHANNEL을 설정해 주세요.")

    initialize()
    session = os.path.join(os.path.dirname(__file__), os.getenv("TELEGRAM_SESSION_PATH", "data/telegram_user"))
    os.makedirs(os.path.dirname(session), exist_ok=True)
    async with TelegramClient(session, int(api_id), api_hash) as client:
        channel = await find_channel(client, selector)
        channel_id = getattr(channel, "username", None) or str(channel.id)
        count = 0
        with connect() as conn:
            async for message in client.iter_messages(channel, limit=limit, reverse=True):
                if message.message or message.media:
                    store_message(conn, channel_id, message)
                    count += 1
            conn.commit()
        print(f"동기화 완료: {count:,}개 메시지 확인")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--limit", type=int, help="최근 N개만 가져오기. 생략하면 전체 기록")
    args = cli.parse_args()
    asyncio.run(sync(args.limit))
