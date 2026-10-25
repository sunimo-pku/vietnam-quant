"""Fetch public SSI/DNSE status snapshots without accounts or credentials.

Research collector: preserves each source separately; does not resolve conflicts.
Usage: python scripts/probe_anonymous_status.py --output outputs/anonymous-probe
Optional --pool points to an existing daily_status.csv for coverage validation.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ADMIN = {0: "UNSPECIFIED", 1: "C&R", 2: "CTR", 3: "NRM", 4: "RES",
         5: "WFR", 6: "WID", 7: "WOV"}
METHOD = {0: "UNSPECIFIED", 1: "NRM", 2: "NWE", 3: "NWN", 4: "SLS", 5: "SNE"}
SANCTION = {0: "UNSPECIFIED", 1: "NRM", 2: "SUS", 3: "DTL", 4: "TFR"}


def fetch(folder, name, url, payload=None):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    requested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read()
        receipt = {"url": url, "method": request.get_method(), "request": payload,
                   "http_status": response.status, "requested_at": requested_at,
                   "received_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "authentication": "none", "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}
    (folder / f"{name}.json").write_bytes(raw)
    (folder / f"{name}-receipt.json").write_text(json.dumps(receipt, indent=2))
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pool", type=Path)
    args = parser.parse_args()
    folder = args.output / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    stocks = []
    for exchange in ("hose", "hnx", "upcom"):
        data = fetch(folder, f"ssi-{exchange}",
                     f"https://iboard-query.ssi.com.vn/stock/exchange/{exchange}")
        if data.get("code") != "SUCCESS" or not isinstance(data.get("data"), list):
            raise ValueError(f"SSI response invalid: {exchange}")
        stocks.extend(x for x in data["data"] if x.get("stockType") == "s")
    symbols = sorted(x["stockSymbol"] for x in stocks)
    if len(symbols) != len(set(symbols)):
        raise ValueError("Duplicate SSI symbols; investigate before joining")
    dnse = {}
    for i in range(0, len(symbols), 100):
        query = ('{ GetKrxStockInfoBySymbols(symbols: ' + json.dumps(symbols[i:i + 100])
                 + ', board: 2) { si { symbol marketId symbolAdminStatusCode '
                 'symbolTradingMethodStatusCode symbolTradingSanctionStatusCode '
                 'securityStatus tradingTime } } }')
        data = fetch(folder, f"dnse-{i:04d}", "https://api.dnse.com.vn/price-api/query",
                     {"query": query})
        if data.get("errors"):
            raise ValueError(f"DNSE GraphQL errors: {data['errors']}")
        for row in data["data"]["GetKrxStockInfoBySymbols"]["si"]:
            if row["symbol"] in dnse:
                raise ValueError("Duplicate DNSE symbol")
            dnse[row["symbol"]] = row
        time.sleep(0.15)
    rows = []
    for stock in stocks:
        symbol = stock["stockSymbol"]
        d = dnse.get(symbol, {})
        admin = ADMIN.get(d.get("symbolAdminStatusCode"), "UNKNOWN")
        ssi_admin = stock.get("adminStatus")
        comparison = ("unknown" if not ssi_admin or admin in ("UNKNOWN", "UNSPECIFIED")
                      else "agree" if ssi_admin == admin else "conflict")
        rows.append({"symbol": symbol, "market": stock["exchange"].upper(),
                     "ssi_admin": ssi_admin, "ssi_trading": stock.get("tradingStatus"),
                     "ssi_perma_halt": stock.get("permaHalt"),
                     "ssi_trading_date": stock.get("tradingDate"),
                     "dnse_admin_raw": d.get("symbolAdminStatusCode"),
                     "dnse_admin": admin,
                     "dnse_method_raw": d.get("symbolTradingMethodStatusCode"),
                     "dnse_method": METHOD.get(d.get("symbolTradingMethodStatusCode"), "UNKNOWN"),
                     "dnse_sanction_raw": d.get("symbolTradingSanctionStatusCode"),
                     "dnse_sanction": SANCTION.get(d.get("symbolTradingSanctionStatusCode"), "UNKNOWN"),
                     "dnse_security_status_raw": d.get("securityStatus"),
                     "dnse_trading_time": d.get("tradingTime"),
                     "admin_comparison": comparison})
    with (folder / "status_comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"ssi_count": len(stocks), "dnse_count": len(dnse),
               "ssi_market_counts": dict(collections.Counter(r["market"] for r in rows)),
               "ssi_admin_counts": dict(collections.Counter(r["ssi_admin"] for r in rows)),
               "dnse_admin_counts": dict(collections.Counter(r["dnse_admin"] for r in rows)),
               "admin_comparison_counts": dict(collections.Counter(r["admin_comparison"] for r in rows)),
               "dnse_missing": sorted(set(symbols) - dnse.keys()),
               "dnse_extra": sorted(dnse.keys() - set(symbols)),
               "ssi_trading_dates": dict(collections.Counter(r["ssi_trading_date"] for r in rows)),
               "dnse_trading_dates": dict(collections.Counter((r["dnse_trading_time"] or "")[:10] for r in rows)),
               "status_dimensions_complete_verified": False}
    if args.pool:
        with args.pool.open(encoding="utf-8-sig", newline="") as f:
            pool = {(r["market"], r["symbol"]) for r in csv.DictReader(f)}
        observed = {(r["market"], r["symbol"]) for r in rows}
        summary["pool_missing"] = sorted(pool - observed)
        summary["pool_extra"] = sorted(observed - pool)
        summary["reference_pool"] = str(args.pool.resolve())
    (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    print(folder)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
