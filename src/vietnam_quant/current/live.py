"""Collect current anonymous snapshots, validate and publish a daily table."""

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..universe import stock_directory
from .contract import MARKETS, SCHEMA_VERSION, SourceError
from .pipeline import build_table, write_tables
from .providers.dnse import ENDPOINT as DNSE_ENDPOINT
from .providers.ssi import ENDPOINT as SSI_ENDPOINT
from .providers.ssi import parse_exchange
from .storage import output_lock, publish_latest, recover_latest, write_json
from .transport import Transport

VN = timezone(timedelta(hours=7))
ADMIN_CODES = {1: "C&R", 2: "CTR", 3: "NRM", 4: "RES", 5: "WFR", 6: "WID", 7: "WOV"}


def read_current_directory(client, market):
    # Keep HOSE responses below its intermittently observed ~16 KiB truncation.
    # Sequential paging stops on the first failed page instead of queuing work.
    return stock_directory(client, market, hose_page_size=10, hose_workers=1)


def dnse_query(symbols):
    return {
        "query": (
            "{ GetKrxStockInfoBySymbols(symbols: "
            + json.dumps(symbols)
            + ", board: 2) { si { symbol marketId symbolAdminStatusCode "
            "symbolTradingMethodStatusCode symbolTradingSanctionStatusCode "
            "securityStatus tradingTime } } }"
        )
    }


def evidence_checks(rows, batches, now, max_age_days):
    """Extra evidence stays in quality.json, never in the eight-column table."""
    issues = []
    trade_date = date.fromisoformat(rows[0]["trade_date"])
    age = (now.astimezone(VN).date() - trade_date).days
    if age < 0 or age > max_age_days:
        issues.append(
            {"issue": "source_date_outside_allowed_age", "age_days": age, "severity": "error"}
        )
    indexed = {row["symbol"]: row for row in rows}
    for batch in batches:
        for source in batch["data"]["GetKrxStockInfoBySymbols"]["si"]:
            symbol = source["symbol"]
            if symbol not in indexed:
                continue
            code = source.get("symbolAdminStatusCode")
            expected = ADMIN_CODES.get(code) if type(code) is int else None
            if expected is None:
                issues.append(
                    {
                        "symbol": symbol,
                        "issue": "dnse_admin_unconfirmed",
                        "value": code,
                        "severity": "warning",
                    }
                )
            elif expected != indexed[symbol]["ssi_admin_status"]:
                issues.append(
                    {
                        "symbol": symbol,
                        "issue": "admin_disagreement",
                        "ssi": indexed[symbol]["ssi_admin_status"],
                        "dnse": code,
                        "severity": "error",
                    }
                )
            try:
                timestamp = datetime.fromisoformat(source["tradingTime"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("timestamp has no timezone")
                if timestamp.astimezone(VN).date() != trade_date or timestamp > now + timedelta(
                    minutes=5
                ):
                    issues.append(
                        {
                            "symbol": symbol,
                            "issue": "dnse_time_mismatch",
                            "value": source["tradingTime"],
                            "severity": "error",
                        }
                    )
            except (KeyError, TypeError, ValueError, AttributeError):
                issues.append({"symbol": symbol, "issue": "dnse_time_unknown", "severity": "error"})
    return issues


def update(
    settings,
    output=None,
    *,
    transport_factory=Transport,
    directory_reader=read_current_directory,
    now=None,
    progress=print,
):
    output = Path(output or settings.output_dir).resolve()
    now = now or datetime.now(timezone.utc)
    with output_lock(output):
        recover_latest(output)
        run = output / "runs" / (now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8])
        (run / "raw").mkdir(parents=True)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "mode": "live",
            "status": "running",
            "started_at": now.isoformat(),
            "run_dir": str(run),
            "settings": settings.as_dict(),
            "all_status_dimensions_verified": False,
        }
        write_json(run / "manifest.json", manifest)
        write_json(output / "last_attempt.json", manifest)
        issues = []
        published = False
        try:
            client = transport_factory(run / "raw", settings)
            client.progress = progress
            ssi, stock_rows = {}, []
            for market in MARKETS:
                progress(f"获取 {market} 股票列表和状态…", flush=True)
                payload = client.json(
                    f"ssi-{market.lower()}", SSI_ENDPOINT.format(exchange=market.lower())
                )
                stock_rows.extend(parse_exchange(payload, market))
                ssi[market] = payload
            symbols = sorted(row["symbol"] for row in stock_rows)
            if len(set(symbols)) != len(symbols):
                raise SourceError("Duplicate symbol in SSI markets")
            batches = []
            for start in range(0, len(symbols), settings.dnse_batch_size):
                progress(
                    f"核对 DNSE 状态 {start + 1}–{min(start + settings.dnse_batch_size, len(symbols))}/{len(symbols)}…",
                    flush=True,
                )
                batches.append(
                    client.json(
                        f"dnse-{start:04d}",
                        DNSE_ENDPOINT,
                        dnse_query(symbols[start : start + settings.dnse_batch_size]),
                    )
                )
            rows, issues = build_table(ssi, batches)
            issues = [{**issue, "severity": "error"} for issue in issues]
            issues.extend(evidence_checks(rows, batches, now, settings.max_data_age_days))
            directory_checked = False
            if settings.verify_exchange_directory:
                actual = {(row["market"], row["symbol"]) for row in rows}
                expected = set()
                for market in MARKETS:
                    progress(f"核对 {market} 交易所股票目录…", flush=True)
                    records, _ = directory_reader(client, market)
                    if not records:
                        raise SourceError(f"{market}: empty exchange directory")
                    write_json(run / "raw" / f"exchange-directory-{market}.json", records)
                    expected.update((r["market"], r["symbol"]) for r in records)
                for market, symbol in sorted(expected - actual):
                    issues.append(
                        {
                            "market": market,
                            "symbol": symbol,
                            "issue": "missing_from_ssi_pool",
                            "severity": "error",
                        }
                    )
                for market, symbol in sorted(actual - expected):
                    issues.append(
                        {
                            "market": market,
                            "symbol": symbol,
                            "issue": "outside_exchange_directory",
                            "severity": "error",
                        }
                    )
                directory_checked = True
            else:
                issues.append({"issue": "exchange_directory_not_checked", "severity": "warning"})
            # A sudden smaller pool deserves review even if a directory agrees.
            previous_path = output / "latest" / "status.json"
            if previous_path.exists():
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
                for market in MARKETS:
                    old_count = sum(r["market"] == market for r in previous)
                    new_count = sum(r["market"] == market for r in rows)
                    if old_count and new_count < old_count * 0.95:
                        issues.append(
                            {
                                "market": market,
                                "issue": "pool_shrank_over_5_percent",
                                "previous": old_count,
                                "current": new_count,
                                "severity": "error",
                            }
                        )
            errors = sum(issue["severity"] == "error" for issue in issues)
            manifest.update(
                trade_date=rows[0]["trade_date"],
                row_count=len(rows),
                market_counts={
                    market: sum(r["market"] == market for r in rows) for market in MARKETS
                },
                directory_checked=directory_checked,
                issues_count=len(issues),
                errors_count=errors,
                status="needs_review" if errors else "success",
                schema_checks_passed=not errors,
            )
            write_tables(run, rows, issues)
            result = (
                f"{'需要检查，本次未更新 latest' if errors else '采集与检查完成'}\n"
                f"数据交易日：{manifest['trade_date']}\n股票数量：{len(rows)}\n"
                f"检查问题：{errors} 项错误，{len(issues) - errors} 项提示\n"
                f"本轮结果：{run}\n股票目录核对：{'已执行' if directory_checked else '已关闭'}\n"
                "数据日期可能早于运行日期；字段含义请查看 docs/status-schema.md。\n"
            )
            (run / "result.txt").write_text(result, encoding="utf-8")
            manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
            manifest["raw_hashes"] = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((run / "raw").iterdir())
                if p.is_file()
            }
            write_json(run / "manifest.json", manifest)
            if not errors:
                write_json(output / "last_attempt.json", {**manifest, "status": "publishing"})
                publish_latest(run, output)
                published = True
            write_json(output / "last_attempt.json", manifest)
            progress(result, flush=True)
            progress(f"最近可用结果：{output / 'latest'}", flush=True)
            return run, manifest
        except (Exception, KeyboardInterrupt) as exc:
            if published:
                # Console interruption after publication must not relabel a committed
                # successful snapshot as failed or claim that old latest was kept.
                return run, manifest
            manifest.update(
                status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                error=f"{type(exc).__name__}: {exc}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            write_json(run / "quality.json", {"issues": issues, "failure": manifest["error"]})
            write_json(run / "manifest.json", manifest)
            write_json(output / "last_attempt.json", manifest)
            message = f"更新未完成，原 latest 保留。\n原因：{manifest['error']}\n本轮记录：{run}\n"
            (run / "result.txt").write_text(message, encoding="utf-8")
            progress(message, flush=True)
            return run, manifest
