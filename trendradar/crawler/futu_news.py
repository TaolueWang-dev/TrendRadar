"""Bounded, read-only OpenD news collection in a killable worker process."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
RESULT_PREFIX = 'TREND RADAR FUTU RESULT:'


def records(data):
    if isinstance(data, tuple):
        data = next((part for part in data if hasattr(part, 'to_dict')), None)
    if data is None or not hasattr(data, 'to_dict'):
        raise ValueError('Unexpected OpenD response format')
    return data.to_dict('records')


def published(value, now):
    text = str(value).strip()
    try:
        if text.replace('.', '', 1).isdigit():
            ts = float(text)
            return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, HKT)
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return dt.replace(tzinfo=HKT) if dt.tzinfo is None else dt.astimezone(HKT)
    except (ValueError, OverflowError, OSError):
        for fmt in ('%Y/%m/%d %H:%M', '%Y/%m/%d'):
            try:
                dt = datetime.strptime(f'{now.year}/{text}', fmt).replace(tzinfo=HKT)
                return dt.replace(year=now.year - 1) if dt > now else dt
            except ValueError:
                pass
    return None


def collect(ctx, ft, cfg, now=None):
    now = now or datetime.now(HKT)
    start = now - timedelta(hours=min(168, max(1, int(cfg.get('window_hours', 48)))) )
    keywords = list(dict.fromkeys(str(k).strip() for k in cfg.get('keywords', []) if str(k).strip()))[:12]
    failures = []
    top = min(5, max(0, int(cfg.get('top_stocks_per_market', 3))))
    if top:
        for market in (ft.Market.HK, ft.Market.US):
            ret, data = ctx.get_hot_list(market, ft.HotListSortField.AVERAGE_HEAT, ft.RankSortDir.DESCENDING, top)
            if ret != ft.RET_OK:
                failures.append(f'hot_list:{market}')
                continue
            keywords.extend(str(row['security']) for row in records(data))
            time.sleep(0.3)
    keywords = list(dict.fromkeys(keywords))[:22]
    per_keyword = min(30, max(1, int(cfg.get('per_keyword', 10))))
    unique, consecutive, attempted = {}, 0, []
    for keyword in keywords:
        attempted.append(keyword)
        ret, data = ctx.get_search_news(keyword, per_keyword)
        if ret != ft.RET_OK:
            failures.append(f'news:{keyword}')
            consecutive += 1
            if consecutive >= 3:
                break
        else:
            consecutive = 0
            for row in records(data):
                stamp = published(row.get('publish_time'), now)
                title = str(row.get('title') or '').strip()
                url = str(row.get('url') or '').strip()
                if not stamp or not start <= stamp <= now or not title:
                    continue
                if not url.startswith(('https://', 'http://')):
                    continue
                item = {'title': title, 'url': url, 'published_at': stamp.isoformat(),
                        'view_count': max(0, int(row.get('view_count') or 0)),
                        'publisher': str(row.get('source') or ''), 'keyword': keyword}
                if url not in unique or item['view_count'] > unique[url]['view_count']:
                    unique[url] = item
        time.sleep(0.3)
    items = sorted(unique.values(), key=lambda row: (row['view_count'], row['published_at'], row['url']), reverse=True)
    items = items[:min(100, max(1, int(cfg.get('limit', 50))))]
    for rank, row in enumerate(items, 1):
        row['rank'] = rank
    return {'items': items, 'failed_queries': failures, 'attempted_keywords': attempted,
            'unqueried_keywords': keywords[len(attempted):], 'window_start': start.isoformat()}


def main():
    import futu as ft
    cfg = json.load(sys.stdin)
    ctx = ft.OpenQuoteContext(host=cfg.get('host', '127.0.0.1'), port=int(cfg.get('port', 11111)))
    try:
        result = collect(ctx, ft, cfg)
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        ctx.close()


if __name__ == '__main__':
    main()
