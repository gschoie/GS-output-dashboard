"""공개 Telegram 웹 미리보기에서 글을 가져오는 무로그인 수집기.

공식 API 수집보다 HTML 변경에 취약하므로 간편 시작/백업 경로로 사용한다.
"""

from __future__ import annotations

import argparse
import html
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from db import connect, initialize
from telegram_importer import load_dotenv, store_message


POST_RE = re.compile(r'data-post="([^"/]+)/([0-9]+)"')
DATETIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
BLOCK_RE = re.compile(
    r'(<div class="tgme_widget_message_wrap[^>]*>.*?)(?=<div class="tgme_widget_message_wrap|<div class="tgme_widget_message_centered|\Z)',
    re.S,
)


class MessageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get("class", "").split()
        if tag == "div" and "tgme_widget_message_text" in classes:
            self.capture = True
            self.depth = 1
            return
        if self.capture:
            if tag == "div":
                self.depth += 1
            if tag == "br":
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.capture and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def normalize_channel(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("@"):
        return value[1:]
    if "t.me/" in value:
        return urlparse(value).path.strip("/").removeprefix("s/")
    return value


def fetch_page(channel: str, before: int | None) -> str:
    url = f"https://t.me/s/{channel}"
    if before:
        url += f"?before={before}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResearchDashboard/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_page(source: str) -> list[SimpleNamespace]:
    messages = []
    for block in BLOCK_RE.findall(source):
        post = POST_RE.search(block)
        stamp = DATETIME_RE.search(block)
        if not post or not stamp:
            continue
        parser = MessageTextParser()
        parser.feed(block)
        text = parser.text()
        if not text:
            continue
        messages.append(SimpleNamespace(
            id=int(post.group(2)), message=text,
            date=datetime.fromisoformat(stamp.group(1).replace("Z", "+00:00")),
            edit_date=None, media=None,
        ))
    return messages


def sync(channel_value: str, pages: int) -> None:
    initialize()
    channel = normalize_channel(channel_value)
    before = None
    seen_ids: set[int] = set()
    total = 0
    page = 0
    with connect() as conn:
        while pages == 0 or page < pages:
            batch = parse_page(fetch_page(channel, before))
            fresh = [message for message in batch if message.id not in seen_ids]
            if not fresh:
                break
            for message in sorted(fresh, key=lambda item: item.id):
                store_message(conn, channel, message)
                seen_ids.add(message.id)
                total += 1
            conn.commit()
            oldest = min(message.id for message in fresh)
            if before == oldest:
                break
            before = oldest
            page += 1
            print(f"{page}페이지 · 누적 {total:,}개")
            time.sleep(0.4)
    print(f"@{channel} 공개채널 동기화 완료: {total:,}개 메시지")


if __name__ == "__main__":
    load_dotenv()
    import os
    cli = argparse.ArgumentParser()
    cli.add_argument("--channel", default=os.getenv("TELEGRAM_CHANNEL", "https://t.me/HI_GS"))
    cli.add_argument("--pages", type=int, default=5, help="가져올 페이지 수. 0이면 가능한 과거 기록 전체")
    args = cli.parse_args()
    sync(args.channel, args.pages)

