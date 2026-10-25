"""Summarize source evidence without manufacturing a complete daily panel."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import html
import json
import re
from vietnam_quant.audit import provider_date, csv_export
from scripts.probe_status_sources import OUT, ROOT


REGULATORY = {19, 20, 22, 50, 51, 52, 53, 54, 56}


def read(path):
    return json.loads(path.read_text())


def main():
    exports = OUT / "exports"
    exports.mkdir(exist_ok=True)
    master_payload = read(OUT / "vndirect-exchange-master/body")
    master = master_payload["data"]
    assert len(master) == master_payload["totalElements"] == len({r["code"] for r in master})
    assert all(r["type"] == "STOCK" and r["floor"] in {"HOSE", "HNX", "UPCOM"} for r in master)
    codes = {r["code"] for r in master}
    master_rows = []
    for r in master:
        flags = []
        if r.get("listedDate") and r.get("delistedDate") and r["listedDate"] > r["delistedDate"]:
            flags.append("listing_after_delisting_requires_venue_history")
        if r["status"] == "listed" and r.get("delistedDate"):
            flags.append("currently_listed_with_prior_delisting")
        master_rows.append({**{k: r.get(k) for k in ("code", "floor", "status", "companyName", "companyId",
                                                     "isin", "listedDate", "delistedDate")},
                            "quality_flags": ";".join(flags)})
    csv_export(exports / "stock_master.csv", master_rows, list(master_rows[0]))

    baseline = read(ROOT / "outputs/status-data/vietstock/events.json")
    merged = {r["EventID"]: r for r in baseline}
    changed_ids = set()
    added_ids = set()
    channel_manifest = read(OUT / "vietstock-channel-history/manifest.json")
    patches = [(f"channel-{c['channel_id']}", read(OUT / f"vietstock-channel-history/channel-{c['channel_id']}.json")["records"])
               for c in channel_manifest if c["complete_for_endpoint_query"]]
    incremental = read(OUT / "vietstock-incremental/result.json")
    assert incremental["complete_for_endpoint_query"] and incremental["rows"] == len(incremental["records"])
    patches.append(("2026-10-12_to_2026-10-23", incremental["records"]))
    provenance = {r["EventID"]: "baseline_2026-10-11" for r in baseline}
    for source, rows in patches:
        for r in rows:
            event_id = r["EventID"]
            if event_id not in merged:
                added_ids.add(event_id)
            elif {k: v for k, v in merged[event_id].items() if k != "Row"} != {k: v for k, v in r.items() if k != "Row"}:
                changed_ids.add(event_id)
            merged[event_id] = r
            provenance[event_id] = source
    (exports / "structured_events.json").write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2))
    normalized = []
    for r in merged.values():
        if r["ChannelID"] not in REGULATORY:
            continue
        note = r.get("Note") or ""
        direction = ("enter" if note.startswith(("Has been put", "Đưa cổ phiếu vào")) else
                     "exit" if note.startswith(("Remove out", "Đưa cổ phiếu ra")) else "unknown")
        event_date = provider_date(r.get("Time"))
        flags = []
        if r["Exchange"] == "UPCoM" and event_date and event_date < "2009-06-24":
            flags.append("provider_venue_predates_market_launch")
        if r["ChannelID"] == 19 and "kiểm soát" in (r.get("Title") or "").lower():
            flags.append("alert_category_title_mentions_control")
        if direction == "unknown":
            flags.append("direction_unmapped")
        normalized.append({"event_id": r["EventID"], "symbol": r["Code"], "provider_exchange": r["Exchange"],
                           "provider_category_id": r["ChannelID"], "provider_category": r["Name"],
                           "provider_event_date": event_date, "query_date": provider_date(r.get("DateOrder")),
                           "direction_from_provider_note": direction,
                           "provider_date_hcb": provider_date(r.get("DateHCB")),
                           "provider_date_gdtl": provider_date(r.get("DateGDTL")),
                           "note": note, "title": r.get("Title"), "quality_flags": ";".join(flags),
                           "retrieval_partition": provenance[r["EventID"]]})
    normalized.sort(key=lambda r: (r["provider_event_date"] or "", r["event_id"]))
    csv_export(exports / "regulatory_transitions.csv", normalized, list(normalized[0]))

    delistings = read(OUT / "hose-delisting-history/events.json")
    delisting_manifest = read(OUT / "hose-delisting-history/manifest.json")
    assert len({r["id"] for r in delistings}) == len(delistings)
    matched = []
    for r in delistings:
        if r["code"] in codes:
            matched.append({"event_id": r["id"], "symbol": r["code"], "name": r["name"],
                            "security_id": r["securityId"],
                            "cancel_date": datetime.fromtimestamp(r["cancelDate"], timezone.utc).date().isoformat(),
                            "instrument_match": "ticker_matches_stock_master;type_not_in_register",
                            "listing_status_id": r["listingStatusId"], "deleted": r["deleted"]})
    csv_export(exports / "hose_delistings_stock_matches.csv", matched, list(matched[0]))

    profiles = []
    for label in ("hnx-amv-detail", "hnx-detail-shs", "hnx-detail-acm", "hnx-detail-ftm"):
        receipt = read(OUT / label / "receipt.json")
        assert receipt["http_status"] == "200" and receipt["curl_exit"] == 0
        body = (OUT / label / "body").read_text()
        values = {}
        for m in re.finditer(r'<div class="dktimkiem_cell_title">\s*<label>(.*?)</label>\s*</div>\s*<div class="dktimkiem_cell_content"[^>]*>(.*?)</div>', body, re.S):
            clean = lambda x: html.unescape(re.sub('<[^>]+>', '', x)).strip()
            values[clean(m[1])] = clean(m[2])
        assert values.get("Trạng thái kiểm soát") and values.get("Trạng thái giao dịch")
        profiles.append({"symbol": "AMV" if label == "hnx-amv-detail" else label.split('-')[-1].upper(),
                         "regulatory_status": values["Trạng thái kiểm soát"], "trading_status": values["Trạng thái giao dịch"],
                         "source_url": receipt["url"], "observed_at": receipt["fetched_at"]})
    csv_export(exports / "direct_profile_examples.csv", profiles, list(profiles[0]))

    category_stats = []
    for channel in sorted(REGULATORY):
        rows = [r for r in normalized if r["provider_category_id"] == channel]
        category_stats.append({"channel": channel, "category": rows[0]["provider_category"], "rows": len(rows),
                               "first": min(r["provider_event_date"] for r in rows),
                               "last": max(r["provider_event_date"] for r in rows),
                               "directions": dict(Counter(r["direction_from_provider_note"] for r in rows))})
    report = {
        "stock_master": {"records": len(master), "status_counts": dict(Counter(r["status"] for r in master)),
                         "market_and_status_counts": dict(Counter(r["floor"] + ":" + r["status"] for r in master)),
                         "listing_after_delisting": sum("listing_after_delisting" in r["quality_flags"] for r in master_rows)},
        "structured_history": {"baseline_records": len(baseline), "merged_records": len(merged), "new_ids": len(added_ids),
                               "changed_ids_excluding_pagination": sorted(changed_ids), "regulatory_records": len(normalized),
                               "regulatory_symbols": len({r["symbol"] for r in normalized}),
                               "directions": dict(Counter(r["direction_from_provider_note"] for r in normalized)),
                               "explicit_hcb_dates": sum(bool(r["provider_date_hcb"]) for r in normalized),
                               "explicit_resume_dates": sum(bool(r["provider_date_gdtl"]) for r in normalized),
                               "quality_flagged_rows": sum(bool(r["quality_flags"]) for r in normalized),
                               "categories": category_stats, "incremental_new_window_rows": incremental["rows"],
                               "full_channel_queries_failed": [c["channel_id"] for c in channel_manifest if not c["complete_for_endpoint_query"]],
                               "baseline_early_coverage_unknown_preserved": True},
        "hose_delisting_register": {"records_all_security_types": len(delistings), "ticker_matched_stock_rows": len(matched),
                                    "ticker_matched_stock_symbols": len({r["symbol"] for r in matched}),
                                    "all_27_year_queries_complete": all(r["complete_for_endpoint_query"] for r in delisting_manifest),
                                    "stock_match_not_a_complete_instrument_classification": True},
        "hose_date_filter_test": {"undocumented_from_to_2000_matches_current_payload": read(OUT / "hose-status-warning/body") == read(OUT / "hose-stock-status-dated-control/body"),
                                  "frontend_supported_params": ["pageIndex", "pageSize", "statusListId"],
                                  "does_not_prove_no_other_history_endpoint": True},
        "daily_status_since_2000_complete": False,
        "no_event_or_no_quote_does_not_mean_normal": True,
    }
    (OUT / "research-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
