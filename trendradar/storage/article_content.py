"""Daily local content supplement; standard news identity/schema stays compatible."""
import hashlib
import json
from pathlib import Path


def key(source_id, title):
    return hashlib.sha256(f'{source_id}\n{title}'.encode()).hexdigest()


def content_path(config, date):
    root = config.get('STORAGE', {}).get('LOCAL', {}).get('DATA_DIR', 'output')
    return Path(root) / 'article_content' / f'{date}.json'


def read_content(config, date):
    path = content_path(config, date)
    return json.loads(path.read_text()) if path.exists() else {}


def save_content(config, date, results):
    entries = {key(source_id, title): {'title': title, 'source_id': source_id, **item}
               for source_id, titles in results.items() for title, item in titles.items() if item.get('content')}
    if not entries:
        return
    path = content_path(config, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_content(config, date)
    existing.update(entries)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
