"""Versioned export contract shared by parsers, pipeline and consumers."""

SCHEMA_VERSION = "1.0"
MARKETS = ("HOSE", "HNX", "UPCOM")
DNSE_MARKETS = {6: "HOSE", 7: "HNX", 8: "UPCOM"}

# Five original status values; provider prefixes make differing meanings explicit.
STATUS_FIELDS = (
    "ssi_admin_status",
    "ssi_trading_status",
    "dnse_trading_method_status",
    "dnse_trading_sanction_status",
    "dnse_security_status",
)
TABLE_FIELDS = ("trade_date", "market", "symbol", *STATUS_FIELDS)
KNOWN_VALUES = {
    "ssi_admin_status": {"NRM", "WFR", "WID", "WOV", "CTR", "RES", "C&R"},
    "ssi_trading_status": {"N", "RT", "TFR", "S", "D", "NL", "ST"},
    "dnse_trading_method_status": {0, 1, 2, 3, 4, 5},
    "dnse_trading_sanction_status": {0, 1, 2, 3, 4},
    "dnse_security_status": {0, 1, 2},
}


class SourceError(ValueError):
    """Input cannot be interpreted as the expected provider response."""
