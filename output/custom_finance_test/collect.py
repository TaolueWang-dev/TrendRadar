from pathlib import Path
import subprocess, shlex, json
base=Path(__file__).resolve().parent
script=(base/'collect_remote.py').read_text()
command='/home/wangtaolue/realtime_news_analysis/.venv/bin/python -u -c '+shlex.quote(script)
res=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','a800',command],capture_output=True,text=True,timeout=240)
(base/'collection.log').write_text(res.stderr)
if res.returncode:
    print(res.stderr[-4000:]);raise SystemExit(res.returncode)
if 'TEST_SAMPLE_JSON_BEGIN\n' not in res.stdout:raise RuntimeError('No sample returned')
data=json.loads(res.stdout.split('TEST_SAMPLE_JSON_BEGIN\n',1)[1])
if (base/'sample.json').exists():
    previous=json.loads((base/'sample.json').read_text())
    data['news']=previous['news']
    data['news_collected_at']=previous['collected_at']
    data['status']['futu']['news_status']='partial: US news returned ret=-1 and the existing client stopped after 5 failures; index queries were not reached; no further news retries'
    data['status']['futu']['successful_news_symbols']=sum(bool(x) for x in data['news'].values())
(base/'sample.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({'collected_at':data['collected_at'],'status':data['status'],'selected':data['constituents'],'news_count':sum(len(x) for x in data['news'].values())},ensure_ascii=False,indent=2))
