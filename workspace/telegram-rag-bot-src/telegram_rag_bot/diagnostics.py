"""Validated deterministic diagnostic graphs; no session or LLM side effects."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import yaml


class InvalidGraph(ValueError):
    """A graph cannot be executed safely."""


@dataclass(frozen=True)
class Graph:
    scenarios: dict

    def step(self, scenario, node, choice_index):
        current = self.scenarios[scenario]['nodes'][node]
        if current['type'] == 'terminal':
            return deepcopy(current)
        if type(choice_index) is not int or not 0 <= choice_index < len(current['choices']):
            raise ValueError('invalid diagnostic choice')
        target = current['choices'][choice_index]['next']
        result = self.scenarios[scenario]['nodes'][target]
        return deepcopy(result) if result['type'] == 'terminal' else target

    def escalate_available(self, node):
        if isinstance(node, dict):
            return node.get('escalation', {}).get('action') == 'escalate'
        return any(node in s['nodes'] for s in self.scenarios.values())


def load_graph(path: Path) -> Graph:
    """Read graph and the bundle's canonical RU catalog without activating i18n."""
    path = Path(path).resolve()
    catalog_path = path.parent.parent.parent / 'i18n' / 'ru.yaml'
    with catalog_path.open(encoding='utf-8') as stream:
        catalog = yaml.safe_load(stream)
    def key(value):
        item = catalog
        if not isinstance(value, str):
            raise InvalidGraph('UI key must be a string')
        for part in value.split('.'):
            if not isinstance(item, dict) or part not in item:
                raise InvalidGraph('unknown UI key')
            item = item[part]
        if not isinstance(item, str):
            raise InvalidGraph('UI key must resolve to text')
    with path.open(encoding='utf-8') as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise InvalidGraph('version must be 1')
    scenarios = data.get('scenarios')
    if not isinstance(scenarios, dict) or not {'vpn', 'mail'} <= scenarios.keys():
        raise InvalidGraph('vpn and mail are required')
    for scenario in scenarios.values():
        if not isinstance(scenario, dict) or not isinstance(scenario.get('nodes'), dict):
            raise InvalidGraph('scenario needs nodes')
        nodes = scenario['nodes']
        start = scenario.get('start')
        if not isinstance(start, str) or start not in nodes:
            raise InvalidGraph('unknown start')
        if 'title_key' in scenario:
            key(scenario['title_key'])
        terminals = 0
        for name, node in nodes.items():
            if not isinstance(name, str) or not isinstance(node, dict):
                raise InvalidGraph('invalid node')
            escalation = node.get('escalation')
            if not isinstance(escalation, dict) or escalation.get('action') != 'escalate':
                raise InvalidGraph('every node needs escalation')
            key(escalation.get('label_key'))
            if node.get('type') == 'question':
                key(node.get('question_key'))
                choices = node.get('choices')
                if not isinstance(choices, list) or not choices:
                    raise InvalidGraph('question needs choices')
                for choice in choices:
                    if not isinstance(choice, dict):
                        raise InvalidGraph('invalid choice')
                    key(choice.get('label_key'))
                    if not isinstance(choice.get('next'), str) or choice['next'] not in nodes:
                        raise InvalidGraph('unknown next node')
            elif node.get('type') == 'terminal':
                terminals += 1
                key(node.get('label_key'))
                ref = node.get('faq_ref')
                if not isinstance(ref, str) or not re.fullmatch(r'faq\.md#[a-z0-9_-]+', ref):
                    raise InvalidGraph('invalid FAQ reference')
                anchor = ref.split('#')[1]
                faq = (path.parent / 'faq.md').read_text(encoding='utf-8')
                if not re.search(r'<a\s+(?:id|name)=["\']' + re.escape(anchor) + r'["\']', faq):
                    raise InvalidGraph('unknown FAQ anchor')
            else:
                raise InvalidGraph('unknown node type')
        seen = set()
        def visit(name, ancestors, depth):
            if name in ancestors:
                raise InvalidGraph('diagnostic cycle')
            seen.add(name)
            node = nodes[name]
            depth += node['type'] == 'question'
            if depth > 3:
                raise InvalidGraph('more than three questions')
            for choice in node.get('choices', []):
                visit(choice['next'], ancestors | {name}, depth)
        visit(start, set(), 0)
        if seen != nodes.keys() or terminals < 2:
            raise InvalidGraph('unreachable nodes or fewer than two terminals')
    return Graph(deepcopy(scenarios))
