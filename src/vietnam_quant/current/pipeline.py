"""Replay saved anonymous-source responses into the agreed eight-column table.

Each run preserves its inputs; replaying old data never changes its provider
trading date. The live collector reuses build_table and write_tables.
"""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .contract import (
    KNOWN_VALUES,
    MARKETS,
    SCHEMA_VERSION,
    STATUS_FIELDS,
    TABLE_FIELDS,
    SourceError,
)
from .providers.dnse import parse_batch
from .providers.ssi import parse_exchange


def build_table(ssi_payloads, dnse_payloads):
    if set(ssi_payloads) != set(MARKETS):
        raise SourceError("All three SSI markets are required")
    stocks = [row for market in MARKETS for row in parse_exchange(ssi_payloads[market], market)]
    if len({row["symbol"] for row in stocks}) != len(stocks):
        raise SourceError("Duplicate SSI symbol across markets")
    if len({row["trade_date"] for row in stocks}) != 1:
        raise SourceError(
            "SSI snapshots have mixed trading dates; do not merge into one daily table"
        )
    dnse = {}
    for payload in dnse_payloads:
        batch = parse_batch(payload)
        if dnse.keys() & batch.keys():
            raise SourceError("Duplicate DNSE symbol across batches")
        dnse.update(batch)
    rows, issues = [], []
    for stock in stocks:
        symbol = stock["symbol"]
        other = dnse.get(symbol)
        if other is not None and other["market"] != stock["market"]:
            raise SourceError(f"{symbol}: provider market mismatch")
        if other is None:
            issues.append({"symbol": symbol, "issue": "missing_dnse_stock"})
        row = dict(stock)
        row.update({key: (other or {}).get(key) for key in STATUS_FIELDS[2:]})
        for field in STATUS_FIELDS:
            value = row[field]
            if value is None or value == "":
                issue = "missing_status"
            elif value not in KNOWN_VALUES[field]:
                issue = "unknown_code"
            elif field.startswith("dnse_") and value == 0:
                issue = "unspecified_status"
            else:
                continue
            issues.append({"symbol": symbol, "field": field, "issue": issue, "value": value})
        rows.append(row)
    extras = sorted(dnse.keys() - {stock["symbol"] for stock in stocks})
    issues.extend({"symbol": symbol, "issue": "dnse_outside_ssi_pool"} for symbol in extras)
    rows.sort(key=lambda row: (row["market"], row["symbol"]))
    return rows, issues


def write_tables(run, rows, issues):
    with (run / "status.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (run / "status.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run / "quality.json").write_text(
        json.dumps({"issues": issues}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def export_saved_run(source: Path, output: Path):
    """Accept the exact file layout saved by probe_anonymous_status.py."""
    captured = {}

    def read(path):
        raw = path.read_bytes()
        captured[path.name] = raw
        return json.loads(raw)

    ssi = {market: read(source / f"ssi-{market.lower()}.json") for market in MARKETS}
    batches = sorted(source.glob("dnse-[0-9][0-9][0-9][0-9].json"))
    if not batches:
        raise SourceError("No DNSE batch files in source run")
    rows, issues = build_table(ssi, [read(path) for path in batches])
    for name in list(captured):
        receipt = source / name.replace(".json", "-receipt.json")
        if receipt.is_file():
            captured[receipt.name] = receipt.read_bytes()
            recorded_hash = json.loads(captured[receipt.name]).get("sha256")
            if recorded_hash and recorded_hash != hashlib.sha256(captured[name]).hexdigest():
                raise SourceError(f"Saved response hash mismatch: {name}")
    generated_at = datetime.now(timezone.utc)
    run = output / "runs" / generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    (run / "raw").mkdir(parents=True, exist_ok=False)
    for name, raw in captured.items():
        (run / "raw" / name).write_bytes(raw)
    write_tables(run, rows, issues)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": "offline_replay",
        "generated_at": generated_at.isoformat(),
        "source_run": str(source.resolve()),
        "trade_date": rows[0]["trade_date"],
        "row_count": len(rows),
        "market_counts": {
            market: sum(row["market"] == market for row in rows) for market in MARKETS
        },
        "pool_basis": "SSI stockType=s; not independently verified against exchange directories in this run",
        "issues_count": len(issues),
        "schema_checks_passed": not issues,
        "all_status_dimensions_verified": False,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in captured.items()},
    }
    # Written last: an interrupted export has no completion manifest.
    (run / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run, manifest
