from pathlib import Path
from copy import deepcopy
import shutil
import pytest
import yaml
from telegram_rag_bot.diagnostics import load_graph, InvalidGraph

SOURCE = Path('config/modes/it_support/diagnostics.yaml')

def graph_fixture(tmp_path, mutate=None):
    path = tmp_path / 'config/modes/it_support/diagnostics.yaml'
    path.parent.mkdir(parents=True)
    (tmp_path / 'config/i18n').mkdir(parents=True)
    shutil.copy('config/i18n/ru.yaml', tmp_path / 'config/i18n/ru.yaml')
    shutil.copy('config/modes/it_support/faq.md', path.parent / 'faq.md')
    data = yaml.safe_load(SOURCE.read_text())
    if mutate:
        mutate(data)
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    return path

def test_all_paths_are_deterministic_and_escalatable():
    graph = load_graph(SOURCE)
    for scenario, spec in graph.scenarios.items():
        for name, node in spec['nodes'].items():
            assert graph.escalate_available(name)
            assert graph.escalate_available(node)
            for i in range(len(node.get('choices', []))):
                assert graph.step(scenario,name,i) == graph.step(scenario,name,i)

@pytest.mark.parametrize('mutate', [
 lambda d:d['scenarios']['vpn']['nodes']['client']['choices'][0].update(next='client'),
 lambda d:d['scenarios']['vpn']['nodes']['client']['choices'][0].update(next='unknown'),
 lambda d:d['scenarios']['vpn']['nodes']['client'].pop('escalation'),
 lambda d:d['scenarios']['vpn']['nodes']['client'].update(question_key='unknown.key'),
 lambda d:d['scenarios']['vpn']['nodes']['install'].update(faq_ref='faq.md#unknown'),
])
def test_invalid_graphs(tmp_path, mutate):
    with pytest.raises(InvalidGraph):
        load_graph(graph_fixture(tmp_path,mutate))

def test_deep_path_rejected(tmp_path):
    def mutate(d):
        nodes=d['scenarios']['vpn']['nodes']
        for name,nxt in [('extra1','extra2'),('extra2','install')]:
            nodes[name]=deepcopy(nodes['client'])
            for c in nodes[name]['choices']: c['next']=nxt
        nodes['connection']['choices'][0]['next']='extra1'
    with pytest.raises(InvalidGraph):load_graph(graph_fixture(tmp_path,mutate))
