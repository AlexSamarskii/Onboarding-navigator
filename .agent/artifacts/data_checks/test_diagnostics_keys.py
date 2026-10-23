from pathlib import Path
import re
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
LOCALE = yaml.safe_load((ROOT / 'config/i18n/ru.yaml').read_text())
GRAPH = yaml.safe_load((ROOT / 'config/modes/it_support/diagnostics.yaml').read_text())


def lookup(key):
    value = LOCALE
    for part in key.split('.'):
        value = value[part]
    assert isinstance(value, str) and value
    return value


def walk_keys(value):
    if isinstance(value, dict):
        for name, item in value.items():
            if name.endswith('_key'):
                yield item
            else:
                yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


def test_all_ui_keys_exist():
    keys = list(walk_keys(GRAPH))
    assert keys
    for key in keys:
        lookup(key)
    assert set(GRAPH['scenarios']) == {'vpn', 'mail'}


@pytest.mark.parametrize('scenario', ('vpn', 'mail'))
def test_all_paths_terminate_with_faq_and_escalation(scenario):
    graph = GRAPH['scenarios'][scenario]
    nodes = graph['nodes']
    visited, ends = set(), set()
    faq = (ROOT / 'config/modes/it_support/faq.md').read_text()
    def visit(name, path=(), questions=0):
        assert name in nodes, f'unknown node {name}'
        assert name not in path, f'cycle {path} -> {name}'
        visited.add(name)
        node = nodes[name]
        assert node['escalation']['action'] == 'escalate'
        lookup(node['escalation']['label_key'])
        assert node['escalation']['label_key'].startswith(f'diagnostics.{scenario}.')
        if node['type'] == 'question':
            questions += 1
            assert questions <= 3
            assert node['question_key'].startswith(f'diagnostics.{scenario}.')
            assert len(node['choices']) >= 2
            for choice in node['choices']:
                visit(choice['next'], (*path, name), questions)
        else:
            assert node['type'] == 'terminal'
            ends.add(name)
            assert node['label_key'].startswith(f'diagnostics.{scenario}.')
            file, anchor = node['faq_ref'].split('#')
            assert file == 'faq.md'
            assert re.fullmatch('[a-z0-9-]+', anchor)
            assert f'<a id="{anchor}"></a>' in faq
    visit(graph['start'])
    assert visited == set(nodes), 'unreachable node'
    assert len(ends) >= 2
    # The data schema permits only fixed traversal, FAQ display and explicit escalation.
    for node in nodes.values():
        allowed = {'type', 'question_key', 'choices', 'escalation'} if node['type'] == 'question' else {'type', 'label_key', 'faq_ref', 'escalation'}
        assert set(node) == allowed
        if node['type'] == 'question':
            assert all(set(c) == {'label_key', 'next'} for c in node['choices'])
