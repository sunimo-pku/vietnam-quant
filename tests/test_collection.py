import json
from pathlib import Path
import tempfile
import unittest

from vietnam_quant.http import FetchError
from vietnam_quant.sources import collect_html_pages, hose_status
from vietnam_quant.store import Store
from vietnam_quant.audit import provider_date
from vietnam_quant.ssc import parse_search, parse_article


class FakeClient:
    def __init__(self, bodies):
        self.bodies = iter(bodies)

    def fetch(self, *args, **kwargs):
        return next(self.bodies), {"http_status": 200}


def table(indices, total):
    return '<table id="_tableDatas"><tbody>' + ''.join(f'<tr><td>{i}</td><td>ABC</td></tr>' for i in indices) + f'</tbody></table><div id="d_total_rec">Tổng số {total} bản ghi</div>'


class CollectionTests(unittest.TestCase):
    def test_archive_search_does_not_hide_truncation_or_server_error(self):
        html = '<p>Tìm thấy 21 kết quả</p><div><h3><a href="/news">Article</a></h3><p>08/04/2005</p></div>'
        links, total = parse_search(html)
        self.assertEqual(total, 21)
        self.assertEqual(len(links), 1)
        with self.assertRaises(FetchError):
            parse_search('<p>Service unavailable</p>')

    def test_archive_future_body_date_is_review_flag_not_effective_date(self):
        html = '<div class="new-content">Suspension begins 11/04/2005.</div>'
        row = parse_article(html, {'title': 'Notice', 'url': 'https://ssc.gov.vn/?dDocName=ABC', 'text': '08/04/2005'})
        self.assertEqual(row['published_local'], '2005-04-08')
        self.assertTrue(row['needs_date_review'])
        self.assertNotIn('effective_at', row)

    def test_provider_midnight_uses_vietnam_date(self):
        # 2004-12-02 00:00 in Vietnam is still December 1 in UTC.
        self.assertEqual(provider_date('/Date(1101920400000)/'), '2004-12-02')
        self.assertIsNone(provider_date(None))

    def test_incomplete_second_page_is_failure(self):
        client = FakeClient([table([1, 2], 3), table([], 3)])
        with self.assertRaises(FetchError):
            collect_html_pages(client, 'https://example.org', {'size': 2}, 'page', 'size')

    def test_repeated_page_is_failure(self):
        client = FakeClient([table([1, 2], 4), table([1, 2], 4)])
        with self.assertRaises(FetchError):
            collect_html_pages(client, 'https://example.org', {'size': 2}, 'page', 'size')

    def test_server_error_page_does_not_mean_zero_records(self):
        client = FakeClient(['<html>Temporarily unavailable</html>'])
        with self.assertRaises(FetchError):
            collect_html_pages(client, 'https://example.org', {'size': 2}, 'page', 'size')

    def test_same_stock_can_have_multiple_hose_reasons(self):
        category = json.dumps({'success': True, 'data': [{'id': 33, 'name': 'Warning'}]})
        records = [{'securitiesId': 1, 'securitiesCode': 'ABC', 'name': 'Issuer',
                    'datePublish': 1, 'appliedDate': 1, 'reason': 'Late report'},
                   {'securitiesId': 1, 'securitiesCode': 'ABC', 'name': 'Issuer',
                    'datePublish': 2, 'appliedDate': 1, 'reason': 'Negative equity'}]
        data = json.dumps({'success': True, 'data': {'list': records, 'paging': {'totalCount': 2}}})
        rows, _ = hose_status(FakeClient([category, data]))
        self.assertEqual(len(rows), 2)
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'test.sqlite')
            self.assertEqual(store.save('HOSE', rows, [])['rows'], 2)
            self.assertEqual(store.save('HOSE', rows[::-1], [])['changes'], 0)
            store.db.close()

    def test_change_tracking_and_failure_retains_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'test.sqlite')
            r = {'market': 'HNX', 'symbol': 'ABC', 'category_id': 'Warning', 'status_label': 'Warning'}
            store.save('HNX', [r], [], '2026-10-11T01:00:00Z')
            self.assertEqual(store.save('HNX', [r], [])['changes'], 0)
            changed = {**r, 'status_label': 'Edited description'}
            self.assertEqual(store.save('HNX', [changed], [])['changes'], 1)
            self.assertEqual(store.db.execute('SELECT change_type FROM changes').fetchone()[0], 'changed')
            sid = store.db.execute('SELECT MAX(id) FROM snapshots').fetchone()[0]
            store.failure('HNX', FetchError('Page missing'))
            self.assertEqual(store.db.execute('SELECT MAX(id) FROM snapshots').fetchone()[0], sid)
            self.assertEqual(store.latest()[0]['status_label'], 'Edited description')
            self.assertIn('observed_at', store.latest()[0])
            store.db.close()

    def test_mass_disappearance_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'test.sqlite')
            rows = [{'market': 'UPCOM', 'symbol': f'X{i}', 'category_id': 'Suspended'} for i in range(20)]
            store.save('UPCOM', rows, [])
            with self.assertRaises(FetchError):
                store.save('UPCOM', [], [])
            self.assertEqual(len(store.latest()), 20)
            store.db.close()

    def test_pagination_url_change_is_not_status_change(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'test.sqlite')
            row = {'market': 'HOSE', 'symbol': 'ABC', 'category_id': '33',
                   'published_at': '2026-01-01', 'source_url': 'https://example.org?page=1'}
            store.save('HOSE', [row], [])
            result = store.save('HOSE', [{**row, 'source_url': 'https://example.org?page=2'}], [])
            self.assertEqual(result['changes'], 0)
            store.db.close()


if __name__ == '__main__':
    unittest.main()
