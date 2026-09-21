import sys, json, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from trendradar.core.loader import load_config
from trendradar.ai.filter import AIFilter
import trendradar.ai.client as client_module
cfg = load_config(str(ROOT / 'config/config.yaml'))
base = Path(__file__).resolve().parent
original_completion = client_module.completion
def observed_completion(**kwargs):
    response = original_completion(**kwargs)
    choice = response.choices[0]
    data = {'finish_reason':choice.finish_reason, 'content':choice.message.content,
            'usage':response.usage.model_dump() if response.usage else None}
    (base / 'diagnostic_response.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print('FINISH', data['finish_reason'], 'USAGE', data['usage'], flush=True)
    print('CONTENT_PREFIX', repr(data['content'][:250]), flush=True)
    return response
client_module.completion = observed_completion
f = AIFilter(cfg['AI'], cfg['AI_FILTER'], lambda:None)
with sqlite3.connect(f'file:{base}/output/news/2026-09-20.db?mode=ro',uri=True) as db:
    db.row_factory = sqlite3.Row
    tags = [dict(r) for r in db.execute('SELECT id,tag,description FROM ai_filter_tags')]
    titles = [dict(r) for r in db.execute('SELECT id,title,platform_id AS source FROM news_items ORDER BY id LIMIT 200')]
res=f.classify_batch(titles,tags,(ROOT/'config/custom/ai/finance_test.txt').read_text())
print('MATCHES',len(res) if res is not None else None)
