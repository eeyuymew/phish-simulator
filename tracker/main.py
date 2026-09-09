from fastapi import FastAPI, Request
import sqlite3
import datetime

app = FastAPI()
DB_PATH = "/app/data/tracker.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL;') # Защита от блокировок базы
    conn.execute('''
        CREATE TABLE IF NOT EXISTS clicks (
            email TEXT,
            token TEXT,
            ip TEXT,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.get("/track")
async def track_click(request: Request, email: str = None, token: str = None):
    if email and token:
        # Получаем реальный IP от Nginx
        ip = request.headers.get("X-Forwarded-For", request.client.host)
        date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO clicks (email, token, ip, date) VALUES (?, ?, ?, ?)",
            (email, token, ip, date)
        )
        conn.commit()
        conn.close()
    return {"status": "ok"}