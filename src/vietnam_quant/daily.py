"""Daily evidence table. Unreported dimensions are never coerced to False.

Snapshots describe what a public source exposed at observation time. They are
not a guarantee that all concurrent legal statuses or intraday changes exist in
that source. In particular, quote boards can show only the highest-priority flag.
"""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import csv
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .http import Client, FetchError, utc_now
from .sources import hnx_status, hose_status, hnx_quote_states, hose_quote_states
from .universe import stock_directory

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MARKETS = ("HOSE", "HNX", "UPCOM")
DIMENSIONS = ("warning", "warning_disclosure", "warning_financial", "warning_other",
              "control", "restriction", "temporary_suspension", "suspension",
              "halt_unspecified", "new_listing", "special_trading_after_inactivity",
              "special_trading_after_long_halt", "compulsory_delisting_reported",
              "voluntary_delisting_reported", "trading_cancelled", "trading_stopped")
CODE_TAGS = {
    "WID": {"warning", "warning_disclosure"},
    "WFR": {"warning", "warning_financial"},
    "WOV": {"warning", "warning_other"}, "CTR": {"control"},
    "RES": {"restriction"}, "C&R": {"control", "restriction"},
    "SUS": {"halt_unspecified"}, "NWE": {"new_listing"},
    # HNX's live legend calls SLS special trading after a halt. Do not
    # translate it as a currently suspended security from the HOSE glossary.
    "SLS": {"special_trading_after_long_halt"},
    "SNE": {"special_trading_after_inactivity"}, "NRM": set(),
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def label_tags(label):
    """Positive evidence only; preserve unrecognized labels for review."""
    text = label.casefold()
    tags = set()
    for phrase, tag in (("cảnh báo", "warning"), ("kiểm soát", "control"),
                        ("hạn chế", "restriction"), ("đình chỉ", "suspension"),
                        ("tạm ngừng", "temporary_suspension"),
                        ("tạm ngưng", "temporary_suspension"),
                        ("tạm dừng", "temporary_suspension"),
                        ("hủy bắt buộc", "compulsory_delisting_reported"),
                        ("hủy tự nguyện", "voluntary_delisting_reported"),
                        ("hủy giao dịch", "trading_cancelled"),
                        ("niêm yết mới", "new_listing")):
        if phrase in text:
            tags.add(tag)
    if "warning" in tags:
        for phrase, tag in (("công bố thông tin", "warning_disclosure"),
                            ("báo cáo tài chính", "warning_financial"), ("khác", "warning_other")):
            if phrase in text:
                tags.add(tag)
    if text.strip() == "ngừng giao dịch":
        tags.add("trading_stopped")
    # A category containing a slash presents alternatives, not proof of both.
    if "tạm ngừng/đình chỉ" in text or "tạm ngưng giao dịch, đình chỉ" in text:
        tags -= {"temporary_suspension", "suspension"}
        tags.add("halt_unspecified")
    return tags


def parse_profile(body, market, symbol, url):
    soup = BeautifulSoup(body, "html.parser")
    code = soup.find("input", id="StockCode")
    board = soup.find("input", id="MarketCode")
    if not code or code.get("value", "").upper() != symbol:
        raise FetchError(f"Wrong or missing profile identity for {market}:{symbol}")
    if not board or board.get("value") != ("NY" if market == "HNX" else "UC"):
        raise FetchError(f"Wrong profile market for {market}:{symbol}")
    fields = {}
    for row in soup.select(".dktimkiem_row"):
        title = row.select_one(".dktimkiem_cell_title")
        value = row.select_one(".dktimkiem_cell_content")
        if title and value:
            fields[title.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    required = ("Trạng thái kiểm soát", "Trạng thái giao dịch")
    if not all(k in fields for k in required):
        raise FetchError(f"Missing direct status fields for {symbol}")
    return {"market": market, "symbol": symbol, "regulatory_label": fields[required[0]] or None,
            "trading_label": fields[required[1]] or None, "source_url": url}


def load_pool(path):
    if path is None:
        return None
    # Explicit market prevents silently matching a reused or transferred code.
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or any(set(("market", "symbol")) - set(r) for r in rows):
        raise ValueError("Pool CSV must contain market,symbol and at least one row")
    pairs = []
    for r in rows:
        pair = (r["market"].strip().upper(), r["symbol"].strip().upper())
        if pair[0] not in MARKETS or not re.fullmatch(r"[A-Z0-9]{2,12}", pair[1]):
            raise ValueError(f"Invalid pool identity: {pair}")
        pairs.append(pair)
    if len(set(pairs)) != len(pairs):
        raise ValueError("Duplicate market,symbol in pool")
    return set(pairs)


def is_fresh(payload, now, max_age=timedelta(hours=2)):
    if not payload or not payload.get("ok"):
        return False
    try:
        stamps = [datetime.fromisoformat(r["fetched_at"]) for r in payload["receipts"]]
        return bool(stamps) and all(t.date() == now.date() and timedelta(0) <= now - t <= max_age
                                   for t in [s.astimezone(VN) for s in stamps])
    except (KeyError, ValueError, TypeError):
        return False


def build_rows(sources, profiles, pool=None, now=None):
    now = now or datetime.now(VN)
    directories, memberships, quotes = {}, defaultdict(list), {}
    fresh = {name: is_fresh(value, now) for name, value in sources.items()}
    for name, payload in sources.items():
        if not fresh[name]:
            continue
        for row in payload["records"]:
            key = (row["market"], row["symbol"])
            if name.startswith("directory-"):
                directories[key] = row
            elif name.startswith("regulatory-"):
                memberships[key].append(row)
            elif name.startswith("quotes-"):
                quotes[key] = row
    # The requested stock universe is the official current directories. Extra
    # source-only codes go to a separate review export (including funds on the
    # HOSE stock board and withdrawn securities retained in regulatory lists).
    keys = pool if pool is not None else set(directories)
    result = []
    for market, symbol in sorted(keys):
        key = (market, symbol)
        profile_payload = profiles.get(f"{market}-{symbol}")
        profile = profile_payload["records"][0] if is_fresh(profile_payload, now) else None
        records, pending, tags, issues = [], [], set(), []
        for row in memberships[key]:
            effective = row.get("effective_at")
            if effective and datetime.fromisoformat(effective).astimezone(VN).date() > now.date():
                pending.append(row)
                continue
            records.append(row)
            found = label_tags(row["status_label"])
            tags |= found
            if not found:
                issues.append("unmapped_regulatory_label")
        q = quotes.get(key)
        admin_normal = False
        if q:
            flags = q["status_label"]
            for field in ("admin_status", "tradingmethod_status", "tradingsantion_status"):
                code = (flags.get(field) or {}).get("code")
                if code:
                    if code not in CODE_TAGS:
                        issues.append(f"unmapped_quote_code:{field}:{code}")
                    else:
                        if market == "HOSE" and code == "SLS":
                            tags.add("halt_unspecified")
                        else:
                            tags |= CODE_TAGS[code]
            admin_normal = (flags.get("admin_status") or {}).get("code") == "NRM"
        profile_normal = profile is not None and (profile["regulatory_label"] or "").casefold() == "bình thường"
        if profile:
            profile_tags = label_tags(profile["regulatory_label"] or "")
            tags |= profile_tags | label_tags(profile["trading_label"] or "")
            if not profile["regulatory_label"] or not profile["trading_label"]:
                issues.append("profile_field_empty")
            if not profile_normal and not profile_tags:
                issues.append("unmapped_profile_label")
        regulatory_tags = tags & {"warning", "control", "restriction"}
        if (profile_normal or admin_normal) and regulatory_tags:
            issues.append("normal_vs_adverse_source_conflict")
        quote_admin_tags = CODE_TAGS.get(((q or {}).get("status_label", {}).get("admin_status") or {}).get("code"), set())
        # A different adverse top-level state is a conflict worth reviewing,
        # unless both are explicitly represented as a combination.
        if profile and quote_admin_tags and label_tags(profile["regulatory_label"] or ""):
            if not (quote_admin_tags & label_tags(profile["regulatory_label"] or "")):
                issues.append("profile_vs_quote_category_conflict")
        if not fresh.get("directory-" + market):
            issues.append("directory_unavailable")
        if not fresh.get("regulatory-" + market):
            issues.append("regulatory_list_unavailable")
        if key not in directories:
            issues.append("not_in_current_directory")
        if not q:
            issues.append("quote_missing")
        if market != "HOSE" and not profile:
            issues.append("profile_missing")
        conflict = any("conflict" in issue for issue in issues)
        observed_flags = {d: True if d in tags else None for d in DIMENSIONS}
        # Keep the raw observations, but never promote contradictory regulatory
        # evidence to a definitive True in the main status columns.
        selected_flags = dict(observed_flags)
        if conflict:
            for dimension in ("warning", "warning_disclosure", "warning_financial", "warning_other", "control", "restriction"):
                selected_flags[dimension] = None
        # No provider has been demonstrated to expose every concurrent flag.
        # Null is intentional; it is not a Boolean False/normal observation.
        row = {"as_of_date": now.date().isoformat(), "source_trading_date": None,
               "market": market, "symbol": symbol,
               "name": directories.get(key, {}).get("name"),
               "pool_membership": "directory" if key in directories else "requested_or_source_only",
               **selected_flags, "observed_flags": observed_flags,
               "normal_reported": bool(profile_normal or admin_normal),
               "regulatory_labels": sorted({r["status_label"] for r in records}),
               "profile_regulatory": profile["regulatory_label"] if profile else None,
               "profile_trading": profile["trading_label"] if profile else None,
               "quote_flags": q["status_label"] if q else None,
               "regulatory_records": records, "pending_records": pending,
               "profile_evidence": profile_payload if profile else None,
               "regulatory_list_complete": fresh.get("regulatory-" + market, False),
               "all_status_dimensions_verified": False,
               "issues": sorted(set(issues)),
               "quality": "conflict" if conflict else
                          "partial" if issues or not (profile or q) else "observed",
               "source_observed_at": {name: [r["fetched_at"] for r in p.get("receipts", [])]
                                       for name, p in sources.items() if name.endswith("-" + market)}}
        result.append(row)
    return result


def run(root, pool_path=None, resume=None, workers=3, import_snapshot=None):
    """Refresh independent sources; resume only same-day, recent validated work."""
    now = datetime.now(VN)
    run_dir = Path(resume) if resume else root / "runs" / now.strftime("%Y%m%dT%H%M%S%f")
    run_dir.mkdir(parents=True, exist_ok=True)
    pool = load_pool(pool_path)
    client = Client(run_dir / "raw")
    hose_client = Client(run_dir / "raw", timeout=120)
    jobs = {}
    for market in MARKETS:
        jobs["directory-" + market] = lambda m=market: stock_directory(hose_client if m == "HOSE" else client, m)
        jobs["regulatory-" + market] = lambda m=market: hose_status(hose_client) if m == "HOSE" else hnx_status(client, m)
        jobs["quotes-" + market] = lambda m=market: hose_quote_states(hose_client) if m == "HOSE" else hnx_quote_states(client, m)
    sources = {}
    # Import only timestamped SQLite snapshots, never loose undated CSVs.
    if import_snapshot:
        import sqlite3
        for kind, filename in (("directory", "stock_directory.sqlite"), ("regulatory", "statuses.sqlite"), ("quotes", "quote_flags.sqlite")):
            path = Path(import_snapshot) / filename
            if not path.exists():
                continue
            db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            try:
                for market in MARKETS:
                    item = db.execute("SELECT id,receipts FROM snapshots WHERE market=? ORDER BY id DESC LIMIT 1", (market,)).fetchone()
                    if item:
                        p = {"ok": True, "records": [json.loads(v[0]) for v in db.execute("SELECT payload FROM records WHERE snapshot_id=?", (item[0],))], "receipts": json.loads(item[1])}
                        if is_fresh(p, now):
                            write_json(run_dir / "sources" / f"{kind}-{market}.json", p)
            finally:
                db.close()
    def fetch_job(name, fn):
        path = run_dir / "sources" / (name + ".json")
        if path.exists():
            old = json.loads(path.read_text())
            if is_fresh(old, datetime.now(VN)):
                return name, old
        try:
            records, receipts = fn()
            value = {"ok": True, "records": records, "receipts": receipts}
        except Exception as exc:
            value = {"ok": False, "records": [], "receipts": [], "error": str(exc), "attempted_at": utc_now()}
        write_json(path, value)
        return name, value
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_job, n, fn) for n, fn in jobs.items()]
        for f in as_completed(futures):
            name, value = f.result(); sources[name] = value
            print(f"{name}: {'OK' if value['ok'] else 'FAILED'} {len(value['records'])}", flush=True)
    # UPCOM does not populate admin_status on the bulk quote feed; fetch the
    # official profile for every stock. HNX gets the same independent check;
    # even a normal quote flag must not suppress a profile's other labels.
    targets = {}
    current_keys = {(row["market"], row["symbol"])
                    for name, source in sources.items() if source["ok"] and name.startswith("directory-")
                    for row in source["records"]}
    selected_keys = pool if pool is not None else current_keys
    for name, source in sources.items():
        if not source["ok"] or not (name.startswith("directory-") or name.startswith("regulatory-")):
            continue
        for row in source["records"]:
            key = (row["market"], row["symbol"])
            if key[0] == "HOSE" or key not in selected_keys:
                continue
            if "chi-tiet-chung-khoan-" in row["source_url"]:
                targets[key] = row["source_url"]
    profiles = {}
    def fetch_profile(item):
        (market, symbol), url = item
        def fetch():
            body, receipt = client.fetch(url)
            return [parse_profile(body, market, symbol, url)], [receipt]
        return fetch_job("profile-" + market + "-" + symbol, fetch)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_profile, item) for item in targets.items()]
        for index, f in enumerate(as_completed(futures), 1):
            name, payload = f.result(); profiles[name.removeprefix("profile-")] = payload
            if index % 25 == 0 or index == len(targets):
                print(f"profiles {index}/{len(targets)}; failures {sum(not p['ok'] for p in profiles.values())}", flush=True)
    return export_run(root, run_dir, pool_path, now.isoformat())


def export_run(root, run_dir, pool_path=None, started_at=None):
    """Rebuild from saved evidence without another network request."""
    now = datetime.now(VN)
    pool = load_pool(pool_path)
    sources, profiles = {}, {}
    for path in (run_dir / "sources").glob("*.json"):
        value = json.loads(path.read_text())
        if path.stem.startswith("profile-"):
            profiles[path.stem.removeprefix("profile-")] = value
        else:
            sources[path.stem] = value
    expected = {f"{kind}-{market}" for kind in ("directory", "regulatory", "quotes") for market in MARKETS}
    source_complete = expected <= set(sources) and all(is_fresh(sources[n], now) for n in expected)
    rows = build_rows(sources, profiles, pool, now)
    all_keys = {(r["market"], r["symbol"]) for p in sources.values() if p["ok"] for r in p["records"]}
    review_keys = all_keys - {(r["market"], r["symbol"]) for r in rows}
    review_rows = build_rows(sources, profiles, review_keys, datetime.now(VN)) if pool is None else []
    write_json(run_dir / "outside_universe_review.json", review_rows)
    manifest = {"started_at": started_at, "completed_at": utc_now(), "run_dir": str(run_dir.resolve()),
                "pool_file": str(Path(pool_path).resolve()) if pool_path else None,
                "pool_definition": "explicit_csv" if pool else "official_current_stock_directories",
                "outside_universe_review_rows": len(review_rows),
                "rows": len(rows), "markets": dict(Counter(r["market"] for r in rows)),
                "quality": dict(Counter(r["quality"] for r in rows)),
                "source_results": {n: {"ok": p["ok"], "rows": len(p["records"]), "error": p.get("error")} for n, p in sources.items()},
                "profile_count": len(profiles), "profile_failures": sum(not p["ok"] for p in profiles.values()),
                "profile_missing_or_stale_in_pool": sum("profile_missing" in r["issues"] for r in rows),
                "missing_sources": sorted(expected - set(sources)),
                "all_status_dimensions_verified": False,
                "semantics": "True=positive observed evidence; null=not established, NEVER normal/False. Conflicting regulatory dimensions are null; observed_flags retains raw positives. normal_reported is a separate raw-source observation.",
                "complete_collection": source_complete and bool(rows) and
                    not any("profile_missing" in r["issues"] for r in rows)}
    write_json(run_dir / "daily_status.json", rows)
    write_json(run_dir / "review_queue.json", [r for r in rows if r["issues"]])
    write_json(run_dir / "manifest.json", manifest)
    fields = ["as_of_date", "source_trading_date", "market", "symbol", "name", "pool_membership", *DIMENSIONS,
              "normal_reported", "observed_flags", "regulatory_labels", "profile_regulatory", "profile_trading",
              "quote_flags", "regulatory_list_complete", "all_status_dimensions_verified", "quality", "issues"]
    with (run_dir / "daily_status.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    # A latest-attempt pointer must not silently replace last successful data.
    write_json(root / "latest_attempt.json", manifest)
    if manifest["complete_collection"]:
        write_json(root / "latest_success.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return manifest["complete_collection"]
