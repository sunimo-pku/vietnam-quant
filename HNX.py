"""
HNX 历史公告爬虫 - 无限翻页版
不设页数上限，一直翻到没有新数据为止
可长期使用：每次跑都会自动抓取最新全量
"""

import os
import time
import random
import pandas as pd
from io import StringIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.options import Options

# ========== 配置 ==========
OUT_DIR = r"D:\VN\hnx_official"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "hnx_market_supervision_history_full.csv")

HISTORY_URL = "https://hnx.vn/vi-vn/co-phieu-etfs/chung-khoan-ny-thong-tin.html"
WAIT_SEC = 30
UPDATE_WAIT = 20
MAX_EMPTY_RETRY = 3     # 连续 3 页无变化/无数据，判定到底

options = Options()
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Edge(options=options)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})


def find_history_table():
    """找含 'Ngày đăng tin' + 'Tiêu đề tin' 的表格"""
    try:
        tables = pd.read_html(StringIO(driver.page_source))
    except Exception:
        return None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if any("Ngày đăng" in c for c in cols) and any("Tiêu đề" in c for c in cols):
            return t
    return None


def get_first_row_sig():
    """历史公告表第一行签名（日期+标题），用于判断翻页是否生效"""
    t = find_history_table()
    if t is None or t.empty:
        return None
    try:
        date_col = [c for c in t.columns if "Ngày đăng" in str(c)][0]
        title_col = [c for c in t.columns if "Tiêu đề" in str(c)][0]
        return f"{t.iloc[0][date_col]}|{str(t.iloc[0][title_col])[:60]}"
    except Exception:
        return None


def goto_page(page_num):
    """JS 调用 SeachArticle(pageNum, 1)"""
    try:
        driver.execute_script(f"SeachArticle({page_num}, 1);")
        return True
    except Exception as e:
        print(f"  调用 SeachArticle({page_num}) 失败: {e}")
        return False


# ============================================================
# 主流程
# ============================================================
print("=" * 60)
print("HNX 历史公告爬虫 - 无限翻页版")
print("=" * 60)

driver.get(HISTORY_URL)
WebDriverWait(driver, WAIT_SEC).until(
    EC.presence_of_element_located((By.TAG_NAME, "body"))
)
time.sleep(8)

print(f"[诊断] 当前 URL: {driver.current_url}")
exists = driver.execute_script("return typeof SeachArticle === 'function';")
print(f"[诊断] SeachArticle 可用: {exists}")
if not exists:
    print("SeachArticle 未定义，停止")
    driver.quit()
    raise SystemExit

all_frames = []
last_sig = None
empty_retry = 0

# 抓第 1 页
current = find_history_table()
if current is None or current.empty:
    print("第 1 页未找到历史公告表，停止")
    driver.quit()
    raise SystemExit

current.columns = [str(c).strip() for c in current.columns]
all_frames.append(current)
last_sig = str(current.iloc[-1].to_dict())

date_col = [c for c in current.columns if "Ngày đăng" in c][0]
dates = pd.to_datetime(current[date_col], format="%d/%m/%Y %H:%M", errors="coerce").dropna()
print(f"[1] {len(current)} 行 | {dates.min().date()} ~ {dates.max().date()} | 累计 {sum(len(t) for t in all_frames)}")

# 无限翻页
page = 2
while True:
    before_sig = get_first_row_sig()

    if not goto_page(page):
        print(f"[{page}] 翻页调用失败，结束")
        break

    # 等待表格更新
    updated = False
    try:
        WebDriverWait(driver, UPDATE_WAIT).until(
            lambda d: get_first_row_sig() != before_sig
        )
        updated = True
        time.sleep(0.8)
    except Exception:
        updated = False

    if not updated:
        empty_retry += 1
        print(f"[{page}] 表格未更新 (连续 {empty_retry}/{MAX_EMPTY_RETRY})")
        if empty_retry >= MAX_EMPTY_RETRY:
            print(f"[{page}] 连续 {MAX_EMPTY_RETRY} 页无变化，判定到底，结束")
            break
        page += 1
        time.sleep(1)
        continue

    # 重置连续无变化计数
    empty_retry = 0

    current = find_history_table()
    if current is None or current.empty:
        print(f"[{page}] 未找到历史公告表，结束")
        break

    current.columns = [str(c).strip() for c in current.columns]

    # 用最后一行内容做去重（同页重复）
    sig = str(current.iloc[-1].to_dict())
    if sig == last_sig:
        print(f"[{page}] 本页与上一页重复，翻页到底")
        break
    last_sig = sig

    all_frames.append(current)

    date_col = [c for c in current.columns if "Ngày đăng" in c][0]
    try:
        dates = pd.to_datetime(current[date_col], format="%d/%m/%Y %H:%M", errors="coerce").dropna()
        if len(dates) > 0:
            print(f"[{page}] {len(current)} 行 | {dates.min().date()} ~ {dates.max().date()} | 累计 {sum(len(t) for t in all_frames)}")
        else:
            print(f"[{page}] {len(current)} 行 | 累计 {sum(len(t) for t in all_frames)}")
    except Exception:
        print(f"[{page}] {len(current)} 行 | 累计 {sum(len(t) for t in all_frames)}")

    # 每 50 页存一次中间快照，防止中途崩溃前功尽弃
    if page % 50 == 0:
        tmp_df = pd.concat(all_frames, ignore_index=True)
        tmp_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
        print(f"  [中间保存] {len(tmp_df)} 行 → {OUT_PATH}")

    page += 1
    time.sleep(random.uniform(0.3, 1.0))

driver.quit()

# ============================================================
# 最终保存
# ============================================================
print("\n" + "=" * 60)
if all_frames:
    df = pd.concat(all_frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates()
    after = len(df)
    if before != after:
        print(f"去重: {before} → {after}")

    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n共 {len(df)} 行 → {OUT_PATH}")

    date_col = [c for c in df.columns if "Ngày đăng" in c][0]
    dates = pd.to_datetime(df[date_col], format="%d/%m/%Y %H:%M", errors="coerce").dropna()
    if len(dates) > 0:
        print(f"最早公告日期: {dates.min()}")
        print(f"最新公告日期: {dates.max()}")

    print("\n前 5 行:")
    print(df.head(5).to_string(index=False))
    print("\n后 5 行:")
    print(df.tail(5).to_string(index=False))
else:
    print("未提取到任何数据")