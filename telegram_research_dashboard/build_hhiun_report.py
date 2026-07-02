"""현중 노조게시판을 수집해 대시보드용 독립 HTML을 만든다."""

from __future__ import annotations

import html
import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "static" / "hhiun_board_report.html"
SNAPSHOT = ROOT / "data" / "hhiun_snapshot.json"
BASE = "http://www.hhiun.or.kr"
BOARD = f"{BASE}/index.php?mid=FreeBoard"
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    "Referer": f"{BASE}/",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def solve_cupid(text: str) -> bool:
    if "cupid.js" not in text:
        return False
    variables = dict(re.findall(
        r'(?:var\s+)?([A-Za-z_$][\w$]*)\s*=\s*toNumbers\s*\(\s*["\']([0-9a-fA-F]+)["\']\s*\)', text
    ))
    match = re.search(
        r'slowAES\.decrypt\s*\(\s*([A-Za-z_$][\w$]*)\s*,\s*2\s*,\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)\s*\)', text
    )
    if not match:
        raise RuntimeError("CUPID 암호화 변수를 찾지 못했습니다")
    cipher_var, key_var, iv_var = match.groups()
    decrypted = AES.new(
        bytes.fromhex(variables[key_var]), AES.MODE_CBC, bytes.fromhex(variables[iv_var])
    ).decrypt(bytes.fromhex(variables[cipher_var]))
    try:
        decrypted = unpad(decrypted, AES.block_size)
    except ValueError:
        pass
    cookie = re.search(r'document\.cookie\s*=\s*["\']([^="\';]+)=["\']\s*\+\s*toHex', text)
    SESSION.cookies.set(cookie.group(1).strip() if cookie else "CUPID", decrypted.hex(), path="/")
    return True


def soup(url: str) -> BeautifulSoup:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    if solve_cupid(response.text):
        time.sleep(0.5)
        response = SESSION.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
    if "cupid.js" in response.text:
        raise RuntimeError("CUPID 보안 페이지가 반복됩니다")
    return BeautifulSoup(response.text, "lxml")


def document_id(url: str) -> str | None:
    found = re.search(r"document_srl=(\d+)", url) or re.search(r"/FreeBoard/(\d+)", url)
    return found.group(1) if found else None


def parse_date(cell) -> datetime:
    text = clean(cell.get_text(" ", strip=True))
    date_match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    year, month, day = map(int, date_match.groups()) if date_match else (NOW.year, NOW.month, NOW.day)
    time_match = re.search(r"(\d{1,2}):(\d{2})", cell.get("title", "")) or re.search(r"(\d{1,2}):(\d{2})", text)
    hour, minute = map(int, time_match.groups()) if time_match else (0, 0)
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def collect() -> list[dict]:
    posts: list[dict] = []
    seen: set[str] = set()
    cutoff = NOW - timedelta(days=35)
    for page in range(1, 31):
        doc = soup(f"{BOARD}&page={page}")
        rows = doc.select("table.restlist tbody tr") or doc.select("form.boardListForm tbody tr")
        oldest = NOW
        for row in rows:
            cells = row.find_all("td", recursive=False) or row.find_all("td")
            if len(cells) < 3 or "공지" in clean(cells[0].get_text(" ", strip=True)):
                continue
            link = next((a for a in row.find_all("a", href=True) if
                         ("document_srl=" in a["href"] or re.search(r"/FreeBoard/\d+", a["href"]))
                         and "#comment" not in a["href"]), None)
            if not link:
                continue
            ident = document_id(link["href"])
            title = clean(link.get_text(" ", strip=True))
            if not ident or ident in seen or not title or title.isdigit():
                continue
            date_cell = row.select_one("td.tabledate")
            if not date_cell:
                continue
            published = parse_date(date_cell)
            oldest = min(oldest, published)
            views = 0
            for cell in reversed(cells):
                if cell is date_cell:
                    continue
                value = clean(cell.get_text(" ", strip=True))
                if re.fullmatch(r"[\d,]+", value):
                    number = int(value.replace(",", ""))
                    if str(number) != ident:
                        views = number
                        break
            small = row.find("small")
            comment_match = re.search(r"\d+", small.get_text(" ", strip=True)) if small else None
            posts.append({
                "id": ident, "title": title, "url": urljoin(BASE, link["href"].replace("&amp;", "&")),
                "published": published, "views": views,
                "comments": int(comment_match.group()) if comment_match else 0,
            })
            seen.add(ident)
        print(f"HHIUN {page}페이지: {len(posts)}개 누적")
        if oldest < cutoff:
            break
        time.sleep(0.5)
    return posts


def body_text(url: str) -> str:
    doc = soup(url)
    body = doc.select_one("div[class*='document_'].xe_content") or doc.select_one("div.xe_content")
    if not body:
        return ""
    for tag in body.select("script,style,iframe,form,button,.comment,[class*='comment_']"):
        tag.decompose()
    return clean(body.get_text(" ", strip=True))


STOP = {"그리고", "그러나", "하지만", "또한", "때문", "대한", "관련", "있다", "없다", "합니다", "했습니다", "있는", "없는", "하는", "되는", "위해", "통해", "우리", "이번"}


def summarize(text: str, limit: int = 330) -> str:
    if not text:
        return "본문을 불러오지 못했습니다."
    if len(text) <= limit:
        return text
    sentences = [clean(x) for x in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if len(clean(x)) >= 15]
    if len(sentences) <= 3:
        return " ".join(sentences)[:limit] + "…"
    frequency = Counter(w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text) if w not in STOP)
    scored = []
    for index, sentence in enumerate(sentences):
        words = re.findall(r"[가-힣A-Za-z0-9]{2,}", sentence)
        score = sum(frequency[w] for w in words) / max(len(words), 1) * max(0.85, 1.15 - index * .02)
        scored.append((score, index))
    chosen = sorted(index for _, index in sorted(scored, reverse=True)[:3])
    result = " ".join(sentences[index] for index in chosen)
    return result[:limit] + ("…" if len(result) > limit else "")


def load_previous() -> tuple[dict, datetime | None]:
    if not SNAPSHOT.exists():
        return {}, None
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return data.get("posts", {}), datetime.fromisoformat(data["captured_at"])
    except Exception:
        return {}, None


def rank(posts: list[dict], days: int, count: int) -> list[dict]:
    # 주간·월간 계산이 서로의 점수를 덮어쓰지 않도록 기간별 복사본 사용
    rows = [dict(p) for p in posts if p["published"] >= NOW - timedelta(days=days)]
    if not rows:
        return []
    for field in ("views", "velocity", "comments"):
        order = sorted(rows, key=lambda p: p[field])
        for index, post in enumerate(order, 1):
            post[f"{field}_pct"] = index / len(order)
    for post in rows:
        post["score"] = 100 * (.45 * post["views_pct"] + .30 * post["velocity_pct"] + .25 * post["comments_pct"])
    return sorted(rows, key=lambda p: (p["score"], p["velocity"], p["views"]), reverse=True)[:count]


def cards(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">해당 기간 게시글이 없습니다.</div>'
    output = []
    for index, post in enumerate(rows, 1):
        increase = f'+{post["increase"]:,}' if post["has_previous"] else "첫 수집"
        output.append(f'''<article class="post"><b class="rank">{index}</b><div><header><a href="{html.escape(post['url'])}" target="_blank" rel="noopener">{html.escape(post['title'])}</a><em>주목도 {post['score']:.1f}</em></header><small>조회 {post['views']:,} · 증가 {increase} · 시간당 {post['velocity']:.1f} · 댓글 {post['comments']:,} · {post['published']:%Y-%m-%d %H:%M}</small><p>{html.escape(post['summary'])}</p></div></article>''')
    return "".join(output)


def write_report(weekly: list[dict], monthly: list[dict], total: int) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>현중 노조게시판 주목 글</title><style>:root{{--bg:#f4f6f3;--ink:#17211d;--muted:#69736e;--line:#dfe4de;--green:#173f35;--lime:#d9f272}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Pretendard,"Noto Sans KR",sans-serif}}main{{max-width:1120px;margin:auto;padding:26px 20px 55px}}.top{{display:flex;justify-content:space-between;align-items:end}}h1{{margin:2px 0 18px}}.top small,small{{color:var(--muted)}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:14px}}.stats div{{background:#fff;border:1px solid var(--line);padding:14px}}.stats b{{display:block;font-size:22px;margin-top:5px}}nav{{display:flex;gap:7px;margin-bottom:10px}}button{{border:1px solid var(--line);background:#fff;padding:9px 17px;cursor:pointer}}button.active{{background:var(--green);color:#fff}}section{{display:none}}section.active{{display:block}}.post{{display:grid;grid-template-columns:45px 1fr;gap:13px;background:#fff;border:1px solid var(--line);padding:15px;margin-bottom:8px}}.rank{{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--green);color:var(--lime)}}.post header{{display:flex;justify-content:space-between;gap:15px}}.post a{{font-weight:700;color:var(--ink);text-decoration:none}}.post em{{font-style:normal;white-space:nowrap;background:#edf2ed;padding:4px 7px;border-radius:10px;font-size:10px}}.post small{{display:block;margin:7px 0}}.post p{{border-top:1px solid #edf0eb;margin:9px 0 0;padding-top:9px;line-height:1.6;font-size:13px;color:#4f5d56}}.empty{{background:#fff;padding:40px;text-align:center}}@media(max-width:650px){{main{{padding:18px 10px}}.top{{display:block}}.stats{{grid-template-columns:1fr 1fr}}.stats div:last-child{{grid-column:1/3}}.post{{grid-template-columns:35px 1fr}}.rank{{width:30px;height:30px}}.post header{{display:block}}.post em{{display:inline-block;margin-top:6px}}}}</style></head><body><main><div class="top"><div><small>UNION BOARD WATCH</small><h1>현중 노조게시판 주목 글</h1></div><small>{NOW:%Y-%m-%d %H:%M} KST 자동 갱신</small></div><div class="stats"><div><small>주간 분석</small><b>{len(weekly)}건</b></div><div><small>월간 분석</small><b>{len(monthly)}건</b></div><div><small>전체 수집</small><b>{total}건</b></div></div><nav><button class="active" data-tab="week">주간 TOP 10</button><button data-tab="month">월간 TOP 15</button></nav><section id="week" class="active">{cards(weekly)}</section><section id="month">{cards(monthly)}</section></main><script>document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('button,section').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')}})</script></body></html>'''
    OUTPUT.write_text(page, encoding="utf-8")


def main() -> None:
    posts = collect()
    if not posts:
        raise RuntimeError("현중 노조게시판 글을 수집하지 못했습니다")
    previous, previous_at = load_previous()
    elapsed = max((NOW - previous_at.astimezone(KST)).total_seconds() / 3600, .25) if previous_at else None
    for index, post in enumerate(posts, 1):
        old = previous.get(post["id"])
        post["has_previous"] = bool(old and elapsed)
        post["increase"] = max(post["views"] - int(old.get("views", 0)), 0) if old else 0
        age = max((NOW - post["published"]).total_seconds() / 3600, 1)
        post["velocity"] = post["increase"] / elapsed if old and elapsed else post["views"] / age
        if post["published"] >= NOW - timedelta(days=31):
            try:
                post["summary"] = summarize(body_text(post["url"]))
            except Exception as exc:
                post["summary"] = f"본문 요약 실패: {exc}"
            if index % 10 == 0:
                print(f"HHIUN 본문 {index}/{len(posts)}")
            time.sleep(0.4)
        else:
            post["summary"] = ""
    weekly = rank(posts, 7, 10)
    monthly = rank(posts, 31, 15)
    write_report(weekly, monthly, len(posts))
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps({
        "captured_at": NOW.isoformat(),
        "posts": {p["id"]: {"views": p["views"], "comments": p["comments"]} for p in posts},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"현중 노조게시판 보고서 생성: {OUTPUT}")


if __name__ == "__main__":
    main()
