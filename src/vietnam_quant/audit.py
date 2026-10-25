"""Coverage evidence and convenient exports, without inventing daily states."""
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .http import utc_now

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def provider_date(value):
    if value is None or value == "":
        return None
    match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", value)
    if not match:
        raise ValueError(f"Unrecognized provider date {value!r}")
    return datetime.fromtimestamp(int(match[1]) / 1000, timezone.utc).astimezone(VN_TZ).date().isoformat()


def csv_export(path, records, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(records)


def run(root):
    calendar_dir = root / "vietstock"
    rows = json.loads((calendar_dir / "events.json").read_text())
    manifest = json.loads((calendar_dir / "manifest.json").read_text())
    regulatory = {19, 20, 22, 50, 51, 52, 53, 54, 56}
    normalized, quality = [], []
    categories = defaultdict(list)
    for row in rows:
        event_date, query_date = provider_date(row.get("Time")), provider_date(row.get("DateOrder"))
        flags = []
        if row["Exchange"] == "UPCoM" and event_date and event_date < "2009-06-24":
            flags.append("provider_venue_predates_market_launch")
        if row["ChannelID"] == 19 and "kiểm soát" in (row.get("Title") or "").lower():
            flags.append("alert_category_title_mentions_control")
        if event_date and event_date > manifest["query_end"]:
            flags.append("event_date_after_query_end")
        if not event_date:
            flags.append("missing_event_date")
        if flags:
            quality.append({"event_id": row["EventID"], "symbol": row["Code"], "flags": flags})
        output = {"event_id": row["EventID"], "symbol": row["Code"], "provider_exchange": row["Exchange"],
                  "provider_category_id": row["ChannelID"], "provider_category": row["Name"],
                  "event_date_local": event_date, "query_date_local": query_date,
                  "provider_date_hcb": provider_date(row.get("DateHCB")),
                  "provider_date_gdtl": provider_date(row.get("DateGDTL")),
                  "provider_date_nytl": provider_date(row.get("DateNYTL")),
                  "provider_date_ctgd": provider_date(row.get("DateCTGD")),
                  "note": row.get("Note"), "reason": row.get("ReasonCBKS") or row.get("Reason"),
                  "title": row.get("Title"), "attachment_url": row.get("FileUrl"),
                  "quality_flags": ";".join(flags)}
        normalized.append(output)
        if event_date:
            categories[(row["ChannelID"], row["Name"])].append(event_date)
    normalized.sort(key=lambda r: (r["query_date_local"] or "", r["event_id"]))
    fields = list(normalized[0]) if normalized else ["event_id", "symbol"]
    csv_export(calendar_dir / "events.csv", normalized, fields)
    csv_export(calendar_dir / "regulatory_events.csv", [r for r in normalized if r["provider_category_id"] in regulatory], fields)
    current_rows = list(csv.DictReader((root / "current_statuses.csv").open(encoding="utf-8-sig")))
    quote_rows = json.loads((root / "current_quote_flags.json").read_text()) if (root / "current_quote_flags.json").exists() else []
    directory_path = root / "current_stock_directory.json"
    directory_rows = json.loads(directory_path.read_text()) if directory_path.exists() else []
    current = {}
    for market in ("HOSE", "HNX", "UPCOM"):
        part = [r for r in current_rows if r["market"] == market]
        codes = {r["symbol"] for r in part}
        quoted = {r["symbol"] for r in quote_rows if r["market"] == market}
        directory = {r["symbol"] for r in directory_rows if r["market"] == market}
        current[market] = {"regulatory_records": len(part), "regulatory_symbols": len(codes),
                           "quote_symbols": len(quoted), "regulatory_symbols_absent_from_quotes": sorted(codes - quoted) if market != "HOSE" else None,
                           "observed_at": max((r["observed_at"] for r in part), default=None)}
        if directory_rows:
            current[market].update({"directory_symbols": len(directory),
                                   "regulatory_symbols_absent_from_directory": sorted(codes - directory)})
    history_manifest = json.loads((root / "history_manifest.json").read_text())
    historical_rows = list(csv.DictReader((root / "historical_announcements.csv").open(encoding="utf-8-sig")))
    histories = {}
    for market in ("HNX", "UPCOM"):
        part = [r for r in historical_rows if r["market"] == market]
        histories[market] = {"records": len(part), "first_publication": min((r["published_local"] for r in part), default=None),
                             "last_publication": max((r["published_local"] for r in part), default=None)}
    live_checks = {}
    for db_name in ("statuses.sqlite", "quote_flags.sqlite", "stock_directory.sqlite"):
        if not (root / db_name).exists():
            continue
        with sqlite3.connect(root / db_name) as db:
            live_checks[db_name] = {"snapshots": db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                                    "changes": db.execute("SELECT COUNT(*) FROM changes").fetchone()[0],
                                    "failures": db.execute("SELECT COUNT(*) FROM failures").fetchone()[0]}
    report = {"generated_at": utc_now(), "calendar_events": len(rows),
              "regulatory_calendar_events": sum(r["ChannelID"] in regulatory for r in rows),
              "calendar_categories": [{"id": key[0], "name": key[1], "records": sum(r["ChannelID"] == key[0] for r in rows),
                                       "first_event_date": min(dates), "last_event_date": max(dates)} for key, dates in sorted(categories.items())],
              "calendar_empty_or_failed_windows": manifest["failures"],
              "calendar_cross_window_duplicates": manifest["duplicate_event_ids_across_windows"],
              "quality_flags": dict(Counter(flag for r in quality for flag in r["flags"])),
              "historical_announcements": histories, "historical_archive_page_checks_passed": history_manifest["complete_for_endpoint_queries"],
              "current_lists": current, "live_checks": live_checks,
              "daily_status_since_2000_complete": False,
              "limitation": "No assumption of normal status from missing history or absence from a regulatory list. Public-source upstream delay is unmeasured."}
    legacy_path = root / "ssc" / "articles.json"
    if legacy_path.exists():
        legacy = json.loads(legacy_path.read_text())
        published = [r["published_local"] for r in legacy if r.get("published_local")]
        report["legacy_archive"] = {"articles": len(legacy), "first_page_date": min(published, default=None),
                                    "last_page_date": max(published, default=None),
                                    "body_dates_requiring_semantic_review": sum(r["needs_date_review"] for r in legacy),
                                    "complete_since_2000": False}
    verified_path = root / "ssc_verified_events.json"
    if verified_path.exists():
        verified = json.loads(verified_path.read_text())
        report["manually_verified_legacy_events"] = len(verified)
        fields = sorted({key for row in verified for key in row})
        csv_export(root / "ssc_verified_events.csv", verified, fields)
    (root / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (calendar_dir / "quality_flags.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ["calendar_events", "regulatory_calendar_events", "quality_flags", "live_checks"]}, ensure_ascii=False, indent=2))
    return report
