import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from trendradar.ai.filter import AIFilter
from trendradar.ai.filter_pipeline import AIFilterPipeline, load_fixed_tags
from trendradar.core.loader import _load_ai_filter_config


class FixedTagTests(unittest.TestCase):
    def test_ten_unique_tags_and_scope(self):
        tags, scope = load_fixed_tags('market_watch_tags.json')
        self.assertEqual(len(tags), 10)
        self.assertEqual(len({t['tag'] for t in tags}), 10)
        self.assertIn('纳斯达克100', scope)
        self.assertIn('2年期美债', scope)
        self.assertEqual(_load_ai_filter_config({'ai_filter': {'fixed_tags_file': 'x.json'}})['FIXED_TAGS_FILE'], 'x.json')

    def test_duplicate_tags_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.json'
            path.write_text(json.dumps({'tags': [{'tag': 'a', 'description': 'b'}] * 2}))
            with self.assertRaises(ValueError):
                load_fixed_tags(path)

    def test_pipeline_skips_ai_tag_generation_and_reuses_cache(self):
        storage = MagicMock()
        storage.get_latest_ai_filter_tag_version.return_value = 0
        storage.get_latest_prompt_hash.return_value = None
        tags, _ = load_fixed_tags('market_watch_tags.json')
        storage.get_active_ai_filter_tags.return_value = tags
        cfg = {'AI_FILTER': {'FIXED_TAGS_FILE': 'market_watch_tags.json'}}
        with tempfile.TemporaryDirectory() as tmp:
            cfg['STORAGE'] = {'LOCAL': {'DATA_DIR': tmp}}
            pipeline = AIFilterPipeline(cfg, storage, datetime.now)
            pipeline._collect_pending_news = MagicMock(return_value=([], [], [], [], [], [], []))
            pipeline._print_pending_stats = MagicMock()
            pipeline._classify_batches = MagicMock(return_value=([], [], []))
            pipeline._save_results = MagicMock()
            pipeline._build_filter_result = MagicMock()
            with patch('trendradar.ai.filter_pipeline.AIFilter') as cls:
                ai = cls.return_value
                ai.load_interests_content.return_value = '金融兴趣'
                ai.compute_interests_hash.side_effect = AIFilter.compute_interests_hash.__get__(object.__new__(AIFilter))
                pipeline.run()
                current_hash = storage.save_ai_filter_tags.call_args.args[2]
                self.assertEqual(len(storage.save_ai_filter_tags.call_args.args[0]), 10)
                self.assertIn('固定标签', ai.compute_interests_hash.call_args.args[0])
                storage.get_latest_prompt_hash.return_value = current_hash
                pipeline.run()
                self.assertEqual(storage.save_ai_filter_tags.call_count, 1)
                ai.extract_tags.assert_not_called()
                ai.update_tags.assert_not_called()
                storage.clear_analyzed_news.assert_called_once()


if __name__ == '__main__':
    unittest.main()
