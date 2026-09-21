"""Read stock discussions via a user-authorized HTTP session, without OpenCLI."""
import os
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests


class SessionRequiredError(RuntimeError):
    pass


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('p', 'br', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(html):
    parser = TextParser()
    parser.feed(str(html or ''))
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())


def read_json(session, url, params):
    response = session.get(url, params=params, timeout=20)
    if response.status_code in (401, 403, 429) or 'json' not in response.headers.get('Content-Type', '').lower():
        raise SessionRequiredError('雪球需要有效登录会话或人工完成验证；已停止请求')
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get('error_code') not in (None, 0, '0') or data.get('error'):
        raise SessionRequiredError('雪球会话不可用；已停止请求')
    return data


def fetch_market_hotstocks(cfg):
    """Fetch independent HK/US 24h lists; never silently substitute NewsNow."""
    limit = min(5, max(1, int(cfg.get('top_per_market', 5))))
    stocks = []
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://xueqiu.com/'})
        session.get('https://xueqiu.com/hq', timeout=20).raise_for_status()
        for market in ('HK', 'US'):
            time.sleep(3)
            data = read_json(session, 'https://stock.xueqiu.com/v5/stock/screener/quote/list.json',
                             {'market': market, 'type': 'hot_24h', 'order_by': 'value',
                              'order': 'desc', 'page': 1, 'size': limit})
            candidates = (data.get('data') or {}).get('list')
            if not isinstance(candidates, list) or not candidates:
                raise ValueError(f'{market} 24h hot list unavailable')
            for rank, item in enumerate(candidates[:limit], 1):
                stocks.append({'symbol': item['symbol'], 'name': item.get('name', ''),
                               'market': market, 'stock_rank': rank, 'heat': item.get('value')})
    return stocks


def fetch_discussions(cfg):
    transport = cfg.get('transport', 'http')
    if transport not in ('http', 'browser'):
        raise ValueError('雪球 transport 只能为 http 或 browser')
    cookie = os.environ.get('XUEQIU_COOKIE', '')
    if transport == 'http' and cfg.get('cookie_file'):
        cookie = Path(cfg['cookie_file']).expanduser().read_text().strip()
    now = datetime.now(timezone.utc)
    window = int(cfg.get('window_hours', 48))
    cutoff = now - timedelta(hours=min(168, max(1, window))) if window else None
    selected = cfg.get('symbols', [])
    stock_ranks = fetch_market_hotstocks(cfg) if not selected and cfg.get('selection') == 'hk_us_24h' else []
    if stock_ranks:
        selected = [stock['symbol'] for stock in stock_ranks]
    sort = cfg.get('sort', 'time')
    if sort not in ('time', 'reply'):
        raise ValueError('雪球 sort 只能为 time 或 reply')
    per_stock = min(10, max(1, int(cfg.get('per_stock', 5))))
    if transport == 'browser':
        from .xueqiu_browser import BrowserSession
        session_context = BrowserSession(cfg)
    else:
        session_context = requests.Session()
    with session_context as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://xueqiu.com/',
                                'Accept': 'application/json, text/plain, */*', 'X-Requested-With': 'XMLHttpRequest'})
        if transport == 'browser':
            pass  # Login stays in the dedicated browser profile, not a Cookie header.
        elif cookie:
            session.headers['Cookie'] = cookie
        else:
            session.get('https://xueqiu.com/hq', timeout=20).raise_for_status()
        if not selected:
            response = requests.get('https://newsnow.busiyi.world/api/s', params={'id': 'xueqiu-hotstock', 'latest': ''}, timeout=20)
            response.raise_for_status()
            data = response.json()
            if data.get('status') not in ('success', 'cache'):
                raise ValueError('NewsNow stock list unavailable')
            selected = [str(row.get('url', '')).rstrip('/').split('/')[-1].upper() for row in data.get('items', [])]
        symbols = list(dict.fromkeys(str(s).upper() for s in selected if re.fullmatch(r'(?:\d{5}|[A-Za-z]{1,6}(?:[.-][A-Za-z])?)', str(s))))
        symbols = symbols[:10 if stock_ranks else min(5, max(1, int(cfg.get('top_stocks', 3))))]
        rows, failures, missing, requests_made = {}, [], 0, 0
        attempted, counts = [], {}
        for symbol in symbols:
            attempted.append(symbol)
            counts[symbol] = 0
            try:
                time.sleep(3)
                data = read_json(session, 'https://xueqiu.com/query/v1/symbol/search/status',
                                 {'symbol': symbol, 'count': per_stock, 'page': 1, 'sort': sort, 'source': 'user'})
                items = data.get('list')
                if not isinstance(items, list):
                    raise ValueError('Unexpected discussion list schema')
                for post_rank, item in enumerate(items[:per_stock], 1):
                    post_id = str(item.get('id', ''))
                    if not post_id.isdigit():
                        continue
                    # description is often a truncated excerpt: never label it as body.
                    if not item.get('text') or item.get('is_long_text'):
                        if requests_made >= min(30, len(symbols) * per_stock):
                            missing += 1
                            continue
                        time.sleep(3)
                        if transport == 'browser':
                            detail = {'text': session.post_body((item.get('user') or {}).get('id', ''), post_id)}
                        else:
                            detail = read_json(session, 'https://xueqiu.com/statuses/show.json', {'id': post_id})
                        requests_made += 1
                        item = {**item, **detail}
                    body = plain_text(item.get('text'))
                    if not body:
                        missing += 1
                        continue
                    timestamp = float(item.get('created_at') or 0) / 1000
                    published = datetime.fromtimestamp(timestamp, timezone.utc)
                    if published > now or (cutoff is not None and published < cutoff):
                        continue
                    user = item.get('user') or {}
                    user_id = str(user.get('id', ''))
                    if not user_id.isdigit():
                        continue
                    url = f'https://xueqiu.com/{user_id}/{post_id}'
                    counts[symbol] += 1
                    membership = {'symbol': symbol, 'post_rank': post_rank}
                    if url in rows:
                        rows[url]['stock_memberships'].append(membership)
                        continue
                    title = plain_text(item.get('title')) or body.splitlines()[0][:90]
                    rows[url] = {'title': f'{title} · 雪球讨论 {post_id}', 'url': url, 'content': body,
                                 'author': str(user.get('screen_name', '')), 'published_at': published.isoformat(),
                                 'symbol': symbol, 'stock_memberships': [membership],
                                 'discussion_sort': sort, 'content_kind': 'discussion_body',
                                 'likes': int(item.get('fav_count') or 0), 'replies': int(item.get('reply_count') or 0),
                                 'retweets': int(item.get('retweet_count') or 0)}
            except (SessionRequiredError, requests.RequestException) as exc:
                failures.append({'symbol': symbol, 'error': type(exc).__name__})
                break  # Do not retry login, rate-limit or challenge failures.
        items = sorted(rows.values(), key=lambda item: item['published_at'], reverse=True)
        for rank, row in enumerate(items, 1):
            row['rank'] = rank
        unqueried = [s for s in symbols if s not in attempted]
        return items, {'symbols': symbols, 'stock_ranks': stock_ranks, 'discussion_sort': sort,
                       'per_stock_target': per_stock, 'collected_per_stock': counts,
                       'unqueried_symbols': unqueried, 'failed_queries': failures, 'missing_body': missing,
                       'shortfalls': {s: per_stock - n for s, n in counts.items() if n < per_stock},
                       'partial': bool(failures or missing or unqueried),
                       'body_count': len(items), 'transport': transport}
