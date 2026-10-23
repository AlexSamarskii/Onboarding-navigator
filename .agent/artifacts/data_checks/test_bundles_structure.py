from pathlib import Path
import hashlib
import json
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MODES = ('it_support', 'benefits', 'learning', 'culture', 'onboarding_plan')

@pytest.mark.parametrize('mode', MODES)
def test_baseline_fields_and_sources(mode):
    bundle = ROOT / 'config/modes' / mode
    data = yaml.safe_load((bundle / 'mode.yaml').read_text())
    required = {'name', 'display_name', 'description', 'enabled', 'files', 'timeout_seconds'}
    assert required <= data.keys()
    assert data.keys() <= required | {'source_titles', 'diagnostics_file', 'plans_directory'}
    assert data['name'] == mode
    assert isinstance(data['display_name'], str)
    assert isinstance(data['description'], str)
    assert data['enabled'] is True
    assert isinstance(data['timeout_seconds'], int) and data['timeout_seconds'] > 0
    assert set(data['files']) == {'system_prompt', 'faq'}
    for relative in [*data['files'].values(), *data['source_titles']]:
        source = (bundle / relative).resolve()
        assert source.is_relative_to(bundle.resolve())
        assert source.is_file()
    if mode == 'it_support':
        before = json.loads((ROOT / '.agent/artifacts/data_scope_snapshot.json').read_text())['before']
        baseline = yaml.safe_load(before['config/modes/it_support/mode.yaml'])
        for field in required - {'display_name'}:
            assert data[field] == baseline[field]
        assert data['display_name'] == 'mode.it_support'
        assert data['diagnostics_file'] == 'diagnostics.yaml'
    if mode == 'onboarding_plan':
        assert data['plans_directory'] == 'plans'
        plans = [bundle / 'plans' / f'{name}.md' for name in ('developer', 'developer__engineering', 'default')]
        assert all(p.is_file() and '- [ ]' in p.read_text() for p in plans)
        assert len({p.read_text() for p in plans}) == 3


def test_protected_files_unchanged():
    snapshot = json.loads((ROOT / '.agent/artifacts/data_scope_snapshot.json').read_text())
    for path, expected in snapshot['protected_hashes'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
