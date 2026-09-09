import csv
import uuid
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

CSV_FILE = "/app/data/users.csv"
BASE_URL = "http://localhost:8084"

def main():
    print("=== УПРАВЛЕНИЕ РАССЫЛКОЙ ФИШИНГА ===")
    
    # 1. Интерактивный выбор шаблона
    templates_dir = "/app/data"
    html_files = [f for f in os.listdir(templates_dir) if f.endswith(".html")]
    
    print("\nДоступные шаблоны писем:")
    for i, file in enumerate(html_files, 1):
        print(f"{i}. {file}")
        
    choice = input("\nВыберите номер шаблона (по умолчанию 1): ").strip()
    idx = int(choice) - 1 if choice.isdigit() and 0 <= int(choice) - 1 < len(html_files) else 0
    template_path = os.path.join(templates_dir, html_files[idx])
    print(f"[+] Выбран шаблон: {html_files[idx]}")

    # 2. Настройки SMTP (можно захардкодить корпоративные, раз они постоянные)
    smtp_host = input(f"SMTP Host [IP/DNS адрес почтового сервера]: ").strip()
    smtp_port = int(input(f"SMTP Port [по умолчанию: 25]: ").strip() or "25")

    # Читаем выбранный шаблон
    with open(template_path, "r", encoding="utf-8") as t_file:
        template_content = t_file.read()

    # 3. Читаем CSV и отправляем
    print(f"\n[*] Начинаем рассылку через {smtp_host}:{smtp_port}...")
    
    with open(CSV_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row['email'].strip()
            first_name = row.get('first_name', 'Сотрудник').strip()
            last_name = row.get('last_name', '').strip()
            
            token = uuid.uuid4().hex[:8] 
            link = f"{BASE_URL}/?email={email}&token={token}"
            
            msg = MIMEMultipart("alternative")
            msg["From"] = f"security@{smtp_host}"
            msg["To"] = email
            msg["Subject"] = "Важное уведомление безопасности"
            
            html_body = template_content.replace("{{.FirstName}}", first_name)
            html_body = html_body.replace("{{.LastName}}", last_name)
            html_body = html_body.replace("{{.Email}}", email)
            html_body = html_body.replace("{{.URL}}", link)
            
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            try:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.sendmail(msg["From"], email, msg.as_string())
                    print(f"[+] Отправлено: {email} (Token: {token})")
            except Exception as e:
                print(f"[-] Ошибка для {email}: {e}")

    print("\n[+] Рассылка завершена!")

if __name__ == "__main__":
    main()