"""링크만 있는 뉴스에서 안전하게 기사 제목과 기업명을 보강한다."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from parser import extract_companies


TITLE_PLACEHOLDERS = {"기사 제목 미확인", "제목 미확인"}
MAX_HTML_BYTES = 1_500_000
META_TITLE_RE = re.compile(
    r"<meta\b[^>]*(?:property|name)=[\"'](?:og:title|twitter:title)[\"'][^>]*content=[\"']([^\"']+)",
    re.I,
)
META_TITLE_RE_REVERSED = re.compile(
    r"<meta\b[^>]*content=[\"']([^\"']+)[\"'][^>]*(?:property|name)=[\"'](?:og:title|twitter:title)[\"']",
    re.I,
)
HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.I | re.S)
SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>", re.I | re.S)


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("지원하지 않는 기사 URL")
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("로컬 주소는 열지 않음")
    for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("공개 인터넷 주소가 아님")


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _clean_title(value: str) -> str | None:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-|·")
    return value[:240] if len(value) >= 4 else None


def fetch_article_metadata(url: str, timeout: int = 10) -> dict | None:
    """원문 HTML에서 제목과 기업 판별용 본문 텍스트를 반환한다."""
    try:
        _validate_public_url(url)
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; GSResearchDashboard/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            },
        )
        with build_opener(SafeRedirectHandler()).open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                return None
            raw = response.read(MAX_HTML_BYTES + 1)
            if len(raw) > MAX_HTML_BYTES:
                raw = raw[:MAX_HTML_BYTES]
            charset = response.headers.get_content_charset() or "utf-8"
            source = raw.decode(charset, errors="replace")
        match = META_TITLE_RE.search(source) or META_TITLE_RE_REVERSED.search(source) or HTML_TITLE_RE.search(source)
        title = _clean_title(match.group(1)) if match else None
        body_match = BODY_RE.search(source)
        body = body_match.group(1) if body_match else source
        body = SCRIPT_STYLE_RE.sub(" ", body)
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
        body = re.sub(r"\s+", " ", body)[:50_000]
        return {"title": title, "text": body} if title else None
    except (OSError, ValueError, UnicodeError):
        return None


def fetch_article_title(url: str, timeout: int = 10) -> str | None:
    metadata = fetch_article_metadata(url, timeout)
    return metadata["title"] if metadata else None


def enrich_news_item(item: dict, metadata_fetcher=fetch_article_metadata) -> dict:
    """링크 뉴스의 원문 제목과 본문을 기준으로 제목·기업을 보강한다."""
    if not item.get("article_url"):
        return item
    needs_fetch = item.get("title") in TITLE_PLACEHOLDERS or not item.get("company_name")
    if not needs_fetch:
        return item
    fetched = metadata_fetcher(item["article_url"])
    if isinstance(fetched, str):
        fetched = {"title": fetched, "text": fetched}
    title = fetched.get("title") if fetched else None
    if not title:
        return item
    companies = extract_companies(f"{title}\n{fetched.get('text', '')}")
    item["title"] = title
    item["summary"] = title
    item["companies"] = companies
    item["company_name"] = ", ".join(companies) if companies else None
    item["confidence"] = 0.85 if companies else 0.65
    item["needs_review"] = int(not companies)
    return item
