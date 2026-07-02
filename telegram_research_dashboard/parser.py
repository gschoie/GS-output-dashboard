"""보수적인 규칙 기반 1차 파서. 원문은 항상 DB에 별도로 보존한다."""

from __future__ import annotations

import re
from urllib.parse import urlparse


# 텔레그램에서 URL 뒤에 공백 없이 붙인 한글 코멘트까지 링크로 먹지 않는다.
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
PRICE_RE = re.compile(r"(?:목표주가|TP)\s*[:：]?\s*([0-9,]+)\s*원?", re.I)
PREVIOUS_PRICE_RE = re.compile(r"(?:기존|종전)\s*(?:목표주가|TP)?\s*[:：]?\s*([0-9,]+)\s*원?", re.I)
OPINION_RE = re.compile(r"(?:투자의견|의견)\s*[:：]?\s*([A-Za-z가-힣 ]{2,16})", re.I)
REPORT_WORDS = ("목표주가", "투자의견", "리포트", "보고서", "기업분석", "산업분석")
REPORT_MARKERS = ("컴플라이언스 승인을 득한 보고서", "컴플 보고서")
DAILY_NEWS_RE = re.compile(r"\d{1,2}/\d{1,2}\([^)]*\)\s*데일리뉴스")
WEEKLY_RE = re.compile(r"주시\s*뉴스")
INDUSTRIES = ("조선", "방산", "기계", "해양", "LNG", "가스선", "컨테이너", "탱커")
KNOWN_COMPANIES = (
    "HD한국조선해양", "HD현대중공업", "HD현대미포", "HD현대", "한화오션",
    "한화에어로스페이스", "한화시스템", "현대로템", "한국항공우주", "KAI",
    "LIG넥스원", "LIG D&A", "풍산", "HJ중공업", "K조선", "현대마린엔진",
    "HD건설기계", "삼성중공업", "두산에너빌리티", "제이오션중공업", "대한항공",
    "두산밥캣", "HD현대건설기계", "HD현대인프라코어",
    "한국카본", "STX엔진", "한화엔진", "HD현대마린솔루션", "SNT다이내믹스",
)
COMPANY_ALIASES = {
    "KF-21": "KAI",
    "KF21": "KAI",
    "보라매": "KAI",
}
CHANNEL_SIGNATURE_RE = re.compile(
    r"(?:조선\s*/\s*기계\s*/\s*방산.*최광식|최광식.*(?:DAOL|다올).*투자증권)", re.I
)
PUBLISHER_RE = re.compile(r"(?:출처|Source)\s*[:：]\s*\[?([^\]\n]+)", re.I)
PUBLISHER_DOMAINS = {
    "yna.co.kr": "연합뉴스", "news1.kr": "뉴스1", "theguru.co.kr": "더구루",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리", "mt.co.kr": "머니투데이", "fnnews.com": "파이낸셜뉴스",
    "chosun.com": "조선일보", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "eurasiantimes.com": "EurAsian Times", "reuters.com": "Reuters",
}


def is_channel_signature(value: str | None) -> bool:
    return bool(value and CHANNEL_SIGNATURE_RE.search(value))


def extract_publisher(text: str, url: str | None = None) -> str | None:
    match = PUBLISHER_RE.search(text)
    if match:
        return match.group(1).strip(" *`[]")[:80]
    if not url:
        return None
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.").removeprefix("m.")
    for domain, publisher in PUBLISHER_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return publisher
    return host or None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip(" -•>\t")
        if clean and not clean.startswith("http") and not is_channel_signature(clean):
            return clean[:180]
    return "제목 미확인"


def _price(match: re.Match[str] | None) -> int | None:
    return int(match.group(1).replace(",", "")) if match else None


def extract_companies(text: str) -> list[str]:
    found = [name for name in KNOWN_COMPANIES if name.casefold() in text.casefold()]
    found.extend(company for alias, company in COMPANY_ALIASES.items() if alias.casefold() in text.casefold())
    if found:
        # 긴 정식 명칭을 우선해 HD현대와 HD현대중공업의 중복을 피한다.
        found.sort(key=len, reverse=True)
        selected = []
        for name in found:
            if not any(name in longer for longer in selected):
                selected.append(name)
        return selected
    patterns = (
        r"\[([가-힣A-Za-z0-9&. ]{2,30})\]",
        r"(?:기업|종목)\s*[:：]\s*([가-힣A-Za-z0-9&. ]{2,30})",
        r"#([가-힣A-Za-z][가-힣A-Za-z0-9&.]*)",
    )
    for pattern in patterns:
        matches = [value.strip() for value in re.findall(pattern, text)]
        matches = [value for value in matches
                   if not any(skip in value for skip in (
                       "투자증권", "데일리뉴스", "다올 시황", "선박기계", "위클리", "주시뉴스", "주시 뉴스"
                   ))
                   and value not in INDUSTRIES and value not in ("조선업", "방위산업")]
        if matches:
            return list(dict.fromkeys(matches))
    return []


def _company(text: str) -> str | None:
    companies = extract_companies(text)
    return ", ".join(companies) if companies else None


def classify(text: str) -> str:
    if any(marker in text for marker in REPORT_MARKERS):
        return "report"
    if DAILY_NEWS_RE.search(text):
        return "news"
    score = sum(word.lower() in text.lower() for word in REPORT_WORDS)
    if score >= 2 or PRICE_RE.search(text):
        return "report"
    if URL_RE.search(text):
        return "news"
    return "unclassified"


def parse_report(text: str) -> dict:
    target_matches = list(PRICE_RE.finditer(text))
    # "기존 목표주가 → 목표주가" 형식에서는 마지막 값을 현재 TP로 본다.
    target = _price(target_matches[-1]) if target_matches else None
    previous = _price(PREVIOUS_PRICE_RE.search(text))
    if target and previous:
        change = "상향" if target > previous else "하향" if target < previous else "유지"
    elif target:
        change = "신규/미확인"
    else:
        change = "미확인"
    opinion = OPINION_RE.search(text)
    urls = URL_RE.findall(text)
    companies = extract_companies(text)
    company = ", ".join(companies) if companies else None
    confidence = min(0.95, 0.45 + (0.2 if company else 0) + (0.2 if target else 0))
    lowered = text.casefold()
    if "한국투자증권" in text:
        firm = "한국투자증권"
    elif "하이투자증권" in text or "hi투자증권" in lowered:
        firm = "하이투자증권"
    elif any(word in lowered for word in ("다올투자증권", "daol투자증권", "ktb투자증권")):
        firm = "다올투자증권"
    else:
        firm = None
    analyst = "최광식" if "최광식" in text else None
    if WEEKLY_RE.search(text):
        report_type = "위클리"
        if "한국투자증권" in text or "kiss" in lowered:
            weekly_folder = "한투시절"
        elif "하이투자증권" in text or "hi투자증권" in lowered:
            weekly_folder = "하이투자증권시절"
        else:
            weekly_folder = "다올선박"
    else:
        report_type = "산업분석" if (len(companies) > 1 or not company and any(word in text for word in ("조선", "방산", "기계"))) else "기업분석"
        weekly_folder = None
    return {
        "title": _first_line(text), "company_name": company,
        "companies": companies,
        "securities_firm": firm, "analyst": analyst, "report_type": report_type,
        "weekly_folder": weekly_folder,
        "opinion": opinion.group(1).strip() if opinion else None,
        "target_price": target, "previous_target_price": previous,
        "target_change": change, "original_url": urls[0] if urls else None,
        "confidence": confidence, "needs_review": int(confidence < 0.8),
    }


def parse_news(text: str) -> dict:
    urls = URL_RE.findall(text)
    article_url = urls[0] if urls else None
    companies = extract_companies(text)
    company = ", ".join(companies) if companies else None
    event_map = {
        "실적": ("실적", "영업이익", "매출"), "수주": ("수주", "계약"),
        "투자": ("투자", "증설"), "정책": ("정책", "정부", "규제"),
        "인수합병": ("인수", "합병", "M&A"), "자금조달": ("유상증자", "회사채", "자금조달"),
    }
    event_type = next((kind for kind, words in event_map.items() if any(w in text for w in words)), "기타")
    confidence = 0.75 if company and urls else 0.55
    return {
        "title": _first_line(text), "company_name": company, "companies": companies,
        "publisher": extract_publisher(text, article_url),
        "article_url": article_url, "event_type": event_type,
        "summary": _first_line(text), "confidence": confidence,
        "needs_review": int(confidence < 0.8),
    }


def parse_news_items(text: str) -> list[dict]:
    """데일리뉴스 묶음에서 제목/URL 쌍을 분리한다. 단독 기사도 한 항목으로 반환한다."""
    lines = [line.strip(" \t•>") for line in text.splitlines()]
    items = []
    current_industry = None
    for index, line in enumerate(lines):
        if line in INDUSTRIES:
            current_industry = line
            continue
        urls = URL_RE.findall(line)
        if not urls:
            continue
        title = None
        candidates = []
        for previous in range(index - 1, max(-1, index - 10), -1):
            candidate = lines[previous]
            if (candidate and not URL_RE.search(candidate) and candidate not in INDUSTRIES
                    and not DAILY_NEWS_RE.search(candidate) and "다올투자증권" not in candidate
                    and not is_channel_signature(candidate)
                    and not candidate.startswith(("출처:", "출처 ", "* 위 내용", "위 내용은"))):
                candidates.append(candidate)
        bracketed = next((candidate for candidate in candidates
                          if candidate.startswith("[") and candidate.endswith("]")
                          and candidate not in ("[TradeWinds]", "[Upstream]")), None)
        title = bracketed or (candidates[0] if candidates else None)
        if title is None:
            for following in range(index + 1, min(len(lines), index + 4)):
                candidate = lines[following]
                if candidate and not URL_RE.search(candidate):
                    title = candidate
                    break
        title = title or "기사 제목 미확인"
        for url in urls:
            parsed = parse_news(f"{title}\n{url}")
            parsed["industry"] = current_industry
            parsed["publisher"] = extract_publisher(text, url)
            companies = extract_companies(title)
            parsed["companies"] = companies
            parsed["company_name"] = ", ".join(companies) if companies else None
            items.append(parsed)
    if not items:
        parsed = parse_news(text)
        parsed["industry"] = next((name for name in INDUSTRIES if name in text), None)
        items.append(parsed)
    # 같은 URL이 본문에 반복된 경우 한 번만 저장한다.
    unique = []
    seen = set()
    for item in items:
        key = item["article_url"] or item["title"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
