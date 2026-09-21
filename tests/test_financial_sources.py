import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

from trendradar.crawler.financial import FinancialFetcher, financial_platforms


class FinancialTests(unittest.TestCase):
    def test_main_merges_financial_sources_without_sending_them_to_newsnow(self):
        from trendradar.__main__ import NewsAnalyzer
        analyzer = object.__new__(NewsAnalyzer)
        ctx = MagicMock()
        ctx.platforms = [{'id': 'normal', 'name': '常规'},
                         {'id': 'finance-ths', 'provider': 'financial'}]
        analyzer.ctx = ctx
        analyzer.storage_manager = MagicMock()
        analyzer.request_interval = 0
        analyzer.data_fetcher = MagicMock()
        analyzer.data_fetcher.crawl_websites.return_value = ({'normal': {}}, {'normal': '常规'}, [])
        with patch('trendradar.crawler.financial.FinancialFetcher') as finance, \
             patch('trendradar.__main__.convert_crawl_results_to_news_data') as convert:
            finance.return_value.crawl.return_value = ({'finance-ths': {}}, {'finance-ths': '同花顺'}, ['finance-xueqiu'])
            results, names, failed = analyzer._crawl_data()
        self.assertEqual(analyzer.data_fetcher.crawl_websites.call_args.args[0], [('normal', '常规')])
        self.assertEqual(set(results), {'normal', 'finance-ths'})
        self.assertEqual(failed, ['finance-xueqiu'])
        self.assertEqual(convert.call_args.args[0], results)

    def test_disabled_by_default(self):
        self.assertEqual(financial_platforms({}), [])

    def test_failure_isolated_and_rank_preserved(self):
        fetcher = FinancialFetcher({k: {"enabled": True} for k in ("ths", "xueqiu", "dongcai")})
        with patch.object(fetcher, 'fetch_ths', return_value=[dict(title='腾讯', rank=9, url='https://example.com')]), \
             patch.object(fetcher, 'fetch_xueqiu', side_effect=TimeoutError), \
             patch.object(fetcher, 'fetch_dongcai', return_value=[]):
            results, names, failures = fetcher.crawl()
        self.assertEqual(results['finance-ths']['腾讯']['ranks'], [9])
        self.assertEqual(failures, ['finance-xueqiu', 'finance-dongcai-hotnews'])
        self.assertEqual(len(names), 3)

    def test_xueqiu_market_filter_and_stable_title(self):
        sample = [dict(symbol='SH600000', name='浦发银行', rank=1),
                  dict(symbol='00700', name='腾讯控股', rank=7, heat=99)]
        fetcher = FinancialFetcher({})
        with patch('trendradar.crawler.financial.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(sample))) as run:
            rows = fetcher.fetch_xueqiu({'limit': 100})
            self.assertEqual(run.call_args.args[0][-1], '50')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['rank'], 7)
        self.assertNotIn('99', rows[0]['title'])
        self.assertEqual(rows[0]['url'], 'https://xueqiu.com/S/00700')

    def test_eastmoney_scoped_parsing_and_dedup(self):
        from trendradar.crawler.financial import EastmoneyHotNewsParser
        parser = EastmoneyHotNewsParser()
        parser.feed('''<a href="https://finance.eastmoney.com/a/1.html">广告</a>
        <div class="Wydj clearfix"><div><h2>网友点击排行榜</h2></div><div><ul>
        <li><span class="no">2</span><a href="/a/2.html">新闻<b>二</b> &amp; 金融</a></li>
        <li><span class="no">1</span><a href="/a/1.html">新闻一</a></li>
        <li><span class="no">3</span><a href="/a/1.html">重复</a></li>
        <li><span class="no">4</span><a href="https://evil.example/a/4.html">外链</a></li>
        </ul></div></div><a href="/a/5.html">其他新闻</a>''')
        rows = parser.results(10)
        self.assertEqual([r['rank'] for r in rows], [1, 2])
        self.assertEqual(rows[1]['title'], '新闻二 & 金融')
        self.assertEqual(len(parser.results(1)), 1)

    def test_eastmoney_changed_page_fails(self):
        from trendradar.crawler.financial import EastmoneyHotNewsParser
        for html in ['<html>login</html>', '<div class="Wydj"><h2>网友点击排行榜</h2></div>']:
            parser = EastmoneyHotNewsParser()
            parser.feed(html)
            with self.assertRaises(ValueError):
                parser.results(10)

    def test_eastmoney_uses_http_without_subprocess(self):
        response = MagicMock()
        response.text = '<div class="Wydj"><h2>网友点击排行榜</h2><li><span class="no">1</span><a href="/a/123.html">新闻</a></li></div>'
        with patch('trendradar.crawler.financial.requests.get', return_value=response) as get, \
             patch('trendradar.crawler.financial.subprocess.run') as run:
            rows = FinancialFetcher({}).fetch_dongcai({})
        self.assertEqual(len(rows), 1)
        get.assert_called_once()
        run.assert_not_called()
        self.assertEqual(response.encoding, 'utf-8')


if __name__ == '__main__':
    unittest.main()
