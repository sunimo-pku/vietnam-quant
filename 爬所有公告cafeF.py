"""
遍历 column_VN.npy 里的所有股票，抓取 CafeF 事件公告，每只股票存一个 CSV。
输出目录: D:/VN/enevt_cafeF
"""

import os
import time
import numpy as np
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== 配置 ==========
SYMBOLS_PATH = "D:/VN/column_VN.npy"
OUT_DIR = "D:/VN/enevt_cafeF"
FAILED_PATH = "D:/VN/cafef_failed_symbols.txt"

MAX_PAGES = 1000
SLEEP_BETWEEN = 2
SKIP_EXISTING = True
PAGE_WAIT = 15

os.makedirs(OUT_DIR, exist_ok=True)

# ========== 读取股票列表 ==========
symbols = np.load(SYMBOLS_PATH, allow_pickle=True)
symbols = [str(s).upper().strip() for s in symbols]
print(f"共 {len(symbols)} 只股票待处理\n")

# ========== 启动浏览器 ==========
options = webdriver.EdgeOptions()
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Edge(options=options)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

failed = []
success = 0
skipped = 0

# ========== 主循环 ==========
for i, sym in enumerate(symbols, 1):
    out_path = os.path.join(OUT_DIR, f"{sym}_cafef_events.csv")

    if SKIP_EXISTING and os.path.exists(out_path):
        skipped += 1
        print(f"[{i}/{len(symbols)}] {sym}: 已存在，跳过")
        continue

    url = f"https://cafef.vn/du-lieu/tin-doanh-nghiep/{sym.lower()}/event.chn"
    all_data = []
    last_first_title = None

    try:
        driver.get(url)
        WebDriverWait(driver, PAGE_WAIT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#divTopEvents ul li"))
        )
        time.sleep(1)

        for page in range(1, MAX_PAGES + 1):
            items = driver.find_elements(By.CSS_SELECTOR, "#divTopEvents ul li")
            if not items:
                break

            try:
                first_title = items[0].find_element(By.CSS_SELECTOR, "a.docnhanhTitle").text.strip()
            except Exception:
                first_title = ""

            if first_title == last_first_title:
                break
            last_first_title = first_title

            for li in items:
                try:
                    date_el = li.find_element(By.CSS_SELECTOR, "span.timeTitle")
                    date = date_el.text.strip()

                    a_el = li.find_element(By.CSS_SELECTOR, "a.docnhanhTitle")
                    title = a_el.text.strip()
                    link = a_el.get_attribute("href")

                    all_data.append({
                        "symbol": sym,
                        "date": date,
                        "title": title,
                        "link": link,
                        "page": page,
                    })
                except Exception:
                    continue

            try:
                next_btn = driver.find_element(By.ID, "aNext")
                if not next_btn.is_enabled():
                    break
                driver.execute_script("arguments[0].click();", next_btn)
                WebDriverWait(driver, PAGE_WAIT).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, "#divTopEvents ul li a.docnhanhTitle").text.strip() != first_title
                )
                time.sleep(0.5)
            except Exception:
                break

        if all_data:
            df = pd.DataFrame(all_data)
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            success += 1
            print(f"[{i}/{len(symbols)}] {sym}: {len(df)} 条 OK")
        else:
            failed.append(sym)
            print(f"[{i}/{len(symbols)}] {sym}: 无数据 FAIL")

    except Exception as e:
        failed.append(sym)
        print(f"[{i}/{len(symbols)}] {sym}: 失败 FAIL {type(e).__name__}: {e}")

    time.sleep(SLEEP_BETWEEN)

driver.quit()

# ========== 汇总 ==========
print(f"\n{'='*60}")
print(f"完成：成功 {success}，跳过 {skipped}，失败 {len(failed)}，总计 {len(symbols)}")

if failed:
    with open(FAILED_PATH, "w", encoding="utf-8") as f:
        for s in failed:
            f.write(s + "\n")
    print(f"失败列表已写入: {FAILED_PATH}")
    print(f"失败代码: {failed[:30]}{' ...' if len(failed) > 30 else ''}")
else:
    print("全部成功")