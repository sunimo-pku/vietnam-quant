import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date
import json
from pathlib import Path
import sys
import time

from .http import Client, utc_now
from .sources import hnx_status, hose_status, hnx_history_year, hnx_quote_states
from .store import Store


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def snapshot(root, quotes=False, universe=False):
    client = Client(root / "raw" / "current")
    store = Store(root / "statuses.sqlite")
    ok = True
    try:
        for market in ("HOSE", "HNX", "UPCOM"):
            try:
                records, receipts = hose_status(client) if market == "HOSE" else hnx_status(client, market)
                print(json.dumps(store.save(market, records, receipts), ensure_ascii=False), flush=True)
            except Exception as exc:
                ok = False
                store.failure(market, exc)
                print(json.dumps({"market": market, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        rows = store.latest()
        write_csv(root / "current_statuses.csv", rows, ["market", "symbol", "category_id", "status_label", "name",
                                                      "effective_at", "published_at", "reason", "source_url", "observed_at"])
    finally:
        store.db.close()
    if quotes:
        quote_store = Store(root / "quote_flags.sqlite")
        try:
            for market in ("HNX", "UPCOM"):
                try:
                    records, receipts = hnx_quote_states(client, market)
                    result = quote_store.save(market, records, receipts)
                    print(json.dumps({"source": "supplementary_quote_flags", **result}), flush=True)
                except Exception as exc:
                    ok = False
                    quote_store.failure(market, exc)
                    print(json.dumps({"source": "supplementary_quote_flags", "market": market, "error": str(exc)}), file=sys.stderr, flush=True)
            (root / "current_quote_flags.json").write_text(json.dumps(quote_store.latest(), ensure_ascii=False, indent=2))
        finally:
            quote_store.db.close()
    if universe:
        from .universe import stock_directory
        directory_store = Store(root / "stock_directory.sqlite")
        try:
            for market in ("HOSE", "HNX", "UPCOM"):
                try:
                    records, receipts = stock_directory(client, market)
                    result = directory_store.save(market, records, receipts)
                    print(json.dumps({"source": "stock_directory", **result}), flush=True)
                except Exception as exc:
                    ok = False
                    directory_store.failure(market, exc)
                    print(json.dumps({"source": "stock_directory", "market": market, "error": str(exc)}), file=sys.stderr, flush=True)
            (root / "current_stock_directory.json").write_text(json.dumps(directory_store.latest(), ensure_ascii=False, indent=2))
        finally:
            directory_store.db.close()
    return ok


def history(root, start, end, refresh=False):
    client = Client(root / "raw" / "history", refresh=refresh)
    partitions = root / "history_partitions"
    partitions.mkdir(parents=True, exist_ok=True)
    all_rows, manifests, failures = [], [], []
    tasks = [(m, y) for m in ("HNX", "UPCOM") for y in range(start, end.year + 1)]
    def run(task):
        market, year = task
        last = end.strftime("%d/%m/%Y") if year == end.year else f"31/12/{year}"
        rows, receipts = hnx_history_year(client, market, year, last)
        part = {"market": market, "year": year, "complete_for_endpoint_query": True,
                "rows": len(rows), "receipts": receipts}
        (partitions / f"{market}-{year}.json").write_text(json.dumps({"manifest": part, "records": rows}, ensure_ascii=False, indent=2))
        return rows, part
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run, task): task for task in tasks}
        for f in as_completed(futures):
            market, year = futures[f]
            try:
                rows, part = f.result()
                all_rows.extend(rows)
                manifests.append(part)
                print(f"{market} {year}: {len(rows)} historical records", flush=True)
            except Exception as exc:
                failures.append({"market": market, "year": year, "error": str(exc)})
                print(f"{market} {year}: FAILED {exc}", file=sys.stderr, flush=True)
    all_rows.sort(key=lambda r: (r["market"], r["published_local"], r["article_id"]))
    fields = ["market", "article_id", "symbol", "published_local", "timezone", "title",
              "has_attachment", "effective_at", "source_endpoint"]
    write_csv(root / "historical_announcements.csv", all_rows, fields)
    manifest = {"generated_at": utc_now(), "query_start_year": start, "query_end": end.isoformat(),
                "rows": len(all_rows), "partitions": sorted(manifests, key=lambda x: (x["market"], x["year"])),
                "failures": failures, "scope": "Public market-supervision announcement archive; not daily historical status",
                "complete_for_endpoint_queries": not failures}
    (root / "history_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return not failures


def main():
    parser = argparse.ArgumentParser(description="Vietnam stock status updates and source research")
    parser.add_argument("--output", type=Path, help="Output directory; update defaults to configured current-status output")
    sub = parser.add_subparsers(dest="command", required=True)
    current = sub.add_parser("current-report", help="Replay SSI/DNSE responses into five original status fields (offline)")
    current.add_argument("--from-run", type=Path, required=True, help="Saved probe_anonymous_status.py run directory")
    update_parser = sub.add_parser("update", help="Update all current stocks from public SSI/DNSE sources")
    update_parser.add_argument("--config", type=Path, help="JSON settings; defaults to config/settings.json if present")
    daily = sub.add_parser("daily", help="Collect a per-stock current multi-dimensional evidence table")
    daily.add_argument("--pool", type=Path, help="CSV with market,symbol; default is current exchange sources")
    daily.add_argument("--resume", type=Path, help="Resume a run; reuse only same-day responses less than 2 hours old")
    daily.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    daily.add_argument("--import-snapshot", type=Path, help="Reuse recent validated SQLite snapshots; fetch missing sources")
    daily_report = sub.add_parser("daily-report", help="Rebuild the current evidence report from a saved run")
    daily_report.add_argument("--run", type=Path, required=True)
    daily_report.add_argument("--pool", type=Path)
    once = sub.add_parser("snapshot", help="Fetch all three public regulatory lists once")
    once.add_argument("--quotes", action="store_true", help="Also collect HNX/UPCOM supplementary trading flags")
    once.add_argument("--universe", action="store_true", help="Also collect all three current exchange stock directories")
    watch = sub.add_parser("watch", help="Poll lists; retain prior data on failures")
    watch.add_argument("--interval", type=float, default=300, help="Seconds between completed cycles")
    watch.add_argument("--cycles", type=int, default=0, help="0 runs until Ctrl-C")
    watch.add_argument("--quotes", action="store_true", help="Also poll supplementary trading flags")
    watch.add_argument("--universe", action="store_true", help="Also poll exchange stock directories")
    hist = sub.add_parser("history", help="Download date-filtered HNX and UPCOM supervision archives")
    hist.add_argument("--start-year", type=int, default=2000)
    hist.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    hist.add_argument("--refresh", action="store_true", help="Refetch historical pages instead of using saved responses")
    calendar = sub.add_parser("calendar", help="Download historical Vietstock listing and regulatory events")
    calendar.add_argument("--start-year", type=int, default=2000)
    calendar.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    calendar.add_argument("--refresh", action="store_true", help="Refetch historical pages instead of using saved responses")
    archive = sub.add_parser("archive", help="Download SSC legacy articles from keyword search or exported paginated index")
    archive.add_argument("--query", action="append", default=[], help="Search keyword; first page only, completeness reported")
    archive.add_argument("--index", action="append", type=Path, default=[], help="JSON containing reported_total and pages[].links[]")
    sub.add_parser("audit", help="Export collected calendar CSVs and report coverage limits")
    args = parser.parse_args()
    if args.command == "update":
        from .current.config import load_settings
        from .current.live import update
        from .current.storage import AlreadyRunning
        try:
            config = args.config
            if config is None and Path("config/settings.json").exists():
                config = Path("config/settings.json")
            settings = load_settings(config)
            _, manifest = update(settings, args.output)
            return 0 if manifest["status"] == "success" else 1
        except (OSError, ValueError, AlreadyRunning) as exc:
            print(f"无法开始更新：{exc}", file=sys.stderr)
            return 1
    args.output = args.output or Path("outputs/status-data")
    if args.command == "current-report":
        from .current.contract import SourceError
        from .current.pipeline import export_saved_run
        try:
            run_dir, manifest = export_saved_run(args.from_run, args.output)
        except (SourceError, OSError, ValueError) as exc:
            print(f"current-report: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"run_dir": str(run_dir), **manifest}, ensure_ascii=False, indent=2))
        return 0 if manifest["schema_checks_passed"] else 1
    if args.command == "daily":
        from .daily import run
        return 0 if run(args.output, args.pool, args.resume, args.workers, args.import_snapshot) else 1
    if args.command == "daily-report":
        from .daily import export_run
        return 0 if export_run(args.output, args.run, args.pool) else 1
    if args.command == "archive":
        from .ssc import download
        if not args.query and not args.index:
            parser.error("archive requires --query or --index")
        return 0 if download(args.output, args.query, args.index) else 1
    if args.command == "audit":
        from .audit import run
        run(args.output)
        return 0
    if args.command in ("history", "calendar"):
        if args.start_year < 2000 or args.start_year > args.end_date.year:
            parser.error("start-year must be between 2000 and end-date year")
        if args.command == "calendar":
            from .vietstock import download
            return 0 if download(args.output, args.start_year, args.end_date, refresh=args.refresh) else 1
        return 0 if history(args.output, args.start_year, args.end_date, refresh=args.refresh) else 1
    if args.command == "snapshot":
        return 0 if snapshot(args.output, args.quotes, args.universe) else 1
    if args.interval < 1 or args.cycles < 0:
        parser.error("interval must be >=1 and cycles >=0")
    cycle, ok = 0, True
    try:
        while args.cycles == 0 or cycle < args.cycles:
            ok = snapshot(args.output, args.quotes, args.universe)
            cycle += 1
            if args.cycles == 0 or cycle < args.cycles:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
