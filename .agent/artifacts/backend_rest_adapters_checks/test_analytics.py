from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from analytics.writer import UnansweredWriter, UnansweredEntry, redact


def test_jsonl_redacted_and_concurrent(tmp_path):
    path=tmp_path/'unanswered.jsonl'
    writer=UnansweredWriter(path)
    assert not path.exists()
    query='JWT eyJfoo.bar.baz password=secret token=abc passphrase=hidden a@b.test +7 (999) 123-45-67'
    def write(i):writer.write(UnansweredEntry('it_support','missing_plan' if i%2 else 'low_score',query,.5))
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(write,range(100)))
    records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(records)==100
    assert {r['reason'] for r in records}=={'missing_plan','low_score'}
    for r in records:
        assert set(r)=={'timestamp','mode','reason','query_redacted','top_score'}
        assert datetime.fromisoformat(r['timestamp']).utcoffset().total_seconds()==0
        assert all(s not in r['query_redacted'] for s in ['eyJfoo','secret','abc','hidden','a@b.test','999'])
