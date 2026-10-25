import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from vietnam_quant.current.config import Settings, load_settings
from vietnam_quant.current.live import update
from vietnam_quant.current.storage import (
    output_lock,
    publish_latest,
    recover_latest,
)
from vietnam_quant.current.transport import Transport, TransportError, retry_after_seconds

FIXTURES = Path(__file__).parent / "fixtures" / "current"
NOW = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)


class FakeResponse:
    status = 200

    def __init__(self, raw=b'{"ok":true}', headers=None):
        self.raw = raw
        self.headers = headers or {"Content-Length": str(len(raw))}

    def read(self, count=None):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FixtureTransport:
    fail = False
    unknown = False

    def __init__(self, folder, settings):
        self.folder = folder

    def json(self, name, url, payload=None):
        if self.fail:
            raise TransportError("offline injected failure")
        source = "dnse-0000.json" if name.startswith("dnse-") else f"{name}.json"
        data = json.loads((FIXTURES / source).read_text(encoding="utf-8"))
        if name.startswith("dnse-"):
            symbols = json.loads(payload["query"].split("symbols: ", 1)[1].split(", board:", 1)[0])
            key = data["data"]["GetKrxStockInfoBySymbols"]
            key["si"] = [r for r in key["si"] if r["symbol"] in symbols]
        elif self.unknown:
            data["data"][0]["adminStatus"] = "NEW_CODE"
        raw = json.dumps(data).encode()
        (self.folder / f"{name}.json").write_bytes(raw)
        (self.folder / f"{name}-receipt.json").write_text(
            json.dumps({"sha256": hashlib.sha256(raw).hexdigest()}), encoding="utf-8"
        )
        return data


def directory(client, market):
    data = json.loads((FIXTURES / f"ssi-{market.lower()}.json").read_text(encoding="utf-8"))
    return [{"market": market, "symbol": r["stockSymbol"]} for r in data["data"]], []


def run_fixture(output, **kwargs):
    return update(
        Settings(dnse_batch_size=2),
        output,
        transport_factory=FixtureTransport,
        directory_reader=kwargs.pop("directory_reader", directory),
        now=kwargs.pop("now", NOW),
        progress=lambda *a, **k: None,
        **kwargs,
    )


class TransportTests(unittest.TestCase):
    def test_transport_keeps_certificate_and_hostname_verification_enabled(self):
        import ssl

        with tempfile.TemporaryDirectory() as tmp:
            transport = Transport(tmp, Settings(), opener=Mock())
            self.assertTrue(transport.ssl_context.check_hostname)
            self.assertEqual(transport.ssl_context.verify_mode, ssl.CERT_REQUIRED)

    def test_429_obeys_retry_after_and_preserves_both_receipts(self):
        error = HTTPError(
            "https://example.com", 429, "limited", {"Retry-After": "3"}, io.BytesIO(b"limited")
        )
        opener = Mock(side_effect=[error, FakeResponse()])
        sleeps = []
        with tempfile.TemporaryDirectory() as tmp:
            client = Transport(tmp, Settings(), opener=opener, sleep=sleeps.append)
            self.assertEqual(client.json("ssi", "https://example.com"), {"ok": True})
            self.assertIn(3, sleeps)
            receipts = [
                json.loads(p.read_text()) for p in Path(tmp).glob("ssi-attempt-*-receipt.json")
            ]
            self.assertEqual(sorted(r["http_status"] for r in receipts), [200, 429])
            self.assertTrue(all(r["tls_verification"] for r in receipts))

    def test_long_retry_after_stops_instead_of_retrying_early(self):
        error = HTTPError(
            "https://example.com", 429, "limited", {"Retry-After": "3600"}, io.BytesIO()
        )
        opener = Mock(side_effect=error)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TransportError):
                Transport(tmp, Settings(), opener=opener, sleep=Mock()).json(
                    "ssi", "https://example.com"
                )
            self.assertEqual(opener.call_count, 1)

    def test_retry_after_http_date_and_invalid_value(self):
        self.assertEqual(retry_after_seconds("Sun, 25 Oct 2026 15:00:10 GMT", NOW), 10)
        self.assertIsNone(retry_after_seconds("invalid"))

    def test_truncated_response_retries_and_bad_json_keeps_evidence(self):
        opener = Mock(side_effect=[FakeResponse(headers={"Content-Length": "100"}), FakeResponse()])
        with tempfile.TemporaryDirectory() as tmp:
            client = Transport(tmp, Settings(), opener=opener, sleep=Mock())
            self.assertEqual(client.json("ssi", "https://example.com"), {"ok": True})
            self.assertEqual(opener.call_count, 2)
            client = Transport(
                tmp,
                Settings(),
                opener=Mock(return_value=FakeResponse(b"<html>error</html>")),
                sleep=Mock(),
            )
            with self.assertRaises(TransportError):
                client.json("html", "https://example.com")
            self.assertTrue(list(Path(tmp).glob("html-attempt-*.body")))
            self.assertFalse((Path(tmp) / "html.json").exists())

    def test_network_retry_is_bounded_and_403_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            opener = Mock(side_effect=URLError("offline"))
            with self.assertRaises(TransportError):
                Transport(tmp, Settings(max_attempts=2), opener=opener, sleep=Mock()).json(
                    "net", "https://example.com"
                )
            self.assertEqual(opener.call_count, 2)
            error = HTTPError("https://example.com", 403, "forbidden", {}, io.BytesIO())
            opener = Mock(side_effect=error)
            with self.assertRaises(TransportError):
                Transport(tmp, Settings(), opener=opener, sleep=Mock()).json(
                    "forbidden", "https://example.com"
                )
            self.assertEqual(opener.call_count, 1)


class LiveUpdateTests(unittest.TestCase):
    def test_official_hose_directory_uses_small_complete_pages(self):
        from urllib.parse import parse_qs, urlsplit

        from vietnam_quant.current.live import read_current_directory

        requests = []

        class DirectoryClient:
            def fetch(self, url):
                query = parse_qs(urlsplit(url).query)
                page, size = int(query["pageIndex"][0]), int(query["pageSize"][0])
                requests.append((page, size))
                rows = [
                    {"code": f"T{i:03}", "name": "Fixture company"}
                    for i in range((page - 1) * size, min(page * size, 12))
                ]
                return json.dumps(
                    {"success": True, "data": {"paging": {"totalCount": 12}, "list": rows}}
                ), {}

        rows, _ = read_current_directory(DirectoryClient(), "HOSE")
        self.assertEqual(len(rows), 12)
        self.assertEqual(requests, [(1, 10), (2, 10)])

    def test_post_publication_console_error_does_not_relabel_success(self):
        with tempfile.TemporaryDirectory() as tmp:

            def progress(message, **kwargs):
                if message.startswith("采集与检查完成"):
                    raise BrokenPipeError("console closed after publication")

            _, manifest = update(
                Settings(),
                Path(tmp),
                transport_factory=FixtureTransport,
                directory_reader=directory,
                now=NOW,
                progress=progress,
            )
            self.assertEqual(manifest["status"], "success")
            self.assertEqual(
                json.loads((Path(tmp) / "latest/manifest.json").read_text(encoding="utf-8"))[
                    "status"
                ],
                "success",
            )

    def test_replay_cannot_replace_live_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run, _ = run_fixture(output)
            before = (output / "latest/manifest.json").read_bytes()
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["mode"] = "offline_replay"
            (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with output_lock(output), self.assertRaises(ValueError):
                publish_latest(run, output)
            self.assertEqual(before, (output / "latest/manifest.json").read_bytes())

    def test_success_writes_eight_columns_and_preserves_each_run(self):
        with tempfile.TemporaryDirectory(prefix="越南 stocks ") as tmp:
            output = Path(tmp)
            run, manifest = run_fixture(output)
            self.assertEqual(manifest["status"], "success")
            self.assertEqual(manifest["row_count"], 7)
            self.assertTrue(manifest["directory_checked"])
            self.assertEqual(manifest["errors_count"], 0)
            self.assertEqual(manifest["issues_count"], 1)  # ECI admin=0 warning only
            self.assertEqual(
                len(
                    (run / "status.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(",")
                ),
                8,
            )
            self.assertEqual(
                (run / "status.csv").read_bytes(), (output / "latest/status.csv").read_bytes()
            )
            second, _ = run_fixture(output)
            self.assertNotEqual(run, second)
            self.assertTrue((run / "manifest.json").exists())

    def test_network_failure_keeps_latest_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run_fixture(output)
            before = (output / "latest/manifest.json").read_bytes()
            with patch.object(FixtureTransport, "fail", True):
                run, manifest = run_fixture(output)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(before, (output / "latest/manifest.json").read_bytes())
            self.assertTrue((run / "result.txt").exists())
            self.assertEqual(
                json.loads((output / "last_attempt.json").read_text())["status"], "failed"
            )

    def test_unknown_status_and_directory_gap_prevent_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch.object(FixtureTransport, "unknown", True):
                run, manifest = run_fixture(output)
            self.assertEqual(manifest["status"], "needs_review")
            self.assertTrue((run / "status.csv").exists())
            self.assertFalse((output / "latest").exists())

            def extra(client, market):
                rows, receipts = directory(client, market)
                return rows + [{"market": market, "symbol": "MISSING"}], receipts

            _, manifest = run_fixture(output, directory_reader=extra)
            self.assertEqual(manifest["status"], "needs_review")
            self.assertFalse((output / "latest").exists())

    def test_stale_source_date_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, manifest = run_fixture(Path(tmp), now=datetime(2026, 11, 10, tzinfo=timezone.utc))
            self.assertEqual(manifest["status"], "needs_review")
            self.assertFalse((Path(tmp) / "latest").exists())

    def test_dnse_timestamp_mismatch_blocks_publication(self):
        from test_current import inputs

        from vietnam_quant.current.live import evidence_checks
        from vietnam_quant.current.pipeline import build_table

        ssi, dnse = inputs()
        rows, _ = build_table(ssi, [dnse])
        dnse["data"]["GetKrxStockInfoBySymbols"]["si"][0]["tradingTime"] = "2026-10-22T07:00:00Z"
        issues = evidence_checks(rows, [dnse], NOW, 7)
        self.assertTrue(any(i["issue"] == "dnse_time_mismatch" for i in issues))

    def test_failed_directory_swap_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run, _ = run_fixture(output)
            before = (output / "latest/manifest.json").read_bytes()
            rename = Path.rename

            def broken(path, target):
                if path.name.startswith(".latest-stage-"):
                    raise PermissionError("injected Windows sharing violation")
                return rename(path, target)

            with output_lock(output), patch.object(Path, "rename", broken):
                with self.assertRaises(PermissionError):
                    publish_latest(run, output)
            self.assertEqual(before, (output / "latest/manifest.json").read_bytes())

    def test_interrupted_swap_recovers_and_old_dates_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run, _ = run_fixture(output)
            (output / "latest").rename(output / ".latest-backup")
            with output_lock(output):
                recover_latest(output)
                manifest = json.loads((output / "latest/manifest.json").read_text())
                manifest["trade_date"] = "2026-10-24"
                (output / "latest/manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    publish_latest(run, output)
            self.assertTrue((output / "latest/status.csv").exists())

    def test_lock_is_released_on_error_and_blocks_other_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            code = (
                "from pathlib import Path; from vietnam_quant.current.storage import output_lock; "
                "import sys;\nwith output_lock(Path(sys.argv[1])): pass"
            )
            with output_lock(output):
                process = subprocess.run([sys.executable, "-c", code, tmp], capture_output=True)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(b"AlreadyRunning", process.stderr)
            with output_lock(output):
                pass

    def test_invalid_settings_are_rejected(self):
        for kwargs in (
            {"request_interval_seconds": 0},
            {"max_attempts": True},
            {"timeout_seconds": float("nan")},
            {"dnse_batch_size": 0},
        ):
            with self.assertRaises(ValueError):
                Settings(**kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"typo": 1}')
            with self.assertRaises(ValueError):
                load_settings(path)
