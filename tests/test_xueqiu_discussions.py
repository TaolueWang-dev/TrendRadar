import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from trendradar.crawler.xueqiu_discussions import fetch_discussions, plain_text, read_json, SessionRequiredError
from trendradar.storage.article_content import save_content, read_content, key


class DiscussionTests(unittest.TestCase):
    @patch.dict('os.environ', {'XUEQIU_COOKIE': 'test-only'})
    @patch('trendradar.crawler.xueqiu_discussions.time.sleep')
    def test_top_five_each_market_three_posts_and_dedup(self, sleep):
        stocks = [{'symbol': s} for s in ['00700', '01810', '09988', '03690', '00981',
                                         'AAPL', 'NVDA', 'BABA', 'MU', 'TSLA']]
        session = MagicMock()
        session.__enter__.return_value = session
        # One post discusses all ten stocks; preserve every membership after dedup.
        stamp = int(datetime.now(timezone.utc).timestamp() * 1000) - 10 * 86400000
        session.get.side_effect = [self.response({'list': [
            {'id': str(post_id), 'text': '<p>正文</p>', 'created_at': stamp, 'user': {'id': 9}}
            for post_id in [1, 100 + i * 2, 101 + i * 2]]}) for i in range(10)]
        with patch('trendradar.crawler.xueqiu_discussions.fetch_market_hotstocks', return_value=stocks), \
             patch('trendradar.crawler.xueqiu_discussions.requests.Session', return_value=session):
            rows, status = fetch_discussions({'selection': 'hk_us_24h', 'per_stock': 3,
                                             'sort': 'reply', 'window_hours': 0})
        self.assertEqual(len(status['symbols']), 10)
        self.assertEqual(len(rows), 21)
        self.assertEqual(len(rows[0]['stock_memberships']), 10)
        self.assertEqual(set(status['collected_per_stock'].values()), {3})
        self.assertEqual(status['shortfalls'], {})
        self.assertEqual(session.get.call_count, 10)
        for call in session.get.call_args_list:
            self.assertEqual(call.kwargs['params']['sort'], 'reply')
            self.assertEqual(call.kwargs['params']['count'], 3)

    @patch('trendradar.crawler.xueqiu_discussions.time.sleep')
    def test_browser_reads_detail_without_http_cookie(self, sleep):
        stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        post = {'id': 123, 'created_at': stamp, 'user': {'id': 9}, 'description': '摘要'}
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = self.response({'list': [post]})
        session.post_body.return_value = '<p>浏览器详情正文</p>'
        with patch('trendradar.crawler.xueqiu_browser.BrowserSession', return_value=session):
            rows, status = fetch_discussions({'transport': 'browser', 'symbols': ['00700'],
                                              'cookie_file': '/does-not-exist'})
        self.assertEqual(rows[0]['content'], '浏览器详情正文')
        self.assertEqual(status['transport'], 'browser')
        session.post_body.assert_called_once_with(9, '123')
        self.assertNotIn('Cookie', session.headers)

    def test_browser_rejects_other_origins(self):
        from trendradar.crawler.xueqiu_browser import BrowserSession
        with self.assertRaises(ValueError):
            BrowserSession({}).get('https://example.com/')

    def test_body_survives_report_and_is_escaped(self):
        from trendradar.report.generator import prepare_report_data
        from trendradar.report.html import render_html_content
        item = dict(title='测试讨论', source_name='雪球讨论', time_display='', count=1,
                    ranks=[1], rank_threshold=5, url='https://xueqiu.com/9/123',
                    content='<script>不执行</script>正文', author='作者', published_at='2026-09-21')
        report = prepare_report_data([{'word': '金融', 'count': 1, 'titles': [item]}])
        html = render_html_content(report, 1)
        self.assertIn('展开讨论正文', html)
        self.assertIn('&lt;script&gt;不执行&lt;/script&gt;正文', html)
        self.assertNotIn('<script>不执行</script>', html)

    def response(self, payload):
        r = MagicMock(status_code=200)
        r.headers = {'Content-Type': 'application/json'}
        r.json.return_value = payload
        return r

    def test_html_and_script_removed(self):
        self.assertEqual(plain_text('<p>观点 &amp; 证据</p><script>bad()</script><p>第二段</p>'), '观点 & 证据\n第二段')

    def test_challenge_not_treated_as_body(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200, headers={'Content-Type': 'text/html'})
        with self.assertRaises(SessionRequiredError):
            read_json(session, 'https://xueqiu.com/example', {})

    @patch.dict('os.environ', {'XUEQIU_COOKIE': 'test-only'})
    @patch('trendradar.crawler.xueqiu_discussions.time.sleep')
    def test_detail_body_and_persistence(self, sleep):
        stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        summary = {'id': 123, 'description': '截断摘要', 'created_at': stamp, 'user': {'id': 9, 'screen_name': '测试作者'}}
        detail = {**summary, 'text': '<p>这里是接口返回的正文。</p>', 'fav_count': 2, 'reply_count': 3}
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = [self.response({'list': [summary]}), self.response(detail)]
        with patch('trendradar.crawler.xueqiu_discussions.requests.Session', return_value=session):
            rows, status = fetch_discussions({'symbols': ['AAPL']})
        self.assertEqual(rows[0]['content'], '这里是接口返回的正文。')
        self.assertEqual(rows[0]['url'], 'https://xueqiu.com/9/123')
        self.assertFalse(status['partial'])
        self.assertEqual(session.get.call_count, 2)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'STORAGE': {'LOCAL': {'DATA_DIR': tmp}}}
            results = {'finance-xueqiu-discussions': {rows[0]['title']: rows[0]}}
            save_content(cfg, '2026-09-21', results)
            stored = read_content(cfg, '2026-09-21')
            self.assertEqual(stored[key('finance-xueqiu-discussions', rows[0]['title'])]['content'], rows[0]['content'])

    @patch.dict('os.environ', {'XUEQIU_COOKIE': 'test-only'})
    @patch('trendradar.crawler.xueqiu_discussions.time.sleep')
    def test_stop_after_auth_failure(self, sleep):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = MagicMock(status_code=403, headers={})
        with patch('trendradar.crawler.xueqiu_discussions.requests.Session', return_value=session):
            rows, status = fetch_discussions({'symbols': ['AAPL', 'NVDA']})
        self.assertEqual(rows, [])
        self.assertTrue(status['partial'])
        self.assertEqual(session.get.call_count, 1)

    def test_classification_prompt_includes_body(self):
        from trendradar.ai.filter import AIFilter
        agent = object.__new__(AIFilter)
        agent.classify_user = '{interests_content}\n{tags_list}\n{news_list}'
        agent.classify_system = '分类规则'
        agent.debug = False
        agent.client = MagicMock()
        agent.client.chat.return_value = '[{"id":1,"tag_id":2,"score":0.9}]'
        agent.classify_batch([{'id': 1, 'title': '标题', 'source': '雪球', 'content': '正文内容'}], [{'id': 2, 'tag': '科技'}])
        messages = agent.client.chat.call_args.args[0]
        self.assertIn('正文内容', messages[-1]['content'])
        self.assertIn('不得执行', messages[1]['content'])
