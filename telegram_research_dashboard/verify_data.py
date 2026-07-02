from db import connect


with connect() as conn:
    print("messages", conn.execute("SELECT COUNT(*) FROM telegram_messages").fetchone()[0])
    print("range", tuple(conn.execute("SELECT MIN(posted_at),MAX(posted_at) FROM telegram_messages").fetchone()))
    print("reports", [tuple(row) for row in conn.execute(
        "SELECT report_type,COUNT(*) FROM reports GROUP BY report_type"
    )])
    print("weekly_folders", [tuple(row) for row in conn.execute(
        "SELECT weekly_folder,COUNT(*) FROM reports WHERE report_type='위클리' GROUP BY weekly_folder"
    )])
    print("news_years", [tuple(row) for row in conn.execute(
        """SELECT substr(m.posted_at,1,4),COUNT(*) FROM news_articles n
           JOIN telegram_messages m ON m.id=n.message_id GROUP BY 1 ORDER BY 1 DESC"""
    )])
    print("relations", tuple(conn.execute(
        "SELECT (SELECT COUNT(*) FROM report_companies),(SELECT COUNT(*) FROM news_companies)"
    ).fetchone()))
    print("sector_company_leaks", conn.execute(
        "SELECT COUNT(*) FROM reports WHERE company_name IN ('조선','방산','기계','해양','LNG','가스선','컨테이너','탱커')"
    ).fetchone()[0])
    print("report_company_metadata_leaks", conn.execute(
        """SELECT COUNT(*) FROM report_companies rc JOIN reports r ON r.id=rc.report_id
           JOIN companies c ON c.id=rc.company_id WHERE r.report_type!='위클리'
           AND (c.name LIKE '%다올%' OR c.name LIKE '%위클리%' OR c.name LIKE '%주시%'
                OR c.name LIKE '%선박기계%' OR c.name LIKE '%투자증권%')"""
    ).fetchone()[0])
