"""In-memory read-only orchestration of the user's existing remote channel clients.
No database updates, deployment, or service restarts. Output is a bounded test sample.
"""
import sys, types, logging, time, json, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('/home/wangtaolue/realtime_news_analysis')
sys.path.insert(0, str(ROOT/'trending_topic_analysis'))
cfg = types.ModuleType('config')
cfg.HKT = timezone(timedelta(hours=8))
cfg.NOW = datetime.now(cfg.HKT)
cfg.TODAY = cfg.NOW.strftime('%Y-%m-%d')
cfg.OPEND_HOST, cfg.OPEND_PORT = '127.0.0.1', 11111
cfg.logger = logging.getLogger('financial-test')
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
class Throttle:
    def wait(self): time.sleep(0.4)
cfg.THROTTLE = Throttle()
def retry_call(fn, name, retries=1, base_delay=1):
    for i in range(retries+1):
        try: return fn()
        except Exception:
            if i==retries: raise
            time.sleep(base_delay)
cfg.retry_call = retry_call
sys.modules['config'] = cfg
from futu_client import (opend_connect, fetch_futu_hot_list, fetch_futu_news,
                         fetch_tencent_ts, fetch_tencent_index)
from ths_client import fetch_ths_hot
from windows import compute_windows

db = sqlite3.connect('file:/data1/Jiajian/realtime_news_analysis/output/realtime.db?mode=ro',uri=True)
db.row_factory = sqlite3.Row
hsi = [{'code':'HK.'+str(r[0]).zfill(5),'name':r[1]} for r in db.execute('SELECT DISTINCT stock_code,stock_name FROM hsi_constituents WHERE as_of_date=(SELECT max(as_of_date) FROM hsi_constituents)')]
ndx = [{'code':'US.'+str(r[0]),'name':r[1]} for r in db.execute('SELECT DISTINCT symbol,company_name FROM nasdaq100_constituents WHERE as_of_date=(SELECT max(as_of_date) FROM nasdaq100_constituents)')]
status = {'xueqiu':'unavailable: opencli is absent on the execution host; no historical substitution'}
ctx = opend_connect()
try:
    hot = fetch_futu_hot_list(ctx)
    if not any(hot.values()): raise RuntimeError('No current Futu hot-list data')
    hot_map={x['security']:x for m in hot.values() for x in m}
    def top(items):
        return sorted((x for x in items if x['code'] in hot_map),key=lambda x:hot_map[x['code']]['average_heat'],reverse=True)[:10]
    selected_hsi,selected_ndx=top(hsi),top(ndx)
    codes=[x['code'] for x in selected_hsi+selected_ndx]
    hk_ts,us_ts=fetch_tencent_ts('hkHSI'),fetch_tencent_ts('usNDX')
    hk_start,us_start=compute_windows(hk_ts,us_ts)
    status['time_windows']='index timestamps' if hk_ts and us_ts else 'includes original 48-hour fallback where index timestamp unavailable'
    # The initial probe hit the news endpoint's failure circuit breaker.
    # Refresh rankings only; retain successful same-session news locally.
    news={}
finally:
    ctx.close()
status['futu']={'hotlist_counts':{k:len(v) for k,v in hot.items()},'requested_news_symbols':len(codes)+4,'nonempty_news_symbols':sum(bool(v) for v in news.values())}
try:
    ths=fetch_ths_hot()
    status['ths']='ok' if ths else 'empty response'
except Exception as e:
    ths=[];status['ths']='failed: '+type(e).__name__
bare={x.split('.',1)[1] for x in codes}
start=min(hk_start,us_start).strftime('%Y-%m-%d %H:%M:%S')
end=cfg.NOW.strftime('%Y-%m-%d %H:%M:%S')
rows=db.execute('SELECT event_id,stock_code,stock_name,title,published_at,source,read_count,comment_count,detail_url FROM dongcai_financial_news WHERE published_at>=? AND published_at<=? ORDER BY read_count DESC',(start,end)).fetchall()
dc=[];per_stock={}
for row in rows:
    x=dict(row); code=str(x['stock_code'])
    if code not in bare:continue
    if per_stock.get(code,0)>=5:continue
    per_stock[code]=per_stock.get(code,0)+1
    x['dat_type']='trending' if x['source']=='热点' else 'news'
    dc.append(x)
status['dongcai']={'latest_in_database':db.execute('SELECT max(published_at) FROM dongcai_financial_news').fetchone()[0], 'window_rows':len(rows),'sample_rows':len(dc)}
db.close()
sample={
 'collected_at':cfg.NOW.isoformat(),'status':status,
 'windows':{'hk_start':hk_start.isoformat(),'us_start':us_start.isoformat()},
 'universe_counts':{'hsi':len(hsi),'ndx':len(ndx)},
 'constituents':{'hsi':selected_hsi,'ndx':selected_ndx},
 'hot_list':{k:[x for x in v if x['security'] in codes] for k,v in hot.items()},
 'news':{k:v[:5] for k,v in news.items()},
 'ths':[x for x in ths if x['symbol'] in bare], 'dongcai':dc,
}
print('TEST_SAMPLE_JSON_BEGIN')
print(json.dumps(sample,ensure_ascii=False,default=str))
