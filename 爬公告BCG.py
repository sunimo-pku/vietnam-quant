import os
import time
import random
import pandas as pd
from io import StringIO          # 新增，用于消除警告
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== 配置 ==========
SYMBOL = 'VNL'                   # 改为 BCG
OUTPUT_DIR = r'D:\VN'
os.makedirs(OUTPUT_DIR, exist_ok=True)

TABS = {
    1: 'dividend_issuance',      # 分红和发行
    2: 'listing',                # 上市/退市/状态事件
}

MAX_PAGES = 30                   # 单 tab 最多翻 30 页，防止死循环

# ========== 浏览器启动（防检测） ==========
options = Options()
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

driver = webdriver.Edge(options=options)

# ========== 逐 tab 抓取 ==========
for tab, tab_name in TABS.items():
    print(f"\n{'='*60}")
    print(f"抓取 {SYMBOL} | tab={tab} ({tab_name})")
    print('='*60)

    all_pages = []
    last_page_signature = None
    page = 1

    while page <= MAX_PAGES:
        url = (f"https://finance.vietstock.vn/lich-su-kien.htm"
               f"?page={page}&tab={tab}&code={SYMBOL}&languageid=2")
        print(f"  第 {page} 页: {url}")
        driver.get(url)

        # 等表格渲染
        try:
            wait = WebDriverWait(driver, 30)
            wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), SYMBOL))
            time.sleep(3)
        except Exception as e:
            print(f"    ⚠️ 等待超时，停止翻页: {e}")
            break

        html = driver.page_source
        try:
            # 关键修复：用 StringIO 包装，消除 FutureWarning
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            print(f"    ⚠️ 表格解析失败: {e}")
            break

        # 找含该股票代码的表格
        current_table = None
        for t in tables:
            if SYMBOL in t.to_string() and len(t) > 0:
                current_table = t
                break

        if current_table is None or len(current_table) == 0:
            print(f"    本页无数据，停止翻页")
            break

        # 用“最后一行内容”判断是否翻页到底（重复页面）
        signature = str(current_table.iloc[-1].to_dict())
        if signature == last_page_signature:
            print(f"    本页与上页重复，翻页到底，停止")
            break

        all_pages.append(current_table)
        last_page_signature = signature
        print(f"    ✅ 获取 {len(current_table)} 行")

        page += 1
        # 随机延时，降低被封风险
        wait_sec = random.uniform(3, 6)
        print(f"    等待 {wait_sec:.1f} 秒...")
        time.sleep(wait_sec)

    # ========== 保存本 tab 的结果 ==========
    if all_pages:
        combined = pd.concat(all_pages, ignore_index=True)
        out_path = os.path.join(OUTPUT_DIR, f'{SYMBOL}_tab{tab}_{tab_name}.csv')
        combined.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f"\n✅ tab={tab} 共 {len(combined)} 行 -> {out_path}")
    else:
        print(f"\n❌ tab={tab} 未获取到任何数据")

driver.quit()
print("\n全部完成！")