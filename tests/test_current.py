import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vietnam_quant.current.contract import TABLE_FIELDS, SourceError
from vietnam_quant.current.pipeline import build_table, export_saved_run
from vietnam_quant.current.providers.dnse import parse_batch
from vietnam_quant.current.providers.ssi import parse_exchange

FIXTURES = Path(__file__).parent / "fixtures" / "current"


def inputs():
    ssi = {
        market: json.loads((FIXTURES / f"ssi-{market.lower()}.json").read_text())
        for market in ("HOSE", "HNX", "UPCOM")
    }
    dnse = json.loads((FIXTURES / "dnse-0000.json").read_text())
    return ssi, dnse


class CurrentContractTests(unittest.TestCase):
    def test_actual_samples_export_only_five_original_status_fields(self):
        ssi, dnse = inputs()
        rows, issues = build_table(ssi, [dnse])
        self.assertEqual(len(rows), 7)
        self.assertEqual(issues, [])
        self.assertEqual(set(rows[0]), set(TABLE_FIELDS))
        self.assertEqual(len(TABLE_FIELDS), 8)
        eci = next(row for row in rows if row["symbol"] == "ECI")
        self.assertEqual(eci["ssi_admin_status"], "C&R")
        self.assertEqual(eci["dnse_trading_sanction_status"], 2)
        # DNSE's admin=0 does not overwrite the chosen SSI regulatory field.
        self.assertEqual({row["trade_date"] for row in rows}, {"2026-10-23"})

    def test_missing_dnse_stock_remains_in_table_with_nulls_and_report(self):
        ssi, dnse = inputs()
        data = dnse["data"]["GetKrxStockInfoBySymbols"]["si"]
        dnse["data"]["GetKrxStockInfoBySymbols"]["si"] = [x for x in data if x["symbol"] != "ACM"]
        rows, issues = build_table(ssi, [dnse])
        acm = next(row for row in rows if row["symbol"] == "ACM")
        self.assertEqual(acm["ssi_admin_status"], "RES")
        self.assertIsNone(acm["dnse_security_status"])
        self.assertIn({"symbol": "ACM", "issue": "missing_dnse_stock"}, issues)

    def test_new_code_preserved_and_reported_not_replaced_by_normal(self):
        ssi, dnse = inputs()
        ssi["HOSE"]["data"][0]["adminStatus"] = "FUTURE_CODE"
        rows, issues = build_table(ssi, [dnse])
        self.assertTrue(any(row["ssi_admin_status"] == "FUTURE_CODE" for row in rows))
        self.assertTrue(any(issue["issue"] == "unknown_code" for issue in issues))

    def test_empty_and_zero_statuses_are_not_normal(self):
        ssi, dnse = inputs()
        ssi["HOSE"]["data"][0]["adminStatus"] = ""
        dnse["data"]["GetKrxStockInfoBySymbols"]["si"][0]["securityStatus"] = 0
        rows, issues = build_table(ssi, [dnse])
        self.assertTrue(any(row["ssi_admin_status"] == "" for row in rows))
        self.assertTrue(any(row["dnse_security_status"] == 0 for row in rows))
        self.assertIn("unspecified_status", {issue["issue"] for issue in issues})

    def test_funds_are_excluded_but_malformed_types_fail(self):
        ssi, _ = inputs()
        payload = ssi["HOSE"]
        payload["data"].append({"stockType": "m", "stockSymbol": "FUND"})
        self.assertEqual(len(parse_exchange(payload, "HOSE")), 3)
        del payload["data"][-1]["stockType"]
        with self.assertRaises(SourceError):
            parse_exchange(payload, "HOSE")

    def test_mixed_trading_dates_cannot_masquerade_as_same_day(self):
        ssi, dnse = inputs()
        ssi["HNX"]["data"][0]["tradingDate"] = "20261022"
        with self.assertRaises(SourceError):
            build_table(ssi, [dnse])

    def test_invalid_date_and_missing_market_fail(self):
        ssi, dnse = inputs()
        ssi["HOSE"]["data"][0]["tradingDate"] = "20260230"
        with self.assertRaises(SourceError):
            build_table(ssi, [dnse])
        del ssi["HOSE"]
        with self.assertRaises(SourceError):
            build_table(ssi, [dnse])

    def test_duplicate_and_market_mismatch_are_not_silently_joined(self):
        ssi, dnse = inputs()
        with self.assertRaises(SourceError):
            build_table(ssi, [dnse, copy.deepcopy(dnse)])
        dnse["data"]["GetKrxStockInfoBySymbols"]["si"][0]["marketId"] = 7
        with self.assertRaises(SourceError):
            build_table(ssi, [dnse])

    def test_graphql_errors_and_boolean_codes_fail(self):
        with self.assertRaises(SourceError):
            parse_batch({"errors": [{"message": "partial error"}], "data": None})
        _, dnse = inputs()
        dnse["data"]["GetKrxStockInfoBySymbols"]["si"][0]["securityStatus"] = True
        with self.assertRaises(SourceError):
            parse_batch(dnse)

    def test_export_is_offline_preserves_date_inputs_and_schema(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")),
        ):
            run, manifest = export_saved_run(FIXTURES, Path(tmp))
            self.assertEqual(manifest["mode"], "offline_replay")
            self.assertEqual(manifest["trade_date"], "2026-10-23")
            with (run / "status.csv").open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(TABLE_FIELDS))
                self.assertEqual(len(list(reader)), 7)
            self.assertEqual(
                (run / "raw/ssi-hose.json").read_bytes(), (FIXTURES / "ssi-hose.json").read_bytes()
            )
            second, _ = export_saved_run(FIXTURES, Path(tmp))
            self.assertNotEqual(run, second)
            self.assertEqual(
                (run / "status.csv").read_bytes(), (second / "status.csv").read_bytes()
            )

    def test_changed_saved_response_fails_receipt_validation(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            shutil.copytree(FIXTURES, source)
            (source / "ssi-hose-receipt.json").write_text('{"sha256":"incorrect"}')
            with self.assertRaises(SourceError):
                export_saved_run(source, Path(tmp) / "output")
            self.assertFalse((Path(tmp) / "output").exists())

    def test_cli_entrypoint_exports_without_network_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vietnam_quant.cli",
                    "--output",
                    tmp,
                    "current-report",
                    "--from-run",
                    str(FIXTURES),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["row_count"], 7)
