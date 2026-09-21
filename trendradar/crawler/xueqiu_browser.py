"""Optional, dedicated browser session for Xueqiu (no existing profile access)."""
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests


DEFAULT_PROFILE = Path.home() / '.local/share/trendradar/xueqiu-browser'


class BrowserSession:
    def __init__(self, cfg):
        self.cfg = cfg
        self.runtime = self.context = None
        self.headers = {}

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError('浏览器模式需要安装 playwright；参见 docs/financial_sources.md') from None
        profile = Path(self.cfg.get('browser_profile') or DEFAULT_PROFILE).expanduser()
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime = sync_playwright().start()
        try:
            self.context = self.runtime.chromium.launch_persistent_context(
                str(profile), channel='chrome', headless=self.cfg.get('headless', True),
            )
            self.page = self.context.new_page()
            self.page.goto('https://xueqiu.com/', wait_until='domcontentloaded', timeout=30000)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def get(self, url, params=None, timeout=20):
        if urlsplit(url).scheme != 'https' or urlsplit(url).netloc != 'xueqiu.com':
            raise ValueError('浏览器会话仅用于 xueqiu.com')
        if urlsplit(self.page.url).hostname != 'xueqiu.com':
            raise RuntimeError('雪球页面未就绪，请先正常登录')
        target = url + ('?' + urlencode(params) if params else '')
        result = self.page.evaluate('''async ({url, timeout}) => {
            const r = await fetch(url, {credentials: 'same-origin',
                signal: AbortSignal.timeout(timeout), redirect: 'error'});
            return {status: r.status, type: r.headers.get('content-type') || '',
                body: await r.text()};
        }''', {'url': target, 'timeout': timeout * 1000})
        response = requests.Response()
        response.status_code = result['status']
        response.headers['Content-Type'] = result['type']
        response._content = result['body'].encode('utf-8')
        response.encoding = 'utf-8'
        response.url = target
        return response

    def __exit__(self, *_):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.runtime:
                self.runtime.stop()

    def post_body(self, user_id, post_id):
        if not str(user_id).isdigit() or not str(post_id).isdigit():
            return ''
        from .xueqiu_discussions import SessionRequiredError
        page = self.context.new_page()
        try:
            response = page.goto(f'https://xueqiu.com/{user_id}/{post_id}',
                                 wait_until='domcontentloaded', timeout=20000)
            if response and response.status in (401, 403, 429):
                raise SessionRequiredError('雪球详情页需要有效会话或人工验证')
            body = page.locator('.article__bd__detail').first
            from playwright.sync_api import TimeoutError as BrowserTimeout
            try:
                body.wait_for(state='attached', timeout=5000)
            except BrowserTimeout:
                raise SessionRequiredError('雪球详情正文未就绪；请人工检查登录或页面验证') from None
            return body.inner_html()
        finally:
            page.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='雪球独立浏览器登录或小样本采集')
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--profile', default=str(DEFAULT_PROFILE))
    parser.add_argument('--symbol', default='00700')
    parser.add_argument('--output', default='output/xueqiu_browser_test.json')
    args = parser.parse_args()
    cfg = {'transport': 'browser', 'browser_profile': args.profile, 'symbols': [args.symbol],
           'per_stock': 2, 'headless': False}
    if args.login:
        with BrowserSession(cfg):
            input('请在打开的独立 Chrome 中登录雪球并完成页面验证，完成后回到终端按回车保存会话：')
        print('浏览器会话已保存；请继续运行小样本测试确认有效性。')
    else:
        from .xueqiu_discussions import fetch_discussions
        rows, status = fetch_discussions(cfg)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'items': rows, 'status': status}, ensure_ascii=False, indent=2))
        print(json.dumps(status, ensure_ascii=False))
        print(f'结果：{output}')
        if not rows:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
