import sqlite3, os

# RSS DB
rss_db = r'd:\CodeSpace\Odin-Assistant\output\rss\2026-07-15.db'
if os.path.exists(rss_db):
    conn = sqlite3.connect(rss_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('=== RSS DB (2026-07-15) ===')
    print('表:', tables)
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{t[0]}"')
        cnt = cursor.fetchone()[0]
        print(f'  {t[0]}: {cnt} 条记录')
        cursor.execute(f'SELECT * FROM "{t[0]}" LIMIT 2')
        cols = [d[0] for d in cursor.description]
        print(f'  列: {cols}')
        rows = cursor.fetchall()
        for r in rows:
            print(f'    {r}')
    conn.close()
else:
    print('RSS DB 不存在')

# News DB
news_db = r'd:\CodeSpace\Odin-Assistant\output\news\2026-07-15.db'
if os.path.exists(news_db):
    conn = sqlite3.connect(news_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('\n=== News DB (2026-07-15) ===')
    print('表:', tables)
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{t[0]}"')
        cnt = cursor.fetchone()[0]
        print(f'  {t[0]}: {cnt} 条记录')
    conn.close()
else:
    print('News DB 不存在')
