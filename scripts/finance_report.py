"""Run the financial adapters and existing report pipeline in an isolated output directory.

Default is a local preview with no AI requests or notifications. --ai explicitly
enables the configured external AI service. --reuse reuses the saved collection.
"""
import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trendradar.core.loader import load_config
from trendradar.__main__ import NewsAnalyzer
from trendradar.storage import convert_crawl_results_to_news_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ai', action='store_true')
    parser.add_argument('--reuse', action='store_true')
    parser.add_argument('--all', action='store_true', help='Include all enabled platforms and RSS; use NewsNow for Xueqiu')
    parser.add_argument('--sources', nargs='+', choices=['ths', 'xueqiu', 'dongcai', 'futu', 'xueqiu_discussions'],
                        help='Only collect these financial channels')
    parser.add_argument('--output', default=str(ROOT / 'output/financial_channels_test'))
    args = parser.parse_args()
    if args.all and args.sources:
        parser.error('--all and --sources cannot be combined')
    base = Path(args.output).resolve()
    base.mkdir(parents=True, exist_ok=True)
    cfg = load_config(str(ROOT / 'config/config.yaml'))
    if args.sources:
        for channel, source in cfg['FINANCIAL_SOURCES'].items():
            if channel not in args.sources:
                source['enabled'] = False
    if args.all:
        if cfg['FINANCIAL_SOURCES'].get('xueqiu', {}).get('enabled'):
            cfg['FINANCIAL_SOURCES']['xueqiu']['enabled'] = False
            cfg['PLATFORMS'] = [p for p in cfg['PLATFORMS'] if p.get('channel') != 'xueqiu']
            if not any(p['id'] == 'xueqiu-hotstock' for p in cfg['PLATFORMS']):
                cfg['PLATFORMS'].append({'id': 'xueqiu-hotstock', 'name': '雪球热门股票', 'expected_domain': 'xueqiu.com'})
    else:
        cfg['PLATFORMS'] = [p for p in cfg['PLATFORMS'] if p.get('provider') == 'financial']
    if args.sources:
        cfg['PLATFORMS'] = [p for p in cfg['PLATFORMS'] if p['channel'] in args.sources]
    cfg['ENABLE_NOTIFICATION'] = False
    cfg['AI_ANALYSIS']['ENABLED'] = args.ai
    cfg['AI_ANALYSIS']['INCLUDE_STANDALONE'] = False
    cfg['AI_ANALYSIS']['INCLUDE_RSS'] = args.all
    cfg['AI_TRANSLATION']['ENABLED'] = False
    cfg['AI_FILTER']['INTERESTS_FILE'] = 'finance_test.txt'
    cfg['FILTER']['METHOD'] = 'ai' if args.ai else 'keyword'
    # The configured DeepSeek model otherwise can spend its token budget on
    # reasoning alone. This override applies only to this test invocation.
    if cfg['AI']['MODEL'].startswith('deepseek/'):
        cfg['AI']['EXTRA_PARAMS'] = {'extra_body': {'thinking': {'type': 'disabled'}}}
    if not args.all:
        cfg['RSS']['ENABLED'] = False
    cfg['SCHEDULE']['enabled'] = False
    cfg['REPORT_MODE'] = 'current'
    cfg['DISPLAY']['REGIONS']['STANDALONE'] = False
    cfg['STORAGE']['BACKEND'] = 'local'
    cfg['STORAGE']['LOCAL']['DATA_DIR'] = str(base / 'output')
    cfg['STORAGE']['LOCAL']['RETENTION_DAYS'] = 0
    cfg['STORAGE']['PULL']['ENABLED'] = False
    cfg['DEBUG'] = False
    os.chdir(base)
    if not Path('config').exists():
        Path('config').symlink_to(ROOT / 'config', target_is_directory=True)
    preview_words = base / 'preview_keywords.txt'
    preview_words.write_text('[WORD_GROUPS]\n\n[采集预览：完整标题，不代表热点判定]\n/.+/\n', encoding='utf-8')
    if not args.ai:
        os.environ['FREQUENCY_WORDS_PATH'] = str(preview_words)

    class ReportAnalyzer(NewsAnalyzer):
        def _should_open_browser(self):
            return False

        def _run_analysis_pipeline(self, *args, **kwargs):
            result = super()._run_analysis_pipeline(*args, **kwargs)
            stats, html, analysis, *_ = result
            (base / 'report_result.json').write_text(json.dumps({
                'ai_requested': args_ai, 'stats': stats, 'html': html,
                'analysis': asdict(analysis) if analysis else None,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            if args_ai and (not analysis or not analysis.success):
                raise RuntimeError('AI summary did not succeed; inspect report_result.json')
            return result

    args_ai = args.ai
    analyzer = ReportAnalyzer(config=cfg)
    if args.ai:
        original_filter = analyzer.ctx.run_ai_filter
        def checked_filter(*a, **kw):
            result = original_filter(*a, **kw)
            if not result or not result.success:
                raise RuntimeError('AI filter failed; refusing silent keyword fallback')
            (base / 'filter_result.json').write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding='utf-8')
            return result
        analyzer.ctx.run_ai_filter = checked_filter
    try:
        snapshot = base / 'collection.json'
        if args.reuse:
            data = json.loads(snapshot.read_text())
            if data['crawl_date'] != analyzer.ctx.format_date():
                raise ValueError('Snapshot is not from today; collect again')
            if set(data['names']) != set(analyzer.ctx.platform_ids):
                raise ValueError('Snapshot sources differ from configuration; collect again')
            results, names, failed = data['results'], data['names'], data['failed']
            from trendradar.storage.article_content import save_content
            save_content(cfg, data['crawl_date'], results)
            analyzer.storage_manager.save_news_data(convert_crawl_results_to_news_data(
                results, names, failed, data['crawl_time'], data['crawl_date']))
        else:
            results, names, failed = analyzer._crawl_data()
            snapshot.write_text(json.dumps({
                'results': results, 'names': names, 'failed': failed,
                'status': analyzer.financial_source_status,
                'crawl_date': analyzer.ctx.format_date(), 'crawl_time': analyzer.ctx.format_time(),
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        if not results:
            raise RuntimeError('No financial sources succeeded')
        rss_items, rss_new, raw_rss, rss_urls = analyzer._crawl_rss_data()
        (base / 'rss_collection.json').write_text(json.dumps({
            'items': raw_rss, 'source_total': analyzer._rss_source_total,
            'source_failed': analyzer._rss_source_failed, 'total': analyzer._rss_total_count,
        }, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        report = analyzer._execute_mode_strategy(analyzer._get_mode_strategy(), results, names, failed,
            rss_items=rss_items, rss_new_items=rss_new, raw_rss_items=raw_rss, rss_new_urls=rss_urls)
        print('REPORT:', report)
    finally:
        analyzer.storage_manager.cleanup()


if __name__ == '__main__':
    main()
