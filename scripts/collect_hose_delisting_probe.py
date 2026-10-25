"""Download HOSE's structured, year-filtered delisting register.

This register includes bonds and warrants. Rows without a verified instrument
type must not be silently classified as stocks.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from urllib.parse import urlencode
from vietnam_quant.http import Client
from scripts.probe_status_sources import OUT


def main():
    dest = OUT / "hose-delisting-history"
    dest.mkdir(parents=True, exist_ok=True)
    client = Client(dest / "raw", ["--compressed"])

    def year_query(year):
        rows, receipts, page, total = [], [], 1, None
        try:
            while True:
                url = "https://api.hsx.vn/l/api/v1/1/securities/cancel?" + urlencode(
                    {"pageIndex": page, "pageSize": 50, "year": year})
                body, receipt = client.fetch(url, cache=True)
                receipts.append(receipt)
                obj = json.loads(body)
                if obj.get("success") is not True:
                    raise ValueError("API failure")
                data = obj["data"]
                current_total = data["paging"]["totalCount"]
                total = current_total if total is None else total
                if current_total != total or len(data["list"]) != min(50, total - (page - 1) * 50):
                    raise ValueError("Changed total or incomplete pagination")
                rows += data["list"]
                if page * 50 >= total:
                    break
                page += 1
            if len({r["id"] for r in rows}) != total:
                raise ValueError("Duplicate or missing IDs")
            result = {"year": year, "complete_for_endpoint_query": True, "reported_total": total,
                      "rows": len(rows), "records": rows, "receipts": receipts}
        except Exception as exc:
            result = {"year": year, "complete_for_endpoint_query": False, "error": str(exc),
                      "rows": len(rows), "records": rows, "receipts": receipts}
        (dest / f"{year}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k not in ("records", "receipts")}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(year_query, range(2000, 2027)))
    (dest / "events.json").write_text(json.dumps([r for y in results for r in y["records"]], ensure_ascii=False, indent=2))
    (dest / "manifest.json").write_text(json.dumps([{k: v for k, v in y.items() if k != "records"}
                                                    for y in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
