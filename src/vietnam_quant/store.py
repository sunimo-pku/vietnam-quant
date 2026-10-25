"""Atomic per-source snapshots and observed list changes in SQLite."""
import json
from pathlib import Path
import sqlite3

from .http import utc_now, FetchError

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
 id INTEGER PRIMARY KEY, market TEXT NOT NULL, observed_at TEXT NOT NULL,
 count INTEGER NOT NULL, receipts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
 snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), symbol TEXT NOT NULL,
 record_key TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(snapshot_id, symbol, record_key)
);
CREATE TABLE IF NOT EXISTS changes (
 snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), symbol TEXT NOT NULL,
 record_key TEXT NOT NULL, change_type TEXT NOT NULL, before TEXT, after TEXT
);
CREATE TABLE IF NOT EXISTS failures (
 id INTEGER PRIMARY KEY, market TEXT NOT NULL, observed_at TEXT NOT NULL, error TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def save(self, market, records, receipts, observed_at=None):
        # HOSE provides no per-reason ID; publication time distinguishes multiple
        # reasons while allowing edits to their reason/effective date to be tracked.
        keyed = {(r["symbol"], r["category_id"] + "|" + (r.get("published_at") or "")):
                 json.dumps(r, ensure_ascii=False, sort_keys=True)
                 for r in records}
        if len(keyed) != len(records):
            raise FetchError("Duplicate snapshot identity")
        previous = self.db.execute("SELECT id, count FROM snapshots WHERE market=? ORDER BY id DESC LIMIT 1",
                                   (market,)).fetchone()
        # A sudden list collapse is quarantined until independently checked, never reported as mass recovery.
        if previous and previous[1] >= 10 and len(records) < previous[1] * 0.5:
            raise FetchError("Regulatory list shrank by over 50%; retain previous snapshot for review")
        before = dict(((s, c), p) for s, c, p in self.db.execute(
            "SELECT symbol, record_key, payload FROM records WHERE snapshot_id=?", (previous[0],))) if previous else {}
        def comparable(payload):
            if payload is None:
                return None
            value = json.loads(payload)
            # Provenance navigation changes do not count as changes to a status.
            value.pop("source_url", None)
            return value
        with self.db:
            cursor = self.db.execute("INSERT INTO snapshots(market, observed_at, count, receipts) VALUES(?,?,?,?)",
                                     (market, observed_at or utc_now(), len(records), json.dumps(receipts)))
            sid = cursor.lastrowid
            self.db.executemany("INSERT INTO records VALUES(?,?,?,?)", [(sid, *key, value) for key, value in keyed.items()])
            changes = []
            if previous:
                for key in sorted(set(before) | set(keyed)):
                    if comparable(before.get(key)) != comparable(keyed.get(key)):
                        kind = "added" if key not in before else "removed" if key not in keyed else "changed"
                        changes.append((sid, *key, kind, before.get(key), keyed.get(key)))
            self.db.executemany("INSERT INTO changes VALUES(?,?,?,?,?,?)", changes)
        return {"market": market, "snapshot_id": sid, "rows": len(records),
                "symbols": len({r["symbol"] for r in records}), "changes": len(changes),
                "initial_baseline": previous is None}

    def failure(self, market, exc):
        with self.db:
            self.db.execute("INSERT INTO failures(market,observed_at,error) VALUES(?,?,?)", (market, utc_now(), str(exc)))

    def latest(self):
        return [{**json.loads(payload), "observed_at": observed} for payload, observed in self.db.execute("""
            SELECT records.payload, snapshots.observed_at FROM records
            JOIN snapshots ON records.snapshot_id=snapshots.id WHERE snapshot_id IN (
                SELECT MAX(id) FROM snapshots GROUP BY market)
            ORDER BY symbol,record_key
        """)]
