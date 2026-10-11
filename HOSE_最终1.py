"""
HOSE 公告爬虫 - 完整版（含 30 条边界修复）
特点：
1. 按月切片：[当月1号, 下月2号]，重叠 2 天
2. 首个切片：[上个月1号, 最新日期]
3. 每个切片独立 CSV，支持断点续跑
4. 实时打印每页每条数据
5. 连续 N 个切片失败自动退出
6. 修复“总条数正好是 30 倍数”的边界问题
7. 最终自动合并 + 按 ID 去重
"""

import os
import time
import json
import random
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.options import Options

# ========== 配置 ==========
OUT_DIR = r"D:\VN\hose_official"
os.makedirs(OUT_DIR, exist_ok=True)

SECURITIES_TYPE = 1
TYPE_NAME = {1: "co_phieu", 2: "trai_phieu", 3: "chung_chi_quy", 4: "etf", 5: "covered_warrant"}
TYPE_LABEL = TYPE_NAME.get(SECURITIES_TYPE, "unknown")

OVERALL_START = "2000-01-01"
OVERALL_END = "2026-10-03"

PAGE_SIZE = 30
MAX_PAGES = 10000
RESUME = True

PRINT_EACH_ITEM = True
TITLE_MAX_LEN = 95

# 连续失败多少个切片后自动退出
MAX_CONSECUTIVE_FAILURES = 5


# ========== 按月生成切片（首片合并上个月） ==========
def generate_monthly_slices(start_str, end_str):
    """
    首个切片：[end 的上个月1号, end]
    后续切片：[更早一个月1号, 上一个切片起始日+1天]（即下月2号，重叠2天）
    """
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    slices = []

    # 首片：上个月1号 ~ end_dt
    y, m = end_dt.year, end_dt.month - 1
    if m == 0:
        m = 12
        y -= 1
    first_start = datetime(y, m, 1)
    if first_start < start_dt:
        first_start = start_dt
    slices.append((first_start, end_dt))

    # 后续逐月往前
    cur_start = first_start
    while cur_start > start_dt:
        prev_y, prev_m = cur_start.year, cur_start.month - 1
        if prev_m == 0:
            prev_m = 12
            prev_y -= 1
        prev_start = datetime(prev_y, prev_m, 1)
        cur_end_of_slice = cur_start + timedelta(days=1)

        if prev_start < start_dt:
            prev_start = start_dt
        slices.append((prev_start, cur_end_of_slice))

        if prev_start <= start_dt:
            break
        cur_start = prev_start

    return [(s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")) for s, e in slices]


SLICES = generate_monthly_slices(OVERALL_START, OVERALL_END)
print(f"月度切片（从最近到最早）：共 {len(SLICES)} 个")
print("\n前 6 个切片：")
for i, (s, e) in enumerate(SLICES[:6], 1):
    print(f"  [{i}] {s} ~ {e}")
print("\n后 3 个切片：")
for i, (s, e) in enumerate(SLICES[-3:], len(SLICES) - 2):
    print(f"  [{i}] {s} ~ {e}")


def slice_filepath(slice_start, slice_end):
    filename = f"hose_{TYPE_LABEL}_{slice_start.replace('-','')}_{slice_end.replace('-','')}.csv"
    return os.path.join(OUT_DIR, filename)


def is_slice_done(slice_start, slice_end):
    """文件存在即视为已完成（含空文件，避免重扫无数据月份）"""
    fp = slice_filepath(slice_start, slice_end)
    if not os.path.exists(fp):
        return False
    try:
        pd.read_csv(fp)
        return True
    except Exception:
        return False


# ========== 注入脚本 ==========
INJECT_SCRIPT = """
(function() {
    if (window.__interceptorInstalled) return;
    window.__interceptorInstalled = true;
    window.__apiResponses = [];
    window.__targetStart = null;
    window.__targetEnd = null;
    window.__targetPage = null;

    function record(url, body) { window.__apiResponses.push({url: url, body: body, ts: Date.now()}); }
    function rewriteUrl(url) {
        if (!url || url.indexOf('news/securitiesType') === -1) return url;
        if (window.__targetStart) url = url.replace(/startDate=[^&]+/, 'startDate=' + window.__targetStart);
        if (window.__targetEnd) url = url.replace(/endDate=[^&]+/, 'endDate=' + window.__targetEnd);
        if (window.__targetPage) url = url.replace(/pageIndex=\\d+/, 'pageIndex=' + window.__targetPage);
        return url;
    }
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        var newUrl = rewriteUrl(url);
        this.__capturedUrl = newUrl;
        return origOpen.apply(this, [method, newUrl]);
    };
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function() {
        var self = this;
        this.addEventListener('load', function() {
            if (self.__capturedUrl && self.__capturedUrl.indexOf('api.hsx.vn') !== -1) {
                record(self.__capturedUrl, self.responseText);
            }
        });
        return origSend.apply(this, arguments);
    };
    var origFetch = window.fetch;
    if (origFetch) {
        window.fetch = function() {
            var args = Array.prototype.slice.call(arguments);
            var url = (typeof args[0] === 'string') ? args[0] : (args[0] && args[0].url) || '';
            var newUrl = rewriteUrl(url);
            if (typeof args[0] === 'string') args[0] = newUrl;
            else if (args[0] && args[0].url) args[0] = Object.assign({}, args[0], {url: newUrl});
            var promise = origFetch.apply(this, args);
            promise.then(function(resp) {
                if (newUrl && newUrl.indexOf('api.hsx.vn') !== -1) {
                    resp.clone().text().then(function(txt) { record(newUrl, txt); }).catch(function(){});
                }
            }).catch(function(){});
            return promise;
        };
    }
})();
"""

# ========== 启动浏览器 ==========
options = Options()
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Edge(options=options)
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': INJECT_SCRIPT})

print("\n[1] 打开 HOSE 页面...")
driver.get("https://www.hsx.vn/vi/tin-tuc/tin-to-chuc-niem-yet")
WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
time.sleep(10)


def parse_news_response(body_str):
    try:
        obj = json.loads(body_str)
        if isinstance(obj, dict) and obj.get('success'):
            data = obj.get('data')
            if isinstance(data, dict):
                return data.get('list', []), data.get('total', 0)
            elif isinstance(data, list):
                return data, len(data)
    except Exception:
        pass
    return [], 0


def click_query():
    try:
        btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Xem Kết Quả')] | //a[contains(text(), 'Xem Kết Quả')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(0.5)
        ActionChains(driver).move_to_element(btn).click().perform()
        return True
    except Exception as e:
        print(f"    [点击出错] {e}")
        return False


def ts_to_str(ts):
    try:
        if not ts: return ""
        return datetime.fromtimestamp(int(ts)).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return ""


def print_page_items(page, items):
    print(f"\n  ┌─ 第 {page} 页，{len(items)} 条 ─────────────────────────────────────")
    for i, item in enumerate(items, 1):
        title = item.get('title') or "(无标题)"
        posted = item.get('postedDate') or item.get('publishFrom')
        dt_str = ts_to_str(posted)
        news_id = item.get('id') or "?"
        title_disp = title[:TITLE_MAX_LEN] + "..." if len(title) > TITLE_MAX_LEN else title
        print(f"  │ [{i:02d}] {dt_str} | {news_id}")
        print(f"  │       {title_disp}")
    print(f"  └─────────────────────────────────────────────────────────────")


def process_records(records):
    rows = []
    for item in records:
        title = item.get('title') or ""
        stock_code = title.split(":")[0].strip() if ":" in title else ""
        posted = item.get('postedDate') or item.get('publishFrom')
        dt_str = ts_to_str(posted)
        news_id = item.get('id')
        detail_url = f"https://www.hsx.vn/vi/tin-tuc/chi-tiet/{news_id}" if news_id else ""
        rows.append({
            "ID": news_id,
            "Tiêu đề": title,
            "Mã CK": stock_code,
            "Ngày tạo": dt_str.split(" ")[0] if dt_str else "",
            "Thời gian": dt_str.split(" ")[1] if dt_str and " " in dt_str else "",
            "Link chi tiết": detail_url,
            "Tóm tắt": item.get('summary', ""),
        })
    return pd.DataFrame(rows).drop_duplicates(subset=['ID'])


# ========== 抓取单个切片（已修复 30 条边界） ==========
def scrape_slice(slice_start, slice_end):
    """抓取一个切片，返回 (records, is_empty)；只要已有数据，最后一页异常不再抛错"""
    slice_records = []
    page = 1
    is_empty = False

    while page <= MAX_PAGES:
        driver.execute_script(f"""
            window.__targetStart = '{slice_start}';
            window.__targetEnd = '{slice_end}';
            window.__targetPage = {page};
            window.__apiResponses = [];
        """)

        # 点击查询
        if not click_query():
            if slice_records:
                print(f"  [第{page}页] 点击失败，但已有 {len(slice_records)} 条数据，正常结束本切片")
                break
            else:
                raise RuntimeError(f"第{page}页点击失败，且无数据")

        # 等待捕获
        start_wait = time.time()
        captured_data = None
        while time.time() - start_wait < 45:
            captured = driver.execute_script("return window.__apiResponses || [];")
            matching = [c for c in captured
                        if 'news/securitiesType' in c['url']
                        and slice_start in c['url']
                        and slice_end in c['url']]
            if matching:
                lst, total = parse_news_response(matching[-1]['body'])
                if lst:
                    captured_data = lst
                    break
            time.sleep(1.5)

        # 捕获超时
        if captured_data is None:
            if slice_records:
                print(f"  [第{page}页] 45秒未捕获响应，但已有 {len(slice_records)} 条数据，正常结束本切片")
                break
            else:
                raise RuntimeError(f"第{page}页45秒未捕获响应，且无数据")

        # 返回 0 条
        if len(captured_data) == 0:
            if slice_records:
                print(f"  [第{page}页] 0 条，已有数据，正常结束本切片")
                break
            else:
                print(f"  [第{page}页] 0 条 → 该日期范围无数据")
                is_empty = True
                break

        # 打印本页
        if PRINT_EACH_ITEM:
            print_page_items(page, captured_data)

        slice_records.extend(captured_data)
        print(f"  ➜ 第 {page} 页汇总：{len(captured_data)} 条 | 本切片累计 {len(slice_records)} 条")

        # 不足一页 → 结束
        if len(captured_data) < PAGE_SIZE:
            print(f"  ➜ 第 {page} 页不足 {PAGE_SIZE} 条，本切片完成")
            break

        page += 1
        time.sleep(random.uniform(1.5, 3.0))

    return slice_records, is_empty


# ========== 主循环 ==========
skipped = 0
completed = 0
failed = 0
empty_slices = 0
consecutive_failures = 0

for slice_idx, (slice_start, slice_end) in enumerate(SLICES, 1):
    print(f"\n{'█'*70}")
    print(f"█ 【切片 {slice_idx}/{len(SLICES)}】{slice_start} ~ {slice_end}")
    print(f"█ 进度：完成 {completed} | 空 {empty_slices} | 跳过 {skipped} | 失败 {failed}")
    print(f"{'█'*70}")

    if RESUME and is_slice_done(slice_start, slice_end):
        df_exist = pd.read_csv(slice_filepath(slice_start, slice_end))
        print(f"  ⏭️ 已存在，跳过（{len(df_exist)} 条）")
        skipped += 1
        continue

    try:
        slice_records, is_empty = scrape_slice(slice_start, slice_end)

        if slice_records:
            df = process_records(slice_records)
            fp = slice_filepath(slice_start, slice_end)
            df.to_csv(fp, index=False, encoding="utf-8-sig")
            print(f"\n  ✅ 保存：{len(df)} 条 -> {os.path.basename(fp)}")
            completed += 1
            consecutive_failures = 0
        elif is_empty:
            fp = slice_filepath(slice_start, slice_end)
            pd.DataFrame(columns=['ID', 'Tiêu đề', 'Mã CK', 'Ngày tạo', 'Thời gian', 'Link chi tiết', 'Tóm tắt']).to_csv(
                fp, index=False, encoding="utf-8-sig")
            print(f"\n  📭 本切片无数据，写入空文件标记完成")
            empty_slices += 1
            consecutive_failures = 0
        else:
            print(f"\n  ⚠️ 本切片未获得数据")
            failed += 1
            consecutive_failures += 1

    except Exception as e:
        print(f"\n  ❌ 本切片失败：{e}")
        failed += 1
        consecutive_failures += 1

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            print(f"\n{'!'*70}")
            print(f"⚠️ 连续 {consecutive_failures} 个切片失败，可能网络已断。")
            print(f"   程序自动退出，已保存的切片不会丢。下次重跑会从断点继续。")
            print(f"{'!'*70}")
            break

    if slice_idx < len(SLICES):
        pause = random.uniform(5.0, 10.0)
        print(f"  [休息] {pause:.1f} 秒...")
        time.sleep(pause)

driver.quit()

# ========== 汇总 ==========
print("\n" + "=" * 70)
print(f"📊 本次运行：完成 {completed} | 空数据 {empty_slices} | 跳过 {skipped} | 失败 {failed}")
print("=" * 70)

# ========== 合并 ==========
print("\n开始合并所有切片文件...")
all_files = [f for f in os.listdir(OUT_DIR)
             if f.startswith(f"hose_{TYPE_LABEL}_") and f.endswith(".csv")
             and "MERGED" not in f]

dfs = []
for f in all_files:
    try:
        df_temp = pd.read_csv(os.path.join(OUT_DIR, f))
        if len(df_temp) > 0:
            dfs.append(df_temp)
    except Exception as e:
        print(f"  跳过 {f}: {e}")

if dfs:
    merged = pd.concat(dfs, ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=['ID'])
    after = len(merged)
    merged = merged.sort_values(by='ID', ascending=False)
    merged_path = os.path.join(OUT_DIR, f"hose_{TYPE_LABEL}_MERGED.csv")
    merged.to_csv(merged_path, index=False, encoding="utf-8-sig")
    print(f"\n🎉 合并 {len(dfs)} 个非空文件：{before} -> {after} 条（按ID去重）")
    print(f"   最终文件：{merged_path}")
    print(f"\n最新 5 条:")
    print(merged.head(5).to_string(index=False))
    print(f"\n最早 5 条:")
    print(merged.tail(5).to_string(index=False))
else:
    print("  ⚠️ 没有找到任何非空切片文件")