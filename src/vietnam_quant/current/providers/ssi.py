"""Parse SSI public exchange snapshots without decoding or merging statuses."""

from datetime import datetime

from ..contract import MARKETS, SourceError

ENDPOINT = "https://iboard-query.ssi.com.vn/stock/exchange/{exchange}"


def parse_exchange(payload, market):
    if market not in MARKETS:
        raise SourceError(f"Unsupported market: {market}")
    if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
        raise SourceError(f"SSI {market}: unsuccessful response")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise SourceError(f"SSI {market}: missing/empty exchange snapshot")
    rows, seen = [], set()
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("stockType"), str):
            raise SourceError(f"SSI {market}: malformed security type")
        if item["stockType"] != "s":
            continue
        symbol = item.get("stockSymbol")
        if not isinstance(symbol, str) or not symbol or symbol in seen:
            raise SourceError(f"SSI {market}: invalid/duplicate symbol {symbol!r}")
        if item.get("exchange") != market.lower():
            raise SourceError(f"SSI {symbol}: exchange mismatch")
        seen.add(symbol)
        raw_date = item.get("tradingDate")
        if not isinstance(raw_date, str) or len(raw_date) != 8 or not raw_date.isdigit():
            raise SourceError(f"SSI {symbol}: invalid tradingDate {raw_date!r}")
        try:
            trade_date = datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
        except ValueError as exc:
            raise SourceError(f"SSI {symbol}: invalid tradingDate {raw_date!r}") from exc
        for key in ("adminStatus", "tradingStatus"):
            if item.get(key) is not None and not isinstance(item[key], str):
                raise SourceError(f"SSI {symbol}: {key} is not a string or null")
        rows.append(
            {
                "trade_date": trade_date,
                "market": market,
                "symbol": symbol,
                "ssi_admin_status": item.get("adminStatus"),
                "ssi_trading_status": item.get("tradingStatus"),
            }
        )
    if not rows:
        raise SourceError(f"SSI {market}: no stocks in snapshot")
    return rows
