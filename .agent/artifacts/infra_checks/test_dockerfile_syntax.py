"""Static image contract checks; never starts Docker."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[3]


def assert_image_contract(text):
    assert re.search(r'^FROM python:3\.13-slim AS builder$', text, re.M)
    assert re.search(r'^FROM python:3\.13-slim AS runtime$', text, re.M)
    assert 'COPY workspace/telegram-rag-bot-src/ /build/' in text
    assert 'python -m build --wheel --outdir /dist' in text
    assert 'COPY --from=builder /dist/*.whl /app/' in text
    assert 'python -m pip install --no-cache-dir /app/*.whl' in text
    assert re.search(r'^USER (app|1000)$', text, re.M)
    assert '--uid 1000' in text
    assert 'HEALTHCHECK ' in text and 'urllib.request.urlopen' in text
    assert 'timeout=5' in text and '127.0.0.1:8080/health' in text
    assert re.search(r'^EXPOSE 8080$', text, re.M)
    cmd = re.findall(r'^CMD (.+)$', text, re.M)
    assert len(cmd) == 1
    assert json.loads(cmd[0]) == ['python', '-m', 'telegram_rag_bot', 'run']
    assert 'COPY deploy/build_config_overlay.py /tmp/build_config_overlay.py' in text
    assert 'RUN python /tmp/build_config_overlay.py /app/config/config.yaml' in text
    assert 'RUN rm /tmp/build_config_overlay.py' in text
    assert "assert c['http_server']['port']==8080" in text
    assert "assert c['http_server']['enabled'] is True" in text
    assert text.index('COPY config/') < text.index('RUN python /tmp/build_config_overlay.py') < text.index('chown -R') < text.index('USER app')
    assert 'WORKDIR /app' in text
    assert 'PYTHONPATH=/app' in text and 'PYTHONDONTWRITEBYTECODE=1' in text
    assert 'PYTHONUNBUFFERED=1' in text
    assert 'ENV CONFIG_PATH' not in text
    assert not re.search(r'(?i)sk-|eyJ|password=|^ARG .*SECRET|^ENV .*TOKEN=', text, re.M)
    for package in ('integrations', 'analytics', 'config'):
        assert f'COPY {package}/ /app/{package}/' in text


def test_context_excludes_sensitive_and_audit_files():
    lines = set((ROOT / '.dockerignore').read_text().splitlines())
    for required in ('.agent/', '.agents/', '.venv/', '.env', '.env.*', 'tests/',
                     'workspace/telegram-rag-bot/', 'dist/', 'build/',
                     'analytics/unanswered.jsonl', '**/*.pem', '**/*.key'):
        assert required in lines
    assert 'workspace/telegram-rag-bot-src/' not in lines
    ignores = set((ROOT / '.gitignore').read_text().splitlines())
    assert {'artifacts/', '*.coverage', '.coverage*', 'coverage.json', '*.log',
            '__pycache__/', '*.pyc', '.venv/', '*.egg-info/', 'build/', 'dist/',
            '.env', '.env.local'} <= ignores
    assert '.agent/artifacts/' not in ignores


def test_image_contract():
    assert_image_contract((ROOT / 'Dockerfile').read_text())


def test_removed_overlay_or_postassert_is_rejected():
    import pytest
    text = (ROOT / 'Dockerfile').read_text()
    for prefix in ('RUN python /tmp/build_config_overlay.py', 'RUN python -c "import yaml;'):
        mutated = '\n'.join(line for line in text.splitlines() if not line.startswith(prefix))
        with pytest.raises(AssertionError):
            assert_image_contract(mutated)
