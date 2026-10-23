"""Replay manifest selections with no real traffic."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'tests/load/run_baseline.py'


def dry_run(seed, out):
    result = subprocess.run([sys.executable, '-B', str(RUNNER), '--dry-run', '--seed', str(seed),
                             '--out', str(out)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)['sample_manifest']


def test_sampling_replays_and_varies(tmp_path):
    assert dry_run(0, tmp_path / 'first') == dry_run(0, tmp_path / 'second')
    assert dry_run(0, tmp_path / 'first') != dry_run(1, tmp_path / 'third')


def test_rag_only_fails_explicitly_even_in_dry_run(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(RUNNER), '--rag-only', '--dry-run',
        '--out', str(tmp_path / 'not_created')], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert result.stderr.strip() == (
        'rag-only requires /debug/rag_latency endpoint, which is not '
        'exposed by the frozen application. AC-N02 remains '
        'pending_environment pending a separate small PR or an '
        'out-of-band profiling run.')
    assert not (tmp_path / 'not_created').exists()
