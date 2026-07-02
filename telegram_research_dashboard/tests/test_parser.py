import unittest

from article_metadata import enrich_news_item
from parser import classify, parse_news, parse_news_items, parse_report


class ParserTest(unittest.TestCase):
    def test_report_target_change(self):
        result = parse_report("[테스트전자]\n기존 목표주가 80,000원 → 목표주가 100,000원\n투자의견 BUY")
        self.assertEqual(result["company_name"], "테스트전자")
        self.assertEqual(result["previous_target_price"], 80000)
        self.assertEqual(result["target_price"], 100000)
        self.assertEqual(result["target_change"], "상향")

    def test_news(self):
        text = "[테스트중공업] 유럽 수주 계약 체결\nhttps://example.com/a"
        self.assertEqual(classify(text), "news")
        self.assertEqual(parse_news(text)["event_type"], "수주")

    def test_unknown_text_is_preserved_for_review(self):
        self.assertEqual(classify("오늘 시장 메모"), "unclassified")

    def test_hi_gs_compliance_report(self):
        text = """탱커 수주, 한화오션의 FLNG 진출
http://bit.ly/example
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        self.assertEqual(classify(text), "report")
        result = parse_report(text)
        self.assertEqual(result["company_name"], "한화오션")
        self.assertEqual(result["securities_firm"], "다올투자증권")
        self.assertEqual(result["analyst"], "최광식")

    def test_multi_company_report_is_industry_and_keeps_each_company(self):
        text = """HD현대중공업, 한화오션, 삼성중공업 수주 점검
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["report_type"], "산업분석")
        self.assertEqual(set(result["companies"]), {"HD현대중공업", "한화오션", "삼성중공업"})

    def test_sector_hashtag_is_not_a_company(self):
        text = """⛴ #조선 「업황과 주가의 괴리가 메꿔지기 시작」
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["companies"], [])
        self.assertEqual(result["report_type"], "산업분석")

    def test_weekly_folders_follow_brokerage_markers(self):
        cases = (
            ("⚓ 주시뉴스\nhttp://bit.ly/DOS700\nDAOL투자증권 최광식", "다올선박"),
            ("⚓️ 주시뉴스\nhttp://bit.ly/KISS610\n한국투자증권 최광식", "한투시절"),
            ("⚓ 주시 뉴스\n조선/기계/방산 | 최광식 | 하이투자증권", "하이투자증권시절"),
            ("⚓ 주시뉴스\n조선/기계/방산 | 최광식 | ktb투자증권", "다올선박"),
        )
        for text, folder in cases:
            with self.subTest(folder=folder):
                result = parse_report(text)
                self.assertEqual(result["report_type"], "위클리")
                self.assertEqual(result["weekly_folder"], folder)

    def test_brokerage_channel_names_are_not_companies(self):
        for text in ("[다올 시황 김지현] 시장 메모", "[상상인선박기계] 조선 코멘트"):
            with self.subTest(text=text):
                self.assertEqual(parse_report(text)["companies"], [])

    def test_hi_gs_daily_news_splits_links(self):
        text = """[다올투자증권 조선/기계/방산 최광식]
6/25(목) 데일리뉴스
조선
HD현대중공업, 우루과이 군함 입찰 참여
https://example.com/ship
방산
한화시스템, 천궁-II 중동 확장
https://example.com/defense"""
        self.assertEqual(classify(text), "news")
        items = parse_news_items(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["industry"], "조선")
        self.assertEqual(items[0]["company_name"], "HD현대중공업")
        self.assertEqual(items[1]["industry"], "방산")

    def test_markdown_link_and_source_line_are_cleaned(self):
        text = """[제이오션중공업-HD현대중공업 군산조선소 자산 양수도 본계약 체결]
• 신규 프로젝트 법인이 출범함
출처: 전북제일신문
[https://example.com/news?id=1](https://example.com/news?id=1)"""
        item = parse_news_items(text)[0]
        self.assertEqual(item["title"], "[제이오션중공업-HD현대중공업 군산조선소 자산 양수도 본계약 체결]")
        self.assertEqual(item["article_url"], "https://example.com/news?id=1")

    def test_link_only_news_uses_article_title_and_classifies_company(self):
        item = parse_news_items("https://example.com/link-only")[0]
        enrich_news_item(item, lambda _url: "한화오션, 신규 FLNG 수주 계약 체결")
        self.assertEqual(item["title"], "한화오션, 신규 FLNG 수주 계약 체결")
        self.assertEqual(item["companies"], ["한화오션"])
        self.assertEqual(item["company_name"], "한화오션")
        self.assertEqual(item["event_type"], "기타")

    def test_link_only_news_keeps_placeholder_when_fetch_fails(self):
        item = parse_news_items("https://example.com/link-only")[0]
        enrich_news_item(item, lambda _url: None)
        self.assertEqual(item["title"], "기사 제목 미확인")

    def test_comment_title_is_replaced_and_company_comes_from_article_body(self):
        item = parse_news_items("오오..\nhttps://example.com/article")[0]
        enrich_news_item(item, lambda _url: {
            "title": "최성안 부회장, 자사주 1만주 추가 매입",
            "text": "삼성중공업은 책임경영 실천의 일환이라고 밝혔다.",
        })
        self.assertEqual(item["title"], "최성안 부회장, 자사주 1만주 추가 매입")
        self.assertEqual(item["company_name"], "삼성중공업")

    def test_full_quoted_title_and_title_company_override_related_news(self):
        item = parse_news_items("美 ITC, 두산밥캣\nhttps://example.com/article")[0]
        enrich_news_item(item, lambda _url: {
            "title": "美 ITC, 두산밥캣 '특허침해 혐의' 조사 착수…철저한 '법적 대응' 예고",
            "description": "두산밥캣 특허 분쟁 기사",
            "text": "기사 하단 관련 뉴스: LIG D&A 해성 검토",
        })
        self.assertEqual(item["companies"], ["두산밥캣"])

    def test_korean_comment_stuck_to_url_is_not_part_of_url(self):
        item = parse_news_items("https://buly.kr/4bi1ueA오오~")[0]
        self.assertEqual(item["article_url"], "https://buly.kr/4bi1ueA")

    def test_summary_post_uses_korean_headline_not_channel_signature(self):
        text = """> 방산 🛫 Indonesia Pulls Out Of KF-21 Co-Production, Could Acquire Jets Directly From South Korea: Reports
> 인도네시아 KF-21 공동 생산 철회, 한국으로부터 직접 도입 가능성 제기

출처: EurAsian Times
링크: [[https://www.eurasiantimes.com/indonesia-pulls-out-of-kf-21-co-production-could-acquire-jets-directly-from-south-korea-reports/](https://www.eurasiantimes.com/indonesia-pulls-out-of-kf-21-co-production-could-acquire-jets-directly-from-south-korea-reports/)]

* 인도네시아 국방부 대변인, 공동 생산 계획 중단 공식화
-----------------------------------------------------------
🎴 조선/기계/방산 | 최광식 | DAOL투자증권"""
        item = parse_news_items(text)[0]
        self.assertEqual(item["title"], "인도네시아 KF-21 공동 생산 철회, 한국으로부터 직접 도입 가능성 제기")
        self.assertEqual(item["company_name"], "KAI")
        self.assertEqual(item["publisher"], "EurAsian Times")
        self.assertNotIn("최광식", item["title"])


if __name__ == "__main__":
    unittest.main()
