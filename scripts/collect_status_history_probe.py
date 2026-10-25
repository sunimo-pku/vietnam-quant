"""Enumerate public structured status/listing events, partitioned by channel.

The provider uses channelID for regulatory categories; catID is a different
filter. A complete page set proves endpoint enumeration, not complete history.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
from bs4 import BeautifulSoup
from vietnam_quant.http import Client
from scripts.probe_status_sources import OUT


CHANNELS = [17, 18, 19, 20, 22, 50, 51, 52, 53, 54, 56]


def main():
    dest = OUT / "vietstock-channel-history"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cookie = tmp + "/anonymous.cookies"
        client = Client(dest / "raw", ["--cookie-jar", cookie])
        page_url = "https://finance.vietstock.vn/lich-su-kien.htm?tab=2&languageid=2"
        html, _ = client.fetch(page_url)
        token = BeautifulSoup(html, "html.parser").select_one("input[name=__RequestVerificationToken]")["value"]
        client.extra_args = ["--compressed", "--cookie", cookie, "-H", "X-Requested-With: XMLHttpRequest", "-H", "Referer: " + page_url]

        def channel(channel_id):
            saved = dest / f"channel-{channel_id}.json"
            if saved.exists():
                previous = json.loads(saved.read_text())
                if previous.get("complete_for_endpoint_query"):
                    print(f"Reuse verified channel {channel_id}: {previous['rows']} rows", flush=True)
                    return previous
            records, receipts, expected_total, page = [], [], None, 1
            try:
                while True:
                    form = {"eventTypeID": 2, "channelID": channel_id, "catID": -1, "code": "",
                            "fDate": "2000-01-01", "tDate": "2026-10-23", "page": page,
                            "pageSize": 100, "orderBy": "Date1", "orderDir": "ASC",
                            "__RequestVerificationToken": token}
                    body, receipt = client.fetch("https://finance.vietstock.vn/data/eventstypedata", form, cache=True)
                    receipts.append(receipt)
                    if not body.strip():
                        raise ValueError("Empty response: coverage unknown")
                    value = json.loads(body)
                    part, total = value[0], int(value[1][0])
                    if expected_total is None:
                        expected_total = total
                    if total != expected_total or len(part) != min(100, total - (page - 1) * 100):
                        raise ValueError("Changed total or incomplete pagination")
                    if any(r["ChannelID"] != channel_id for r in part):
                        raise ValueError("Channel filter ignored")
                    records.extend(part)
                    if page * 100 >= total:
                        break
                    page += 1
                if len({r["EventID"] for r in records}) != expected_total:
                    raise ValueError("Duplicate/missing IDs")
                result = {"channel_id": channel_id, "query_start": "2000-01-01", "query_end": "2026-10-23",
                          "complete_for_endpoint_query": True, "rows": len(records), "reported_total": total,
                          "receipts": receipts, "records": records}
            except Exception as exc:
                result = {"channel_id": channel_id, "complete_for_endpoint_query": False,
                          "error": str(exc), "rows": len(records), "receipts": receipts, "records": records}
            (dest / f"channel-{channel_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({k: v for k, v in result.items() if k not in ("records", "receipts")}), flush=True)
            return result

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(channel, CHANNELS))
        events = [r for group in results for r in group["records"]]
        (dest / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2))
        (dest / "manifest.json").write_text(json.dumps([{k: v for k, v in group.items() if k != "records"}
                                                        for group in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
