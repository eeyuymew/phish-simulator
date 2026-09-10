from fastapi import FastAPI, Request
import sqlite3
import datetime

app = FastAPI()
DB_PATH = "/app/data/tracker.db"
# Окно дедупликации: nginx mirror может отправить один запрос дважды.
# Повторный клик (email, token, ip) в течение этого окна не фиксируется,
# а поздние повторные переходы сохраняются как отдельные события.
DEDUP_WINDOW_SEC = 5

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL;')  # защита от блокировок БД
    conn.execute('''
        CREATE TABLE IF NOT EXISTS clicks (
            email TEXT,
            token TEXT,
            ip TEXT,
            date TEXT,   -- отображаемая дата перехода (минуты)
            ts TEXT      -- техническое поле для дедупликации (секунды)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.get("/track")
async def track_click(request: Request, email: str = None, token: str = None):
    if email and token:
        # Реальный IP клиента пробрасывается Nginx через заголовок
        ip = request.headers.get("X-Forwarded-For", request.client.host)
        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d %H:%M")
        ts = now.strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_PATH)
        cutoff = (now - datetime.timedelta(seconds=DEDUP_WINDOW_SEC)).strftime("%Y-%m-%d %H:%M:%S")
        dup = conn.execute(
            "SELECT 1 FROM clicks WHERE email=? AND token=? AND ip=? AND ts >= ? LIMIT 1",
            (email, token, ip, cutoff),
        ).fetchone()
        if not dup:
            conn.execute(
                "INSERT INTO clicks (email, token, ip, date, ts) VALUES (?, ?, ?, ?, ?)",
                (email, token, ip, date, ts)
            )
        conn.commit()
        conn.close()
    return {"status": "ok"}
