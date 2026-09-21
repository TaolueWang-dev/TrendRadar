import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from trendradar.crawler.futu_news import collect, published, HKT


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        return self.rows


class FutuTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 20, 16, tzinfo=HKT)
        self.ft = SimpleNamespace(RET_OK=0)

    @patch('trendradar.crawler.futu_news.time.sleep')
    def test_dedup_window_and_rank(self, sleep):
        def row(url, hours, views):
            return dict(title=url, url='https://news.futunn.com/'+url,
                        publish_time=(self.now-timedelta(hours=hours)).isoformat(), view_count=views)
        ctx = MagicMock()
        ctx.get_search_news.side_effect = [(0, Frame([row('one', 1, 3), row('old', 80, 999), row('future', -1, 999)])),
                                          (0, Frame([row('one', 1, 5), row('two', 2, 10)]))]
        result = collect(ctx, self.ft, {'top_stocks_per_market': 0, 'keywords': ['a', 'b']}, self.now)
        self.assertEqual([r['title'] for r in result['items']], ['two', 'one'])
        self.assertEqual([r['rank'] for r in result['items']], [1, 2])
        self.assertEqual(result['items'][1]['view_count'], 5)

    @patch('trendradar.crawler.futu_news.time.sleep')
    def test_failure_circuit_breaker(self, sleep):
        ctx = MagicMock()
        ctx.get_search_news.return_value = (-1, 'failure')
        result = collect(ctx, self.ft, {'top_stocks_per_market': 0, 'keywords': ['a', 'b', 'c', 'd']}, self.now)
        self.assertEqual(ctx.get_search_news.call_count, 3)
        self.assertEqual(result['unqueried_keywords'], ['d'])
        self.assertEqual(len(result['failed_queries']), 3)

    def test_publication_formats(self):
        for value in [self.now.isoformat(), str(self.now.timestamp()), str(int(self.now.timestamp()*1000))]:
            self.assertEqual(published(value, self.now), self.now)
        now = datetime(2026, 1, 1, tzinfo=HKT)
        self.assertEqual(published('12/31', now).year, 2025)
        self.assertIsNone(published('invalid', now))
