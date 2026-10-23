"""Image-copy overlay contract, including deliberate mutation controls."""
from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from deploy.build_config_overlay import apply_overlay, verify_overlay, load_config, dump_config
import deploy.build_config_overlay as overlay

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def product():
    return yaml.safe_load((ROOT / 'config/config.yaml').read_text())


def test_product_preserved_and_roundtrip(product, tmp_path):
    before = deepcopy(product)
    result = apply_overlay(product)
    assert result['http_server'] == {'enabled': True, 'port': 8080}
    assert {k:v for k,v in result.items() if k != 'http_server'} == before
    assert list(result) == list(before) + ['http_server']
    result['unicode_example'] = 'Привет, сотрудник'
    path = tmp_path / 'config.yaml'
    dump_config(path, result)
    assert 'Привет, сотрудник' in path.read_text()
    assert load_config(path) == result
    assert list(load_config(path)) == list(result)
    assert verify_overlay(path, set(result)) == result


@pytest.mark.parametrize('original', [{'enabled': True, 'port': 8000},
    {'enabled': False, 'port': 9000, 'extra': 'x'}])
def test_existing_server_replaced_values_retains_extra(original):
    config = {'rag': {'score_threshold': .65}, 'http_server': deepcopy(original)}
    result = apply_overlay(config)
    assert result['http_server'] == {**original, 'enabled': True, 'port': 8080}
    assert apply_overlay(deepcopy(result)) == result


@pytest.mark.parametrize('config', [[], 'text', None, {'http_server': 'text'}, {'http_server': []}])
def test_invalid_types(config):
    with pytest.raises(ValueError):
        apply_overlay(config)


def test_verify_rejects_bad_port_enabled_and_lost_keys(tmp_path):
    path = tmp_path / 'config.yaml'
    for config, keys in [({'http_server': {'port': 9000, 'enabled': True}}, {'http_server'}),
        ({'http_server': {'port': 8080, 'enabled': False}}, {'http_server'}),
        ({'http_server': {'port': 8080, 'enabled': True}}, {'http_server', 'rag'})]:
        dump_config(path, config)
        with pytest.raises(ValueError):
            verify_overlay(path, keys)


def test_setdefault_mutation_is_detected():
    source = inspect.getsource(apply_overlay)
    assert source.count('http_server.update(enabled=True, port=8080)') == 1
    mutated = source.replace('http_server.update(enabled=True, port=8080)',
        'http_server.setdefault("enabled", True); http_server.setdefault("port", 8080)')
    namespace = {}
    exec(compile(mutated, '<negative-control>', 'exec'), namespace)
    result = namespace['apply_overlay']({'http_server': {'enabled': False, 'port': 9000}})
    with pytest.raises(AssertionError):
        assert result['http_server'] == {'enabled': True, 'port': 8080}


def test_main_postverify_and_error_exit(product, tmp_path, monkeypatch):
    path = tmp_path / 'config.yaml'
    dump_config(path, product)
    calls = []
    real_verify = overlay.verify_overlay
    def record(path, expected_keys=None):
        calls.append(set(expected_keys))
        return real_verify(path, expected_keys)
    monkeypatch.setattr(overlay, 'verify_overlay', record)
    assert overlay.main([str(path)]) == 0
    assert calls == [set(product) | {'http_server'}]
    dump_config(path, {'http_server': 'invalid'})
    process = subprocess.run([sys.executable, '-B', str(ROOT / 'deploy/build_config_overlay.py'), str(path)], capture_output=True, text=True, timeout=10)
    assert process.returncode == 1
    assert 'overlay failed' in process.stderr
