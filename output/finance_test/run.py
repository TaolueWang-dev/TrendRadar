"""Replay a local news snapshot through the real financial AI pipeline; no notifications."""
import os
import sys
import json
import sqlite3
from pathlib import Path
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from trendradar.core.loader import load_config
from trendradar.__main__ import NewsAnalyzer
import trendradar.ai.client as client_module

BASE = Path(__file__).resolve().parent
original_completion = client_module.completion
call_index = 0
def observed_completion(**kwargs):
    global call_index
    kwargs['extra_body'] = {**kwargs.get('extra_body', {}), 'thinking': {'type': 'disabled'}}
    response = original_completion(**kwargs)
    call_index += 1
    choice = response.choices[0]
    (BASE / f'api_response_{call_index}.json').write_text(json.dumps({
        'model': response.model, 'finish_reason': choice.finish_reason,
        'content': choice.message.content,
        'usage': response.usage.model_dump() if response.usage else None,
    }, ensure_ascii=False, indent=2))
    if choice.finish_reason == 'length' or not choice.message.content:
        raise RuntimeError('Incomplete AI response; refusing to treat it as no matches')
    return response
client_module.completion = observed_completion
os.chdir(BASE)
if not Path('config').exists():
    Path('config').symlink_to(ROOT / 'config', target_is_directory=True)
cfg = load_config(str(ROOT / 'config/config.yaml'))
cfg['ENABLE_NOTIFICATION'] = False
cfg['FILTER']['METHOD'] = 'ai'
cfg['AI_FILTER']['INTERESTS_FILE'] = 'finance_test.txt'
cfg['AI_ANALYSIS']['ENABLED'] = True
cfg['AI_ANALYSIS']['INCLUDE_STANDALONE'] = False
cfg['AI_ANALYSIS']['INCLUDE_RSS'] = False
cfg['AI_TRANSLATION']['ENABLED'] = False
cfg['RSS']['ENABLED'] = False
cfg['SCHEDULE']['enabled'] = False
cfg['REPORT_MODE'] = 'current'
cfg['DISPLAY']['REGIONS']['STANDALONE'] = False
cfg['DISPLAY']['STANDALONE']['PLATFORMS'] = []
cfg['DISPLAY']['STANDALONE']['RSS_FEEDS'] = []
cfg['STORAGE']['BACKEND'] = 'local'
cfg['STORAGE']['LOCAL']['DATA_DIR'] = str(BASE / 'output')
cfg['STORAGE']['LOCAL']['RETENTION_DAYS'] = 0
cfg['STORAGE']['PULL']['ENABLED'] = False
cfg['DEBUG'] = False

source = ROOT / 'output/news/2026-09-20.db'
dest = BASE / 'output/news' / source.name
dest.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as original:
    with sqlite3.connect(dest) as copied:
        original.backup(copied)

class TestAnalyzer(NewsAnalyzer):
    def _should_open_browser(self):
        return False

    def _run_analysis_pipeline(self, *args, **kwargs):
        result = super()._run_analysis_pipeline(*args, **kwargs)
        stats, html, analysis, *_ = result
        (BASE / 'result.json').write_text(json.dumps({
            'sample': str(source), 'stats': stats, 'html': html,
            'analysis': asdict(analysis) if analysis else None,
        }, ensure_ascii=False, indent=2))
        return result

analyzer = TestAnalyzer(config=cfg)
# Fail explicitly instead of accepting the production keyword fallback.
original_filter = analyzer.ctx.run_ai_filter
def checked_filter(*args, **kwargs):
    result = original_filter(*args, **kwargs)
    if not result or not result.success:
        raise RuntimeError('Financial AI filtering failed; no keyword fallback accepted')
    (BASE / 'filter_result.json').write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return result
analyzer.ctx.run_ai_filter = checked_filter
with sqlite3.connect(dest) as db:
    names = dict(db.execute('SELECT id,name FROM platforms'))
    results = {}
    for title, platform, rank, url, mobile in db.execute('SELECT title,platform_id,rank,url,mobile_url FROM news_items'):
        results.setdefault(platform, {})[title] = {'ranks': [rank], 'url': url, 'mobileUrl': mobile}
print('TEST: 2026-09-20 stored snapshot; financial prompt; notifications disabled', flush=True)
try:
    report = analyzer._execute_mode_strategy(analyzer._get_mode_strategy(), results, names, [])
    print('TEST_REPORT:', report, flush=True)
finally:
    analyzer.storage_manager.cleanup()
