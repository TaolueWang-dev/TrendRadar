import unittest
from trendradar.ai.analyzer import AIAnalyzer, AIAnalysisResult
from trendradar.ai.formatter import _render_citations, render_ai_analysis_html_rich


class CitationTests(unittest.TestCase):
    def test_only_included_items_registered(self):
        analyzer = object.__new__(AIAnalyzer)
        analyzer.max_news = 1
        analyzer.include_rss = True
        analyzer.include_rank_timeline = False
        analyzer._sources = {}
        a = {'title': '新闻', 'url': 'https://example.com/a', 'source_name': '来源'}
        b = {'title': '超出上限', 'url': 'https://example.com/b'}
        prepared = analyzer._prepare_news_content([{'word': '财经', 'titles': [a, b]}])
        self.assertIn('[[S1]]', prepared.news_content)
        self.assertEqual(list(analyzer._sources), ['S1'])
        self.assertEqual(analyzer._citation(a, '来源'), ' | 来源编号:[[S1]]')
        self.assertEqual(analyzer._citation({'url': 'javascript:alert(1)'}), '')

    def test_safe_render_and_missing_reference(self):
        sources = {'S1': {'url': 'https://example.com/?a=1&b=2', 'source': '<来源>', 'title': '标题"'},
                   'S2': {'url': 'javascript:alert(1)'}}
        html = _render_citations('<script>x</script>[[S1]][[S2]][[S999]]', sources)
        self.assertNotIn('<script>', html)
        self.assertNotIn('javascript:', html)
        self.assertEqual(html.count('<a '), 1)
        self.assertEqual(html.count('来源待核实'), 2)
        self.assertIn('&amp;b=2', html)

    def test_all_html_sections_have_links(self):
        result = AIAnalysisResult(success=True, sources={'S1': {'url': 'https://example.com', 'source': '来源'}})
        for name in ('core_trends', 'sentiment_controversy', 'signals', 'rss_insights', 'outlook_strategy'):
            setattr(result, name, '结论[[S1]]')
        result.standalone_summaries = {'源': '结论[[S1]]'}
        self.assertEqual(render_ai_analysis_html_rich(result).count('class="ai-citation"'), 6)
