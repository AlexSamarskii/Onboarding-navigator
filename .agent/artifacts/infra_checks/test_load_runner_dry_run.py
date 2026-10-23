"""Only --dry-run subprocess execution; unit checks never perform HTTP."""
from pathlib import Path
from collections import Counter
import ast
import importlib.util
import json
import math
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'tests/load/run_baseline.py'


def load_runner():
    spec = importlib.util.spec_from_file_location('infra_runner', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_contract(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(RUNNER), '--dry-run', '--seed', '0',
        '--rps', '10', '--duration', '300', '--samples', '1000', '--out', str(tmp_path)],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output == json.loads((tmp_path / 'sample_manifest.json').read_text())
    assert output['seed'] == 0 and output['expected_rps'] == 10
    assert output['expected_duration'] == 300
    assert output['offered_request_count'] == 3000
    assert output['expected_request_count'] == 3100
    entries = output['sample_manifest']
    assert len(entries) == 1000
    assert len({row['request_id'] for row in entries}) == 1000
    module = load_runner()
    for row in entries:
        scenario, mode, query = module.SCENARIOS[row['request_id'] % 12]
        assert (row['scenario'], row['mode'], row['query']) == (scenario, mode, query)
        assert 0 <= row['request_id'] < 3000
    counts = Counter(row['scenario'] for row in entries)
    assert [counts[row[0]] for row in module.SCENARIOS] == [84] * 4 + [83] * 8
    assert output['thresholds']['p95_telegram_e2e_ms'] == 3000
    assert output['thresholds']['p95_rag_only_ms'] == 200
    assert not (tmp_path / 'summary.json').exists()


def test_no_application_imports_and_dry_run_cannot_request(tmp_path, monkeypatch, capsys):
    module = load_runner()
    tree = ast.parse(RUNNER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not item.name.startswith('telegram_rag_bot') for item in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith('telegram_rag_bot')
    def forbidden(*args, **kwargs):
        raise AssertionError('dry-run reached HTTP code')
    monkeypatch.setattr(module.urllib.request, 'urlopen', forbidden)
    assert module.main(['--dry-run', '--telegram-e2e', '--target-url', 'http://unused.invalid',
                        '--out', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['sample_count'] == 1000


def test_p95_and_failures():
    module = load_runner()
    assert module.percentile95(list(reversed(range(1000)))) == 950
    assert module.percentile95([0] * 950 + [math.inf] * 50) == math.inf
