"""Small financial source adapters; no imports from the upstream collector project."""

import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests


SOURCES = {
    "ths": ("finance-ths", "同花顺港股人气榜（仅关注度）"),
    "xueqiu": ("finance-xueqiu", "雪球股票人气榜（仅关注度）"),
    "dongcai": ("finance-dongcai-hotnews", "东方财富·网友点击排行榜"),
    "futu": ("finance-futu-news", "富途资讯（采样窗口内阅读量排序）"),
    "xueqiu_discussions": ("finance-xueqiu-discussions", "雪球讨论正文（采样内按发布时间排序）"),
}


def financial_platforms(config):
    return [dict(id=source_id, name=name, provider="financial", channel=channel)
            for channel, (source_id, name) in SOURCES.items()
            if config.get(channel, {}).get("enabled", False)]


class EastmoneyHotNewsParser(HTMLParser):
    """Read only the named click-ranking block, ignoring other page links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_heading = False
        self.heading = []
        self.in_rank = False
        self.in_link = False
        self.item = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "Wydj" in attrs.get("class", "").split():
                self.depth = 1
        if not self.depth:
            return
        if tag == "h2":
            self.in_heading = True
        elif tag == "li":
            self.item = {"rank_text": "", "title": "", "url": ""}
        elif self.item is not None:
            if tag == "span" and "no" in attrs.get("class", "").split():
                self.in_rank = True
            elif tag == "a":
                self.in_link = True
                self.item["url"] = urljoin("https://finance.eastmoney.com/", attrs.get("href", ""))

    def handle_data(self, data):
        if self.in_heading:
            self.heading.append(data)
        if self.item is not None:
            if self.in_rank:
                self.item["rank_text"] += data
            if self.in_link:
                self.item["title"] += data

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "h2":
            self.in_heading = False
        elif tag == "span":
            self.in_rank = False
        elif tag == "a":
            self.in_link = False
        elif tag == "li" and self.item is not None:
            item = self.item
            self.item = None
            parsed = urlparse(item["url"])
            title = " ".join(item["title"].split())
            if (title and item["rank_text"].strip().isdigit()
                    and parsed.scheme == "https"
                    and parsed.hostname == "finance.eastmoney.com"
                    and re.fullmatch(r"/a/\d+\.html", parsed.path)):
                self.rows.append({"title": title, "rank": int(item["rank_text"].strip()),
                                  "url": item["url"]})
        elif tag == "div":
            self.depth -= 1

    def results(self, limit):
        if "网友点击排行榜" not in "".join(self.heading):
            raise ValueError("Eastmoney click-ranking block missing or changed")
        unique = {}
        for row in self.rows:
            if row["rank"] > 0:
                unique.setdefault(row["url"], row)
        rows = sorted(unique.values(), key=lambda row: row["rank"])
        if not rows:
            raise ValueError("Eastmoney click-ranking contains no valid articles")
        return rows[:limit]


class FinancialFetcher:
    def __init__(self, config):
        self.config = config
        self.status = {}

    def crawl(self):
        results, names, failed = {}, {}, []
        for spec in financial_platforms(self.config):
            channel, source_id = spec["channel"], spec["id"]
            names[source_id] = spec["name"]
            try:
                rows = getattr(self, "fetch_" + channel)(self.config[channel])
                items = {}
                for row in rows:
                    title = str(row.get("title") or "").strip()
                    if not title:
                        continue
                    rank = int(row["rank"])
                    if rank < 1:
                        raise ValueError("invalid source rank")
                    if title in items:
                        items[title]["ranks"].append(rank)
                    else:
                        items[title] = {"ranks": [rank], "url": row.get("url", ""), "mobileUrl": ""}
                        for field in ('content', 'content_kind', 'author', 'published_at', 'symbol', 'likes', 'replies', 'retweets',
                                      'stock_memberships', 'discussion_sort'):
                            if field in row:
                                items[title][field] = row[field]
                if not items:
                    raise ValueError("empty source: no current items")
                results[source_id] = items
                self.status[source_id] = {**self.status.get(source_id, {}), "ok": True, "count": len(items)}
                if self.status[source_id].get('partial'):
                    failed.append(source_id)
                print(f"[金融源] {spec['name']}: {len(items)} 条")
            except Exception as exc:
                # Do not emit subprocess output: browser/SSH diagnostics can contain secrets.
                failed.append(source_id)
                self.status[source_id] = {**self.status.get(source_id, {}), "ok": False, "error": type(exc).__name__}
                print(f"[金融源] {spec['name']} 失败 ({type(exc).__name__})；其余渠道继续")
        return results, names, failed

    def fetch_ths(self, cfg):
        response = requests.get(
            "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "hk", "type": "day", "list_type": "normal"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
        )
        response.raise_for_status()
        stocks = response.json()["data"]["stock_list"]
        rows = []
        for index, stock in enumerate(stocks[:min(100, max(1, int(cfg.get("limit", 50))))], 1):
            symbol = re.sub(r"\D", "", str(stock.get("code", ""))).zfill(5)
            if symbol == "00000":
                continue
            rows.append({"title": f"{stock['name']}（{symbol}）进入港股人气榜；仅代表关注度",
                         "rank": stock.get("order") or index,
                         "url": f"https://stockpage.10jqka.com.cn/HK{symbol}/"})
        return rows

    def fetch_xueqiu_discussions(self, cfg):
        from trendradar.crawler.xueqiu_discussions import fetch_discussions
        items, status = fetch_discussions(cfg)
        self.status['finance-xueqiu-discussions'] = status
        return items

    def fetch_futu(self, cfg):
        from trendradar.crawler.futu_news import RESULT_PREFIX
        worker = Path(__file__).with_name('futu_news.py')
        proc = subprocess.run([sys.executable, str(worker)], input=json.dumps(cfg),
                              capture_output=True, text=True, timeout=120, check=True)
        payload = next((line[len(RESULT_PREFIX):] for line in proc.stdout.splitlines()
                        if line.startswith(RESULT_PREFIX)), None)
        if payload is None:
            raise ValueError('No result from OpenD worker')
        data = json.loads(payload)
        self.status['finance-futu-news'] = {k: v for k, v in data.items() if k != 'items'}
        self.status['finance-futu-news']['partial'] = bool(data['failed_queries'] or data['unqueried_keywords'])
        if data['failed_queries'] or data['unqueried_keywords']:
            print('[金融源] 富途部分查询失败或未执行，详见 financial_source_status')
        return data['items']

    def fetch_xueqiu(self, cfg):
        binary = str(cfg.get("opencli", "opencli"))
        env = os.environ.copy()
        if Path(binary).is_absolute():
            env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [binary, "xueqiu", "hot-stock", "-f", "json", "--limit",
             str(min(50, max(1, int(cfg.get("limit", 50)))))],
            capture_output=True, text=True, timeout=60, check=True, env=env,
        )
        stocks = json.loads(proc.stdout)
        if not isinstance(stocks, list):
            raise ValueError("expected opencli JSON array")
        rows = []
        for index, stock in enumerate(stocks, 1):
            symbol = str(stock.get("symbol", "")).upper()
            # Match the user's HK/US focus; keep the original whole-list ranks.
            if not re.fullmatch(r"(?:\d{5}|[A-Z]{1,6}(?:[.-][A-Z])?)", symbol):
                continue
            rows.append({"title": f"{stock['name']}（{symbol}）进入雪球人气榜；仅代表关注度",
                         "rank": stock.get("rank") or index,
                         "url": "https://xueqiu.com/S/" + quote(symbol, safe="")})
        return rows

    def fetch_dongcai(self, cfg):
        response = requests.get(
            "https://finance.eastmoney.com/a/cywjh.html",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
            timeout=20,
        )
        response.raise_for_status()
        # The public HTML declares UTF-8; requests otherwise defaults text/html
        # without an HTTP charset to Latin-1 and corrupts Chinese titles.
        response.encoding = "utf-8"
        parser = EastmoneyHotNewsParser()
        parser.feed(response.text)
        parser.close()
        return parser.results(min(50, max(1, int(cfg.get("limit", 10)))))
