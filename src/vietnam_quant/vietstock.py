"""Anonymous calendar reads, preserving all original fields and time semantics.

Provider venue labels are not assumed to be the historical trading venue.
Calendar events are not a complete daily status panel.
"""
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
import tempfile

from bs4 import BeautifulSoup

from .http import Client, FetchError, utc_now

BASE = "https://finance.vietstock.vn"
PAGE = BASE + "/lich-su-kien.htm?tab=2&languageid=2"
PAGE_SIZE = 500  # Public endpoint caps larger requested sizes at 500.


def download(root, start, end, *, refresh=False):
    output = root / "vietstock"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vn-calendar-") as temp:
        cookie_path = str(Path(temp) / "anonymous.cookies")
        client = Client(root / "raw" / "vietstock", ["--cookie-jar", cookie_path], refresh=refresh)
        body, _ = client.fetch(PAGE)
        token = BeautifulSoup(body, "html.parser").select_one("input[name=__RequestVerificationToken]")
        if token is None:
            raise FetchError("Missing public calendar anti-forgery token")
        client.extra_args = ["--cookie", cookie_path, "-H", "X-Requested-With: XMLHttpRequest",
                             "-H", "Accept: application/json, text/javascript, */*; q=0.01",
                             "-H", "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
                             "-H", "Referer: " + PAGE]
        body, _ = client.fetch(BASE + "/data/eventtypebyid", {"id": 2}, cache=True)
        categories = json.loads(body)[1]
        (output / "categories.json").write_text(json.dumps(categories, ensure_ascii=False, indent=2))
        tasks = []
        for year in range(start, end.year + 1):
            for month in range(1, 13):
                first = date(year, month, 1)
                if first <= end:
                    tasks.append((first, min(date(year, month, monthrange(year, month)[1]), end)))

        def partition(bounds):
            first, last = bounds
            rows, receipts, page, total = [], [], 1, None
            while True:
                form = {"eventTypeID": 2, "channelID": 0, "code": "", "catID": -1,
                        "fDate": first.isoformat(), "tDate": last.isoformat(), "page": page,
                        "pageSize": PAGE_SIZE, "orderBy": "Date1", "orderDir": "ASC",
                        "__RequestVerificationToken": token["value"]}
                body, receipt = client.fetch(BASE + "/data/eventstypedata", form, cache=True)
                if not body.strip():
                    raise FetchError("HTTP 200 with empty body: no event total provided; treat as unknown coverage")
                value = json.loads(body)
                if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], list):
                    raise FetchError("Unrecognized calendar response")
                part, reported_total = value[0], int(value[1][0])
                if total is None:
                    total = reported_total
                if total != reported_total or len(part) != min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE):
                    raise FetchError(f"Calendar changed or incomplete on page {page}")
                rows.extend(part)
                receipts.append(receipt)
                if page * PAGE_SIZE >= total:
                    break
                page += 1
            if len({r["EventID"] for r in rows}) != total:
                raise FetchError("Duplicate or missing calendar events")
            metadata = {"from": first.isoformat(), "to": last.isoformat(), "rows": total,
                        "complete_for_endpoint_query": True, "receipts": receipts}
            (output / f"{first:%Y-%m}.json").write_text(json.dumps({"manifest": metadata, "records": rows}, ensure_ascii=False, indent=2))
            return rows, metadata

        all_rows, partitions, failures = [], [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(partition, bounds): bounds for bounds in tasks}
            for f in as_completed(futures):
                first, last = futures[f]
                try:
                    rows, metadata = f.result()
                    all_rows.extend(rows)
                    partitions.append(metadata)
                    if rows or first.month == 12:
                        print(f"Vietstock {first:%Y-%m}: {len(rows)} events", flush=True)
                except Exception as exc:
                    failures.append({"from": first.isoformat(), "to": last.isoformat(), "error": str(exc)})
                    print(f"Vietstock {first:%Y-%m}: FAILED {exc}", flush=True)
        unique, duplicates, conflicts = {}, [], []
        for row in all_rows:
            if row["EventID"] in unique:
                duplicates.append(row["EventID"])
                # Delisting events can match both last-trade and re-listing dates,
                # so identical events may legitimately appear in different months.
                old = {k: v for k, v in unique[row["EventID"]].items() if k != "Row"}
                new = {k: v for k, v in row.items() if k != "Row"}
                if old != new:
                    conflicts.append(row["EventID"])
            else:
                unique[row["EventID"]] = row
        all_rows = sorted(unique.values(), key=lambda r: r["EventID"])
        (output / "events.json").write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))
        manifest = {"generated_at": utc_now(), "query_start_year": start, "query_end": end.isoformat(),
                    "rows": len(all_rows), "partitions": sorted(partitions, key=lambda p: p["from"]),
                    "failures": failures, "duplicate_event_ids_across_windows": duplicates,
                    "conflicting_event_ids_across_windows": conflicts,
                    "complete_for_endpoint_queries": not failures and not conflicts,
                    "scope": "Provider calendar events; no guarantee of complete historical daily status"}
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest["complete_for_endpoint_queries"]
