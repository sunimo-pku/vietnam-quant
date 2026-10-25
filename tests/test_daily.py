from datetime import datetime, timedelta
import unittest

from vietnam_quant.daily import VN, build_rows, is_fresh, label_tags, parse_profile, export_run
from vietnam_quant.http import FetchError
from vietnam_quant.sources import parse_hose_quote_states
from pathlib import Path
import tempfile
import json
from contextlib import redirect_stdout
from io import StringIO


NOW = datetime(2026, 10, 25, 17, tzinfo=VN)


def payload(rows=(), hours=0):
    return {"ok": True, "records": list(rows),
            "receipts": [{"fetched_at": (NOW - timedelta(hours=hours)).isoformat()}]}


def stock(symbol="AAA", market="HNX", **kw):
    return {"market": market, "symbol": symbol, **kw}


class DailyTests(unittest.TestCase):
    def test_empty_export_cannot_report_collection_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / 'run'; (run / 'sources').mkdir(parents=True)
            with redirect_stdout(StringIO()):
                self.assertFalse(export_run(root, run))
            self.assertFalse((root / 'latest_success.json').exists())

    def test_failed_attempt_cannot_replace_last_success_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / 'run'; (run / 'sources').mkdir(parents=True)
            previous = '{"run_dir":"previous_success"}'
            (root / 'latest_success.json').write_text(previous)
            with redirect_stdout(StringIO()):
                self.assertFalse(export_run(root, run))
            self.assertEqual((root / 'latest_success.json').read_text(), previous)

    def test_visible_empty_profile_is_unknown_not_normal(self):
        html = '<input id="StockCode" value="ABC"><input id="MarketCode" value="UC">'
        for label, value in [('Trạng thái kiểm soát', ''), ('Trạng thái giao dịch', 'Hoạt động')]:
            html += f'<div class="dktimkiem_row"><div class="dktimkiem_cell_title">{label}</div><div class="dktimkiem_cell_content">{value}</div></div>'
        parsed = parse_profile(html, 'UPCOM', 'ABC', 'https://example.org')
        self.assertIsNone(parsed['regulatory_label'])
        row = build_rows({'directory-UPCOM': payload([stock('ABC', 'UPCOM')])},
                         {'UPCOM-ABC': payload([parsed])}, now=NOW)[0]
        self.assertFalse(row['normal_reported'])
        self.assertIn('profile_field_empty', row['issues'])

    def test_hose_quote_schema_duplicate_and_warning_subtype(self):
        raw = {'securitySymbol': 'ABC', 'code': 'ABC', 'warning_status': 'WID'}
        rows = parse_hose_quote_states(json.dumps({'success': True, 'data': [raw]}))
        self.assertEqual(rows[0]['status_label']['admin_status']['code'], 'WID')
        with self.assertRaises(FetchError):
            parse_hose_quote_states(json.dumps({'success': True, 'data': [raw, raw]}))

    def test_fund_on_hose_board_does_not_expand_stock_pool(self):
        sources = {'directory-HOSE': payload([stock('ABC', 'HOSE')]),
                   'quotes-HOSE': payload([stock('FUCTVGF4', 'HOSE', status_label={})])}
        rows = build_rows(sources, {}, now=NOW)
        self.assertEqual([r['symbol'] for r in rows], ['ABC'])

    def test_no_membership_is_not_normal_or_false(self):
        sources = {"directory-HNX": payload([stock()]), "regulatory-HNX": payload()}
        row = build_rows(sources, {}, now=NOW)[0]
        self.assertIsNone(row["warning"])
        self.assertIsNone(row["suspension"])
        self.assertFalse(row["normal_reported"])
        self.assertFalse(row["all_status_dimensions_verified"])

    def test_old_success_is_not_used_as_current(self):
        old = payload([stock(status_label="Cảnh báo")], hours=25)
        sources = {"directory-HNX": payload([stock()]), "regulatory-HNX": old}
        row = build_rows(sources, {}, now=NOW)[0]
        self.assertIsNone(row["warning"])
        self.assertIn("regulatory_list_unavailable", row["issues"])
        self.assertFalse(is_fresh(old, NOW))

    def test_multiple_statuses_and_quote_subtype_survive(self):
        sources = {"directory-HNX": payload([stock()]),
                   "regulatory-HNX": payload([stock(status_label="Cảnh báo"), stock(status_label="Kiểm soát")]),
                   "quotes-HNX": payload([stock(status_label={"admin_status": {"code": "WFR"}})])}
        row = build_rows(sources, {}, now=NOW)[0]
        self.assertTrue(row["warning"])
        self.assertTrue(row["warning_financial"])
        self.assertTrue(row["control"])
        self.assertEqual(len(row["regulatory_records"]), 2)

    def test_normal_vs_adverse_is_visible_conflict(self):
        sources = {"directory-HNX": payload([stock()]),
                   "regulatory-HNX": payload([stock(status_label="Cảnh báo")]),
                   "quotes-HNX": payload([stock(status_label={"admin_status": {"code": "NRM"}})])}
        row = build_rows(sources, {}, now=NOW)[0]
        self.assertEqual(row["quality"], "conflict")
        self.assertIsNone(row["warning"])
        self.assertTrue(row["observed_flags"]["warning"])

    def test_inactive_security_not_dropped_without_directory(self):
        sources = {"directory-UPCOM": payload(),
                   "regulatory-UPCOM": payload([stock("XYZ", "UPCOM", status_label="Đình chỉ giao dịch")])}
        # Explicitly requested symbols remain present even if a directory drops
        # them; default source-only rows are exported separately for review.
        rows = build_rows(sources, {}, {("UPCOM", "XYZ")}, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["suspension"])
        self.assertIn("not_in_current_directory", rows[0]["issues"])

    def test_future_effective_notice_kept_separate(self):
        sources = {"directory-HOSE": payload([stock(market="HOSE")]),
                   "regulatory-HOSE": payload([stock(market="HOSE", status_label="Cảnh báo", effective_at="2026-10-26T00:00:00+07:00")])}
        row = build_rows(sources, {}, now=NOW)[0]
        self.assertIsNone(row["warning"])
        self.assertEqual(len(row["pending_records"]), 1)

    def test_explicit_pool_missing_symbol_does_not_disappear(self):
        rows = build_rows({}, {}, {("HOSE", "ZZZ")}, NOW)
        self.assertEqual(rows[0]["symbol"], "ZZZ")
        self.assertIsNone(rows[0]["control"])
        self.assertIn("directory_unavailable", rows[0]["issues"])

    def test_alternative_halt_types_do_not_become_two_flags(self):
        tags = label_tags("CK thuộc diện tạm ngừng/đình chỉ giao dịch")
        self.assertEqual(tags, {"halt_unspecified"})

    def test_profile_identity_and_required_statuses(self):
        html = '<input id="StockCode" value="ABC"><input id="MarketCode" value="UC">'
        for label, value in [("Trạng thái kiểm soát", "Hạn chế giao dịch"), ("Trạng thái giao dịch", "Hoạt động")]:
            html += f'<div class="dktimkiem_row"><div class="dktimkiem_cell_title">{label}</div><div class="dktimkiem_cell_content">{value}</div></div>'
        row = parse_profile(html, "UPCOM", "ABC", "https://example.org")
        self.assertEqual(row["trading_label"], "Hoạt động")
        with self.assertRaises(FetchError):
            parse_profile(html, "UPCOM", "OTHER", "https://example.org")
        with self.assertRaises(FetchError):
            parse_profile(html, "HNX", "ABC", "https://example.org")


if __name__ == "__main__":
    unittest.main()
