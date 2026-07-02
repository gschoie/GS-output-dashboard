from __future__ import annotations

from datetime import datetime, timedelta, timezone

from db import connect, initialize
from parser import parse_news, parse_report


SAMPLES = [
    ("report", "[한화에어로스페이스] 수출 파이프라인 확대\n투자의견 BUY\n기존 목표주가 900,000원 → 목표주가 1,050,000원\nhttps://example.com/report/1"),
    ("report", "[삼성전자] 메모리 업사이클의 다음 구간\n투자의견 매수\n목표주가 110,000원\nhttps://example.com/report/2"),
    ("report", "[HD한국조선해양] 고선가 선박 매출 인식 본격화\n투자의견 BUY\n기존 목표주가 320,000원 목표주가 350,000원"),
    ("news", "[SK하이닉스] HBM 신규 투자 검토…생산능력 확대\nhttps://example.com/news/1"),
    ("news", "[현대로템] 유럽 지역 추가 수주 계약 기대\nhttps://example.com/news/2"),
    ("news", "[NAVER] AI 검색 서비스 정식 출시\nhttps://example.com/news/3"),
]


def seed():
    initialize()
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM telegram_messages").fetchone()[0]:
            print("데이터가 이미 있어 샘플 입력을 건너뜁니다.")
            return
        now = datetime.now(timezone.utc)
        for index, (kind, text) in enumerate(SAMPLES, 1):
            posted = (now - timedelta(days=index // 2)).isoformat()
            cur = conn.execute("INSERT INTO telegram_messages(channel_id,message_id,posted_at,text) VALUES(?,?,?,?)",
                               ("sample-private", index, posted, text))
            message_id = cur.lastrowid
            if kind == "report":
                data = parse_report(text)
                conn.execute("""INSERT INTO reports(message_id,title,company_name,opinion,target_price,previous_target_price,
                  target_change,original_url,confidence,needs_review)
                  VALUES(:message_id,:title,:company_name,:opinion,:target_price,:previous_target_price,
                  :target_change,:original_url,:confidence,:needs_review)""", {"message_id": message_id, **data})
            else:
                data = parse_news(text)
                conn.execute("""INSERT INTO news_articles(message_id,title,company_name,article_url,event_type,summary,confidence,needs_review)
                  VALUES(:message_id,:title,:company_name,:article_url,:event_type,:summary,:confidence,:needs_review)""",
                  {"message_id": message_id, **data})
        conn.commit()
    print("샘플 데이터 입력 완료")


if __name__ == "__main__":
    seed()

