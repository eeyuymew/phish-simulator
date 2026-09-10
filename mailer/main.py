#!/usr/bin/env python3
"""Mailer учебной фишинговой кампании.

Читает список пользователей из CSV, генерирует уникальные токены,
формирует персональные ссылки, отправляет письма через SMTP и
сохраняет выданные токены в отдельную БД SQLite (mailer/data/tokens.db).

Запуск из контейнера:
    docker compose run --rm mailer --smtp-host mail.test.ru --base-url 192.168.0.102

Режимы шифрования:
    --tls   STARTTLS (обычно порт 587)
    --ssl   SMTPS (обычно порт 465)
    без флага — открытое соединение (внутренний relay, порт 25)
"""

import argparse
import csv
import datetime
import os
import smtplib
import sqlite3
import ssl
import sys
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DATA_DIR = "/app/data"
CSV_FILE = os.path.join(DATA_DIR, "users.csv")
TOKENS_DB = os.path.join(DATA_DIR, "tokens.db")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8084")
TRACK_PORT = "8084"  # порт nginx, жёстко задан в docker-compose.yml

TOKENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    link TEXT NOT NULL,
    template TEXT,
    smtp_host TEXT,
    sent_ok INTEGER NOT NULL DEFAULT 0,
    issued_at TEXT NOT NULL
)
"""


def init_tokens_db():
    conn = sqlite3.connect(TOKENS_DB)
    conn.execute(TOKENS_SCHEMA)
    conn.commit()
    conn.close()


def parse_args():
    p = argparse.ArgumentParser(
        description="Рассылка учебных фишинговых писем",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--smtp-host", required=True, help="адрес SMTP-сервера")
    p.add_argument("--smtp-port", type=int, default=25, help="порт SMTP")
    p.add_argument("--from-addr", default=None,
                   help="адрес отправителя (по умолчанию security@<домен из smtp-host>)")
    p.add_argument("--template", default=None,
                   help="имя HTML-шаблона в %s (по умолчанию — единственный .html в каталоге)" % DATA_DIR)
    p.add_argument("--csv", default=CSV_FILE, help="путь к CSV со списком пользователей")
    p.add_argument("--base-url", default=None,
                   help="IP или хост стенда без схемы и порта, например 192.168.0.102 "
                        "(http:// и порт 8084 добавляются автоматически)")
    p.add_argument("--tls", action="store_true", help="использовать STARTTLS")
    p.add_argument("--ssl", action="store_true", help="использовать SMTPS (465)")
    p.add_argument("--dry-run", action="store_true",
                   help="не отправлять письма, только показать ссылки и сохранить токены")
    args = p.parse_args()

    if not args.from_addr:
        # smtp-host вида mail.test.ru -> security@test.ru (две последние метки)
        parts = args.smtp_host.split(".")
        domain = ".".join(parts[-2:]) if len(parts) > 1 else args.smtp_host
        args.from_addr = f"security@{domain}"
    if args.tls and args.ssl:
        p.error("--tls и --ssl несовместимы")
    if args.base_url:
        # Ожидаем голый IP/хост; при этом терпим схему, порт и слэш на конце
        base = args.base_url.rstrip("/").split("://", 1)
        rest = base[1] if len(base) == 2 else base[0]
        if "/" in rest:
            p.error("--base-url: укажите только IP или хост, без пути")
        host = rest.split(":", 1)[0]  # пользовательский порт игнорируем
        args.base_url = f"http://{host}:{TRACK_PORT}"
    else:
        args.base_url = BASE_URL  # годится только для проверки на машине со стендом
    return args


def pick_template(templates_dir: str, name: str | None) -> str:
    """Возвращает путь к выбранному HTML-шаблону."""
    html_files = sorted(f for f in os.listdir(templates_dir) if f.lower().endswith(".html"))
    if not html_files:
        sys.exit(f"[!] В {templates_dir} нет .html шаблонов")
    if name:
        if name not in html_files:
            sys.exit(f"[!] Шаблон '{name}' не найден. Доступны: {', '.join(html_files)}")
        return os.path.join(templates_dir, name)
    if len(html_files) > 1:
        sys.exit(f"[!] В {templates_dir} несколько шаблонов, укажите --template "
                 f"({', '.join(html_files)})")
    return os.path.join(templates_dir, html_files[0])


def send_letters(args, template_path: str):
    with open(template_path, "r", encoding="utf-8") as t_file:
        template_content = t_file.read()

    # Для учебного стенда отключаем проверку сертификата:
    # внутренние SMTP-серверы обычно используют самоподписанные сертификаты
    if args.ssl:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif args.tls:
        context = ssl._create_unverified_context()

    sent = failed = 0
    with open(args.csv, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "email" not in reader.fieldnames:
            sys.exit(f"[!] В {args.csv} нет колонки 'email'")
        for row in reader:
            email = (row.get("email") or "").strip()
            if not email:
                continue
            first_name = row.get("first_name", "Сотрудник").strip() or "Сотрудник"
            last_name = row.get("last_name", "").strip()

            token = uuid.uuid4().hex[:8]
            link = f"{args.base_url}/?email={email}&token={token}"

            html_body = (template_content
                         .replace("{{.FirstName}}", first_name)
                         .replace("{{.LastName}}", last_name)
                         .replace("{{.Email}}", email)
                         .replace("{{.URL}}", link))

            issued_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ok = 0
            if not args.dry_run:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["From"] = args.from_addr
                    msg["To"] = email
                    msg["Subject"] = "Важное уведомление безопасности"
                    msg.attach(MIMEText(html_body, "html", "utf-8"))

                    if args.ssl:
                        server = smtplib.SMTP_SSL(args.smtp_host, args.smtp_port, context=context)
                    else:
                        server = smtplib.SMTP(args.smtp_host, args.smtp_port, timeout=30)
                        if args.tls:
                            server.starttls(context=context)
                    with server:
                        server.sendmail(args.from_addr, email, msg.as_string())
                    print(f"[+] Отправлено: {email} (Token: {token})")
                    ok = 1
                    sent += 1
                except Exception as e:
                    print(f"[-] Ошибка для {email}: {e}")
                    failed += 1
            else:
                print(f"[dry-run] Ссылка для {email}: {link}")
                sent += 1

            # Каждый выданный токен фиксируем, даже если письмо не ушло
            with sqlite3.connect(TOKENS_DB) as conn:
                conn.execute(
                    "INSERT INTO mail_tokens (email, token, link, template, smtp_host, sent_ok, issued_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (email, token, link, os.path.basename(template_path), args.smtp_host, ok, issued_at),
                )

    mode = "dry-run" if args.dry_run else "рассылка"
    print(f"\n[+] {mode} завершена: успешных {sent}, ошибок {failed}. Токены: {TOKENS_DB}")


def main():
    args = parse_args()
    template_path = pick_template(DATA_DIR, args.template)
    print(f"[*] Шаблон: {template_path}")
    print(f"[*] SMTP: {args.smtp_host}:{args.smtp_port}, From: {args.from_addr}"
          f"{' (STARTTLS)' if args.tls else ''}{' (SSL)' if args.ssl else ''}"
          f"{' [DRY-RUN]' if args.dry_run else ''}")
    init_tokens_db()
    send_letters(args, template_path)


if __name__ == "__main__":
    main()
