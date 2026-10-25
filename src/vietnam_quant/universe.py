"""Current exchange stock directories, kept separate from regulatory labels."""
import json
from concurrent.futures import ThreadPoolExecutor
import math
from urllib.parse import urlencode, urljoin

from .http import FetchError
from .sources import HOSE, collect_html_pages, json_response


def stock_directory(client, market, *, hose_page_size=20, hose_workers=3):
    if market == "HOSE":
        records, receipts, seen = [], [], set()
        # Large responses are often truncated by this public host. Smaller
        # pages retain the same reported total and explicit uniqueness checks.
        size = hose_page_size
        def fetch_page(page):
            url = HOSE + "/1/securities/stock?" + urlencode({"pageIndex": page, "pageSize": size})
            body, receipt = client.fetch(url)
            return page, json_response(body), receipt
        first_page, first, first_receipt = fetch_page(1)
        total = int(first["paging"]["totalCount"])
        if hose_workers == 1:
            rest = [fetch_page(page) for page in range(2, math.ceil(total / size) + 1)]
        else:
            with ThreadPoolExecutor(max_workers=hose_workers) as pool:
                rest = list(pool.map(fetch_page, range(2, math.ceil(total / size) + 1)))
        for page, payload, receipt in [(first_page, first, first_receipt), *rest]:
            current_total = int(payload["paging"]["totalCount"])
            part = payload["list"]
            if total != current_total or len(part) != min(size, total - (page - 1) * size):
                raise FetchError("HOSE stock directory pagination changed or incomplete")
            receipts.append(receipt)
            for row in part:
                symbol = row["code"]
                if not symbol or symbol in seen:
                    raise FetchError("Missing or duplicate HOSE directory symbol")
                seen.add(symbol)
                records.append({"market": market, "symbol": symbol, "name": row["name"],
                                "category_id": "stock_directory", "status_label": "present_in_stock_directory",
                                "provider_profile": row, "source_url": HOSE + "/1/securities/stock"})
        if not records:
            raise FetchError("Empty HOSE current stock directory requires review")
        return records, receipts
    path = "List" if market == "HNX" else "UC_Issuer"
    url = "https://www.hnx.vn/ModuleIssuer/" + path + "/ListSearch_Datas"
    form = {"p_issearch": 0, "p_keysearch": "", "p_market_code": "" if market == "HNX" else "UC",
            "p_orderby": "STOCK_CODE", "p_ordertype": "ASC", "p_currentpage": 1, "p_record_on_page": 100}

    class TableResponse:
        def fetch(self, *args, **kwargs):
            body, receipt = client.fetch(*args, **kwargs)
            try:
                value = json.loads(body)
                content = value["Content"]
            except (ValueError, KeyError, TypeError) as exc:
                raise FetchError("HNX directory response has no expected HTML table") from exc
            return content, receipt

    rows, receipts = collect_html_pages(TableResponse(), url, form, "p_currentpage", "p_record_on_page")
    records = []
    for tr, cells in rows:
        expected = 7 if market == "HNX" else 6
        if len(cells) != expected or not cells[1]:
            raise FetchError("Unrecognized HNX stock directory row")
        link = tr.select_one("td:nth-of-type(2) a")
        records.append({"market": market, "symbol": cells[1], "name": cells[2],
                        "category_id": "stock_directory", "status_label": "present_in_stock_directory",
                        "provider_profile": {"raw_cells": cells[3:]},
                        "source_url": urljoin("https://www.hnx.vn", link["href"]) if link else url})
    if len({r["symbol"] for r in records}) != len(records):
        raise FetchError("Duplicate HNX directory symbol")
    return records, receipts
