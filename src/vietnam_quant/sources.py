"""Official public lists. Absence from these lists does not imply normal trading."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from hashlib import sha256
import math
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .http import FetchError

HNX_LIST = "https://www.hnx.vn/ModuleReportStockETFs/Report_Stock_ETFs_ListStocks/ListStock_Listed"
UPCOM_LIST = "https://www.hnx.vn/ModuleReportStockETFs/Report_IDX_CanhBaoNDT/NextPageCanhBaoNDT"
HISTORY = {
    "HNX": "https://www.hnx.vn/ModuleReportStockETFs/Report_Stock_ETFs_ListStocks/SearchForTinHDGSTT_Listed",
    "UPCOM": "https://www.hnx.vn/ModuleReportStockETFs/Report_IDX_CanhBaoNDT/SearchForTinHDGSTT_Upcom",
}
HOSE = "https://api.hsx.vn/l/api/v1"


def html_table(body, table_id="_tableDatas"):
    soup = BeautifulSoup(body, "html.parser")
    table = soup.find("table", id=table_id)
    total_tag = soup.find(id="d_total_rec")
    if table is None or total_tag is None:
        raise FetchError("Expected exchange table and pagination metadata are missing")
    total_text = total_tag.get_text(" ", strip=True)
    match = re.search(r"Tổng số\s+(\d+)\s+bản ghi", total_text)
    if match:
        total = int(match.group(1))
    elif "Không tìm thấy dữ liệu" in total_text:
        total = 0
    else:
        raise FetchError(f"Unrecognized record count: {total_text!r}")
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if cells:
            rows.append((tr, [c.get_text(" ", strip=True) for c in cells]))
    return rows, total


def collect_html_pages(client, url, form, page_key, size_key, table_id="_tableDatas", *, cache=False):
    size = int(form[size_key])
    body, receipt = client.fetch(url, {**form, page_key: 1}, cache=cache)
    first, total = html_table(body, table_id)
    rows, receipts = first[:], [receipt]
    expected_first = min(size, total)
    if len(first) != expected_first:
        raise FetchError(f"Page 1: expected {expected_first} rows, got {len(first)}")
    for page in range(2, math.ceil(total / size) + 1):
        body, receipt = client.fetch(url, {**form, page_key: page}, cache=cache)
        part, current_total = html_table(body, table_id)
        expected = min(size, total - (page - 1) * size)
        if current_total != total or len(part) != expected:
            raise FetchError(f"Pagination changed or incomplete on page {page}")
        rows.extend(part)
        receipts.append(receipt)
    # STT must form a complete 1..N sequence, detecting repeated/skipped pages.
    if [int(cells[0]) for _, cells in rows] != list(range(1, total + 1)):
        raise FetchError("Duplicate or missing page sequence")
    return rows, receipts


def hnx_status(client, market):
    if market == "HNX":
        url = HNX_LIST
        form = {"p_keysearch": "", "_type": "5", "_market": "LIS_BRD_01",
                "_view_name": "TableListStockAspecting", "pColOrder": "SYMBOL",
                "pOrderType": "ASC", "pCurrentPage": 1, "pRecordOnPage": 50, "pIsSearch": 0}
        page_key, size_key = "pCurrentPage", "pRecordOnPage"
    else:
        url = UPCOM_LIST
        form = {"pNumPage": 1, "pAction": 0, "pStock": "0", "pStatus": "0",
                "pOrderBy": "SYMBOL ASC", "pNumRecord": 50}
        page_key, size_key = "pNumPage", "pNumRecord"
    rows, receipts = collect_html_pages(client, url, form, page_key, size_key)
    records = []
    for tr, cells in rows:
        if len(cells) != 4 or not cells[1] or not cells[3]:
            raise FetchError("Unrecognized regulatory row")
        anchor = tr.select_one("td:nth-of-type(2) a")
        records.append({"market": market, "symbol": cells[1], "category_id": cells[3],
                        "status_label": cells[3], "name": cells[2], "effective_at": None,
                        "published_at": None, "reason": None,
                        "source_url": urljoin("https://www.hnx.vn", anchor["href"]) if anchor else url})
    return records, receipts


def epoch(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def json_response(body):
    try:
        value = json.loads(body)
    except ValueError as exc:
        raise FetchError("Expected JSON response") from exc
    if value.get("success") is not True:
        raise FetchError(f"Exchange returned failure: {value.get('message')}")
    return value["data"]


def hose_status(client):
    body, receipt = client.fetch(HOSE + "/securities/status-list")
    dictionary = json_response(body)
    if not isinstance(dictionary, list) or not dictionary:
        raise FetchError("Missing HOSE status dictionary")
    receipts, records = [receipt], []
    for category in dictionary:
        page, size, total = 1, 100, None
        seen = set()
        while True:
            url = HOSE + "/1/securities/stock-status?" + urlencode({
                "pageIndex": page, "pageSize": size, "statusListId": category["id"]})
            body, receipt = client.fetch(url)
            payload = json_response(body)
            part = payload["list"]
            reported_total = int(payload["paging"]["totalCount"])
            if total is None:
                total = reported_total
            if total != reported_total or len(part) != min(size, total - (page - 1) * size):
                raise FetchError("HOSE pagination changed or incomplete")
            receipts.append(receipt)
            for row in part:
                # One stock may have several active reasons in the same category.
                identity = sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                if identity in seen:
                    raise FetchError("Duplicate HOSE securities page")
                seen.add(identity)
                records.append({"market": "HOSE", "symbol": row["securitiesCode"],
                                "category_id": str(category["id"]), "status_label": category["name"],
                                "name": row["name"], "effective_at": epoch(row.get("appliedDate")),
                                "published_at": epoch(row.get("datePublish")),
                                "reason": row.get("reason"), "source_url": HOSE + "/1/securities/stock-status?" + urlencode({"statusListId": category["id"]})})
            if page * size >= total:
                break
            page += 1
    return records, receipts


def hnx_history_year(client, market, year, end_date):
    form = {"_pFromDate": f"01/01/{year}", "_pToDate": end_date,
            "pTieuDeTin": "", "pMaChungKhoan": "", "pCurrentPage": 1, "pRecordOnPage": 100}
    rows, receipts = collect_html_pages(client, HISTORY[market], form, "pCurrentPage",
                                        "pRecordOnPage", "_tableDatasArticle", cache=True)
    records = []
    for tr, cells in rows:
        if len(cells) != 5:
            raise FetchError("Unrecognized history row")
        link = tr.select_one("td:nth-of-type(4) a")
        match = re.search(r"funcViewDetailArticlesByID\((\d+),(\d+)\)", link.get("onclick", "")) if link else None
        if match is None:
            raise FetchError("Missing article identifier")
        published = datetime.strptime(cells[1], "%d/%m/%Y %H:%M").isoformat()
        records.append({"market": market, "article_id": match.group(1), "symbol": cells[2],
                        "published_local": published, "timezone": "Asia/Ho_Chi_Minh", "title": cells[3],
                        "has_attachment": match.group(2) != "0", "effective_at": None,
                        "source_endpoint": HISTORY[market]})
    if len({r["article_id"] for r in records}) != len(records):
        raise FetchError("Duplicate article identifiers")
    return records, receipts


def hnx_quote_states(client, market):
    """Supplementary trading flags; some suspended stocks are absent from this feed."""
    url = "https://banggia.hnx.vn/Home/GetByAreas"
    board = "LIS" if market == "HNX" else "UPC"
    groups = ("ABC", "DEF", "GHI", "JKL", "MNO", "PQR", "STUV", "WXYZ")
    fields = {"listing_status", "admin_status", "tradingmethod_status", "tradingsantion_status", "status"}
    def group_read(group):
        body, receipt = client.fetch(url, {"pKey": group, "pBoard": board})
        value = json.loads(body)
        if value.get("success") != 1 or not isinstance(value.get("obj"), list):
            raise FetchError("Unrecognized price-board response")
        rows = []
        for raw in value["obj"]:
            parts = raw.split("|")
            if len(parts) < 3 or not parts[1]:
                raise FetchError("Unrecognized stock quote")
            symbol, flags = parts[1], {}
            for part in parts[2:]:
                values = part.split("*")
                if len(values) >= 2 and values[0].startswith(symbol + "_"):
                    key = values[0][len(symbol) + 1:]
                    if key in fields:
                        flags[key] = {"display": values[1], "code": values[3] if len(values) >= 4 else None}
            if "status" not in flags or "admin_status" not in flags:
                raise FetchError(f"Missing trading flags for {symbol}")
            rows.append({"market": market, "symbol": symbol, "category_id": "quote_flags",
                         "status_label": flags, "source_url": url})
        return rows, receipt
    records, receipts = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for rows, receipt in pool.map(group_read, groups):
            records.extend(rows)
            receipts.append(receipt)
    if len({r["symbol"] for r in records}) != len(records):
        raise FetchError("Duplicate stock across alphabet groups")
    return records, receipts


def parse_hose_quote_states(body):
    """The public rtboard.hsx.vn frontend's stock (type 1) snapshot."""
    data = json_response(body)
    if not isinstance(data, list) or not data:
        raise FetchError("Missing HOSE stock board")
    records = []
    for row in data:
        symbol = row.get("securitySymbol")
        if not symbol or row.get("code") != symbol or "warning_status" not in row:
            raise FetchError("Unexpected HOSE stock board identity/status schema")
        records.append({"market": "HOSE", "symbol": symbol, "name": row.get("name"),
                        "category_id": "quote_flags",
                        "status_label": {"admin_status": {"code": row["warning_status"], "display": row["warning_status"]}},
                        "source_url": HOSE + "/securities/load-securities-matching/1"})
    if len({r["symbol"] for r in records}) != len(records):
        raise FetchError("Duplicate HOSE board stock")
    return records


def hose_quote_states(client):
    body, receipt = client.fetch_large_get(HOSE + "/securities/load-securities-matching/1")
    return parse_hose_quote_states(body), [receipt]
