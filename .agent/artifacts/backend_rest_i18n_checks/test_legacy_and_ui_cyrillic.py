"""Approved replacement: immutable extracted legacy, strict UI AST and locale keys."""
import ast
from collections import Counter
import hashlib
import json
import io
import tokenize
from pathlib import Path
import re
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'workspace/telegram-rag-bot-src/telegram_rag_bot'
CYRILLIC = re.compile('[А-Яа-яЁё]')
MARKERS = {'loader.greeting_header': '# ПРИВЕТСТВИЕ', 'loader.greeting_instruction': 'Используйте это приветствие', 'loader.role_header': '# РОЛЬ И ПОВЕДЕНИЕ'}


def _method(source, name):
    return next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def _literals(node):
    return Counter(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and CYRILLIC.search(n.value))


def assert_ui_cyrillic_allowed(source, allow_markers=False):
    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    lines = source.splitlines()
    comments = {token.start[0]: token.string for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT}
    marker_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
        elif isinstance(node, ast.JoinedStr):
            value = ''.join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        else:
            continue
        if not CYRILLIC.search(value):
            continue
        owner = parents.get(node)
        # Only documented logger calls with line-level markers are exempt.
        ancestor = owner
        while ancestor is not None:
            if isinstance(ancestor, ast.Call) and isinstance(ancestor.func, ast.Attribute) and isinstance(ancestor.func.value, ast.Name) and ancestor.func.value.id in {'logger', 'logging'} and ancestor.func.attr in {'debug', 'info', 'warning', 'error', 'exception', 'critical', 'log'}:
                assert '# noqa: i18n' in comments.get(node.lineno, ''), f'unmarked logging literal at {node.lineno}'
                break
            ancestor = parents.get(ancestor)
        else:
            if allow_markers and isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == '_marker' and len(owner.args) >= 2 and isinstance(owner.args[0], ast.Constant) and owner.args[0].value in MARKERS and node is owner.args[1] and value == MARKERS[owner.args[0].value]:
                assert '# noqa: i18n' in comments.get(node.lineno, '')
                assert 'baseline legacy marker fallback, required for backward compat' in lines[node.lineno - 1]
                marker_count += 1
                continue
            raise AssertionError(f'UI/docstring Cyrillic at line {node.lineno}: {value!r}')
    if allow_markers:
        assert marker_count == 3


def test_extracted_legacy_ast_and_cyrillic_multiset_preserved():
    # User clarification: invariant A covers the extracted method; other UI is B/C.
    snapshot = json.loads((ROOT / '.agent/artifacts/backend_rest_i18n_snapshot.json').read_text())
    original = _method(snapshot['before']['workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py'], '_legacy_handle_message')
    extracted = _method((SRC / 'handlers_legacy.py').read_text(), 'legacy_handle_message')
    assert [ast.dump(n, include_attributes=False) for n in original.body] == [ast.dump(n, include_attributes=False) for n in extracted.body]
    assert _literals(original) <= _literals(extracted)


def test_handlers_and_mode_loader_ast():
    assert_ui_cyrillic_allowed((SRC / 'handlers.py').read_text())
    assert_ui_cyrillic_allowed((SRC / 'mode_loader.py').read_text(), True)


def test_new_ui_literal_negative_controls():
    for source in ['message = "Новая строка"', 'message = f"Новая строка {1}"', 'message = "Новая строка" # noqa: i18n', 'unrelated("Новая строка") # noqa: i18n']:
        with pytest.raises(AssertionError): assert_ui_cyrillic_allowed(source)
    assert_ui_cyrillic_allowed('logger.warning("Диагностика") # noqa: i18n')
    for source in ['logger.warning("Диагностика # noqa: i18n")', 'text = "Ёё"', '_marker("unrelated", "Новый", value) # noqa: i18n']:
        with pytest.raises(AssertionError): assert_ui_cyrillic_allowed(source)
    with pytest.raises(AssertionError): assert_ui_cyrillic_allowed('logger.warning("Диагностика")')


def test_all_literal_translation_keys_resolve():
    catalog = yaml.safe_load((ROOT / 'config/i18n/ru.yaml').read_text())
    for name in ('handlers.py', 'main.py'):
        tree = ast.parse((SRC / name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str): continue
            direct = isinstance(node.func, ast.Name) and node.func.id == 't'
            command = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self' and node.func.attr == '_translate'
            if not (direct or command): continue
            value = catalog
            for part in node.args[0].value.split('.'):
                assert isinstance(value, dict) and part in value, (name, node.lineno, node.args[0].value)
                value = value[part]
            assert isinstance(value, str)


def test_superseded_body_identity_and_expected_old_failure():
    archive = ROOT / '.agent/artifacts/backend_rest_wiring_checks/test_i18n_keys_used.py.superseded'
    data = archive.read_bytes()
    original = data.split(b'\n', 3)[3]
    sha = hashlib.sha256(original).hexdigest()
    assert sha == '81b87f6526a3c86d3dd0fa4946b454c835fc11949165c90730586cbcf6f68e63'
    assert sha.encode() in data.split(b'\n', 3)[2]
    snapshot = json.loads((ROOT / '.agent/artifacts/backend_rest_wiring_snapshot.json').read_text())
    old = _literals(ast.parse(snapshot['before']['workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py']))
    new = _literals(ast.parse((SRC / 'handlers.py').read_text()))
    assert old != new, 'Old retention equality would unexpectedly pass'
