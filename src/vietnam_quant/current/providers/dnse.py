"""Parse anonymous DNSE GraphQL snapshots, keeping the numeric wire values."""

from ..contract import DNSE_MARKETS, SourceError

ENDPOINT = "https://api.dnse.com.vn/price-api/query"
FIELDS = {
    "symbolTradingMethodStatusCode": "dnse_trading_method_status",
    "symbolTradingSanctionStatusCode": "dnse_trading_sanction_status",
    "securityStatus": "dnse_security_status",
}


def parse_batch(payload):
    if not isinstance(payload, dict) or payload.get("errors"):
        raise SourceError("DNSE: failed GraphQL response")
    try:
        data = payload["data"]["GetKrxStockInfoBySymbols"]["si"]
    except (KeyError, TypeError) as exc:
        raise SourceError("DNSE: missing stock snapshot") from exc
    if not isinstance(data, list):
        raise SourceError("DNSE: stock snapshot is not a list")
    rows = {}
    for item in data:
        if not isinstance(item, dict):
            raise SourceError("DNSE: malformed row")
        symbol, market = item.get("symbol"), item.get("marketId")
        if not isinstance(symbol, str) or not symbol or symbol in rows:
            raise SourceError(f"DNSE: invalid/duplicate symbol {symbol!r}")
        if type(market) is not int or market not in DNSE_MARKETS:
            raise SourceError(f"DNSE {symbol}: invalid marketId {market!r}")
        row = {"market": DNSE_MARKETS[market], "symbol": symbol}
        for raw, target in FIELDS.items():
            value = item.get(raw)
            if value is not None and type(value) is not int:
                raise SourceError(f"DNSE {symbol}: {raw} is not an integer or null")
            row[target] = value
        rows[symbol] = row
    return rows
