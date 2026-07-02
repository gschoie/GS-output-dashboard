"""저장된 Telegram 원문에 최신 파싱 규칙을 다시 적용한다."""

from datetime import datetime
from types import SimpleNamespace

from db import connect, initialize
from telegram_importer import store_message


def rebuild() -> None:
    initialize()
    with connect() as conn:
        messages = conn.execute(
            "SELECT channel_id,message_id,posted_at,edited_at,text FROM telegram_messages ORDER BY id"
        ).fetchall()
        for index, row in enumerate(messages, 1):
            message = SimpleNamespace(
                id=row["message_id"],
                message=row["text"],
                date=datetime.fromisoformat(row["posted_at"]),
                edit_date=datetime.fromisoformat(row["edited_at"]) if row["edited_at"] else None,
                media=None,
            )
            store_message(conn, row["channel_id"], message)
            if index % 500 == 0:
                conn.commit()
                print(f"{index:,}/{len(messages):,} 재분류")
        conn.commit()
        conn.execute("DELETE FROM companies WHERE id NOT IN (SELECT company_id FROM report_companies UNION SELECT company_id FROM news_companies)")
        conn.commit()
    print(f"재분류 완료: {len(messages):,}개 원문")


if __name__ == "__main__":
    rebuild()
