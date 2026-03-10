import sys
import json
import pandas as pd
import threading
import logging
from tkinter import Tk, filedialog, messagebox, Button, Label
from playwright.sync_api import sync_playwright, TimeoutError
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# Fix Unicode trên Windows
if sys.platform.startswith('win') and sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')

# File output
PASS_FILE = "pass.csv"
DEAD_FILE = "dead_acc.xlsx"
MAX_WORKERS = 5

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Keywords lists (expanded languages)
PREMIUM_KEYWORDS = [
    "premium", "premio", "prémium", "prêmio", "prémio", "prēmium",
    "cao cấp", "đặc biệt", "高級", "高级", "高端", "プレミアム", "高級プラン",
    "프리미엄", "고급", "พรีเมียม", "ระดับพรีเมียม", "премиум", "премиальный",
    "بريميوم", "متميز", "de pago", "haut de gamme", "erstklassig",
    "di lusso", "de luxo", "ayrıcalıklı", "प्रीमियम", "उच्च गुणवत्ता",
    "tingkat tinggi"
]
CONFIRM_BUTTON_KEYWORDS = [
    "Continue", "Confirm", "Tiếp tục", "Xác nhận", "確認", "确认", "続行",
    "계속", "확인", "ต่อไป", "ยืนยัน", "Продолжить", "Подтвердить",
    "متابعة", "تأكيد", "Continuar", "Confirmar", "Continuer", "Confirmer",
    "Fortsetzen", "Bestätigen", "Continuare", "Conferma", "Devam et",
    "Onayla", "जारी रखें", "पुष्ट करें", "Lanjutkan", "Konfirmasi"
]
ERROR_MESSAGES = [
    "can't change your plan", "cannot change your plan", "không thể thay đổi gói",
    "ไม่สามารถเปลี่ยนแผนได้", "не можете изменить план"
]

# Chuẩn hóa cookies
def normalize_cookies(raw_cookies):
    normalized = []
    for c in raw_cookies:
        cookie = {k: c.get(k, c.get(k.lower(), '')) for k in ['name', 'value', 'domain', 'path', 'httpOnly', 'secure']}
        cookie['path'] = cookie.get('path', '/')
        ss = c.get('sameSite', '') or c.get('same_site', '')
        if isinstance(ss, str) and ss.lower() in ('strict', 'lax', 'none'):
            cookie['sameSite'] = ss.capitalize()
        if 'expires' in c:
            cookie['expires'] = c['expires']
        normalized.append(cookie)
    return normalized

def parse_cookie_string(cookie_str):
    cookies = []
    for pair in cookie_str.split(";"):
        if "=" in pair:
            name, value = pair.strip().split("=", 1)
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".netflix.com",
                "path": "/",
                "httpOnly": name.lower().startswith("secure"),
                "secure": True,
            })
    return cookies

def check_cookie_session(cookie_json_str):
    try:
        try:
            data = json.loads(cookie_json_str)
            cookies = normalize_cookies(data.get('cookies', []))
        except json.JSONDecodeError:
            cookies = parse_cookie_string(cookie_json_str.strip())

        if not cookies:
            return "cookie_invalid", "Không có cookie hợp lệ"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
            )
            context.set_default_timeout(30000)
            context.add_cookies(cookies)
            page = context.new_page()

            # Truy cập ChangePlan
            page.goto("https://www.netflix.com/ChangePlan", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if "/changeplan" not in page.url.lower():
                browser.close()
                return "account_dead", f"Không vào được ChangePlan, redirect về: {page.url}"

            # Nếu vào được ChangePlan → tiếp tục kiểm tra Extra Members
            page.goto("https://www.netflix.com/account/membership/extra-members", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            extra_url = page.url.lower()

            browser.close()

            if "/account/membership/extra-members" in extra_url:
                return "account_alive", "Tài khoản có slot thành viên bổ sung"
            else:
                return "account_alive", "Truy cập ChangePlan được, nhưng không có slot thành viên bổ sung"

    except Exception as e:
        try:
            browser.close()
        except:
            pass
        return "error", f"Lỗi không xác định: {e}"


def process_file(filepath):
    try:
        df = pd.read_excel(filepath) if filepath.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(filepath)
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không đọc file: {e}")
        return

    for col in ('username', 'password', 'cookies'):
        if col not in df.columns:
            messagebox.showerror("Lỗi định dạng", f"File phải có cột '{col}'")
            return

    has_slot_rows = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(check_cookie_session, str(row['cookies'])): (idx, row)
            for idx, row in df.iterrows()
        }

        for future in as_completed(futures):
            idx, row = futures[future]
            status, reason = future.result()
            logging.info(f"#{idx+1} {row['username']}: {status} - {reason}")

            if status == "account_alive" and "slot thành viên bổ sung" in reason.lower():
                data = row.copy()
                data['status'] = reason
                has_slot_rows.append(data)

    # Ghi ra file CSV duy nhất
    if has_slot_rows:
        pd.DataFrame(has_slot_rows)[['username', 'password', 'cookies', 'status']].to_csv("has_slot.csv", index=False)
        messagebox.showinfo("Hoàn thành", f"✅ Tìm thấy {len(has_slot_rows)} tài khoản có slot → has_slot.csv")
    else:
        messagebox.showinfo("Hoàn thành", "⚠️ Không tìm thấy tài khoản nào có slot thành viên bổ sung.")


    alive_rows, dead_rows = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(check_cookie_session, str(row['cookies'])): (idx, row)
            for idx, row in df.iterrows()
        }
        for future in as_completed(futures):
            idx, row = futures[future]
            status, reason = future.result()
            data = row.copy()
            if status == "account_alive":
                data['status'] = reason
                alive_rows.append(data)
            else:
                data['reason'] = reason
                dead_rows.append(data)
            logging.info(f"#{idx+1} {row['username']}: {status} - {reason}")

    pd.DataFrame(alive_rows)[['username', 'password', 'cookies']].to_csv(PASS_FILE, index=False)
    pd.DataFrame(dead_rows).to_excel(DEAD_FILE, index=False)
    messagebox.showinfo(
        "Hoàn thành",
        f"{len(alive_rows)} sống → {PASS_FILE}\n{len(dead_rows)} chết → {DEAD_FILE}"
    )


def main_gui():
    root = Tk()
    root.title("Netflix Cookie Checker")
    root.geometry("420x200")
    label = Label(root, text="Chọn file tài khoản Netflix", font=("Arial", 12))
    label.pack(pady=20)
    Button(
        root,
        text="Chọn & Bắt đầu",
        font=("Arial", 12),
        command=lambda: threading.Thread(
            target=lambda: process_file(
                filedialog.askopenfilename(
                    title="Chọn file",
                    filetypes=[("Excel", "*.xls;*.xlsx"), ("CSV", "*.csv")]
                ) or ''
            )
        ).start()
    ).pack(pady=10)
    root.mainloop()

if __name__ == "__main__":
    main_gui()
