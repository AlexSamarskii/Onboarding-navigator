"""Application boundaries only: no bot, ConfigLoader, provider or network execution."""
import asyncio
from copy import deepcopy
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry
from telegram_rag_bot.utils.metrics import register_metrics

main = importlib.import_module('telegram_rag_bot.main')
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def synthetic_runtime_environment(monkeypatch):
    for key in ('TELEGRAM_TOKEN', 'GIGACHAT_KEY', 'YANDEX_API_KEY', 'YANDEX_FOLDER_ID'):
        monkeypatch.setenv(key, 'synthetic-value')


class FakeProvider:
    def __init__(self, name, *, fail=False, healthy=True):
        self.config = SimpleNamespace(name=name, model='fake')
        self.fail, self.healthy = fail, healthy
        self.calls = []
    async def generate(self, prompt, params=None):
        self.calls.append((prompt, params))
        await asyncio.sleep(0)
        if self.fail:
            raise ValueError('synthetic failure')
        return 'fake reply'
    async def health_check(self):
        return self.healthy


@pytest.fixture
def isolated(monkeypatch):
    registry = CollectorRegistry()
    metrics = register_metrics(registry)
    monkeypatch.setattr(main, 'LLM_REQUESTS', metrics['LLM_REQUESTS'])
    monkeypatch.setattr(main, 'FALLBACK_TOTAL', metrics['FALLBACK_TOTAL'])
    return registry


def sample(registry, name, labels):
    return registry.get_sample_value(name, labels) or 0


@pytest.mark.asyncio
async def test_observer_counts_each_attempt_and_health(isolated):
    cache = {}
    provider = FakeProvider('gigachat')
    observed = main.ProviderObserver(provider, cache)
    assert observed.config is provider.config
    assert await observed.generate('prompt', {'temperature': 0}) == 'fake reply'
    assert provider.calls == [('prompt', {'temperature': 0})]
    assert sample(isolated, 'llm_requests_total', {'provider': 'gigachat', 'status': 'success'}) == 1
    assert await observed.health_check()
    assert cache['gigachat'] == 'ok' and cache['last_check_iso']['gigachat'].endswith('+00:00')
    provider.fail = True
    with pytest.raises(ValueError):
        await observed.generate('prompt')
    assert sample(isolated, 'llm_requests_total', {'provider': 'gigachat', 'status': 'failure'}) == 1
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 0


@pytest.mark.asyncio
async def test_real_unchanged_router_scopes_switches_and_direct_calls(isolated):
    from orchestrator import Router
    router = Router(strategy='first-available')
    first, second = FakeProvider('gigachat', fail=True), FakeProvider('yandexgpt')
    router.add_provider(main.ProviderObserver(first, {}))
    router.add_provider(main.ProviderObserver(second, {}))
    scoped = main.RequestScopedRouter(router)
    await scoped.route('a')
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 1
    # Independent invocation directly on the second provider is not a switch.
    await router.providers[1].generate('b')
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 1
    await asyncio.gather(scoped.route('c'), scoped.route('d'))
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 3
    first.healthy = False
    await scoped.route('healthy second provider')
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 3


@pytest.mark.asyncio
async def test_failed_health_updates_cache_without_switch_or_attempt(isolated):
    provider = FakeProvider('gigachat')
    async def fail_health():
        raise RuntimeError('synthetic health failure')
    provider.health_check = fail_health
    cache = {}
    with pytest.raises(RuntimeError):
        await main.ProviderObserver(provider, cache).health_check()
    assert cache['gigachat'] == 'fail'
    assert sample(isolated, 'fallback_total', {'type': 'llm'}) == 0
    assert sample(isolated, 'llm_requests_total', {'provider': 'gigachat', 'status': 'failure'}) == 0


@pytest.mark.parametrize('async_mode', [True, 'false', 0, None])
def test_async_configuration_rejected(async_mode):
    with pytest.raises(ValueError):
        main.normalize_runtime_config({'retrieval': {'async_mode': async_mode}})


def test_product_and_legacy_defaults_use_only_synthetic_env(monkeypatch):
    for key in ('TELEGRAM_TOKEN', 'GIGACHAT_KEY', 'YANDEX_API_KEY', 'YANDEX_FOLDER_ID'):
        monkeypatch.setenv(key, 'synthetic-value')
    product = main.normalize_runtime_config({'llm': {'providers': ['gigachat', 'yandexgpt']}, 'session': {'ttl_seconds': 20}})
    assert product['orchestrator']['strategy'] == 'first-available'
    assert [x['name'] for x in product['orchestrator']['providers']] == ['gigachat', 'yandexgpt']
    assert product['telegram']['token'] == 'synthetic-value'
    legacy = {'telegram': {'token': 'legacy-synthetic'}, 'orchestrator': {'strategy': 'first-available', 'providers': []}}
    assert main.normalize_runtime_config(legacy)['telegram'] == legacy['telegram']


@pytest.mark.asyncio
@pytest.mark.parametrize('index_error,graph_error', [(False, False), (True, False), (False, True)])
async def test_bootstrap_order_uses_fakes(monkeypatch, tmp_path, index_error, graph_error):
    events = []
    config_path = ROOT / 'config/config.yaml'
    config = {
        'modes_directory': str(ROOT / 'config/modes'),
        'modes': {name: {'diagnostics_file': 'diagnostics.yaml'} for name in ('it_support', 'benefits', 'learning', 'culture', 'onboarding_plan')},
        'rag': {'score_threshold': .65}, 'retrieval': {'async_mode': False},
        'i18n': {'default_locale': 'ru'},
        'integrations': {'ticketing': {'url': 'https://synthetic.invalid', 'hr_chat_id': None}},
        'analytics': {'unanswered_path': str(tmp_path / 'missing' / 'unanswered.jsonl')},
    }
    # All credential inputs are synthetic, and ConfigLoader is never executed.
    for key in ('TELEGRAM_TOKEN', 'GIGACHAT_KEY', 'YANDEX_API_KEY', 'YANDEX_FOLDER_ID'):
        monkeypatch.setenv(key, 'synthetic-value')
    monkeypatch.setattr(main.ConfigLoader, 'load_config', lambda path: events.append('config') or deepcopy(config))
    monkeypatch.setattr(main, 'load_locale', lambda path: events.append(('locale', path)))
    monkeypatch.setattr(main, 'register_metrics', lambda: events.append('metrics'))
    monkeypatch.setattr(main, 'setup_logging', lambda cfg: None)
    local_router = SimpleNamespace(providers=[FakeProvider('gigachat'), FakeProvider('yandexgpt')])
    monkeypatch.setattr(main, 'create_router', lambda *args, **kwargs: local_router)
    monkeypatch.setattr(main, 'MultiLLMOrchestrator', lambda **kwargs: SimpleNamespace(**kwargs))
    class Factory:
        def __init__(self, **kwargs):
            events.append('factory')
            self.embeddings_provider = object()
            self.vectorstore_provider = None
            self.chains = {}
        def create_chain(self, mode):
            pytest.fail('bootstrap must not create a chain before indexing')
    monkeypatch.setattr(main, 'RAGChainFactory', Factory)
    class HR:
        def __init__(self, cfg, embeddings, **kwargs):
            self.factory = kwargs['rag_factory']
            self.threshold = kwargs['score_threshold']
    monkeypatch.setattr(main, 'HRFAISSProvider', HR)
    class Coordinator:
        def __init__(self, provider, directory, **kwargs):
            assert provider.factory.vectorstore_provider is provider
            events.append('coordinator')
        async def ingest(self, sources):
            events.append('ingest')
            assert any(p.name == 'developer__engineering.md' for p in sources)
            assert any(p.name == 'example.md' for p in sources)
            if index_error:
                raise RuntimeError('synthetic index failure')
    monkeypatch.setattr(main, 'IndexCoordinator', Coordinator)
    monkeypatch.setattr(main, 'TicketClient', lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(main, 'UnansweredWriter', lambda path: SimpleNamespace(path=path))
    def graph(path):
        events.append(('graph', path))
        if graph_error:
            raise ValueError('synthetic bad graph')
        return 'graph'
    monkeypatch.setattr(main, 'load_graph', graph)
    monkeypatch.setattr(main, 'SessionManager', lambda **kwargs: SimpleNamespace(redis_client=None))
    monkeypatch.setattr(main, 'FeedbackCollector', lambda redis: None)
    def handlers(**kw):
        assert events.index('metrics') < events.index('factory')
        return SimpleNamespace(**kw)
    monkeypatch.setattr(main, 'TelegramHandlers', handlers)
    result = await main.bootstrap_components(config_path)
    assert events[0] == 'config' and events[1][0] == 'locale' and events[2] == 'metrics'
    assert result.rag_factory.vectorstore_provider.threshold == .65
    assert result.handlers.diagnostics_graph == (None if graph_error else 'graph')
    assert (result.runtime_state['last_reindex'] == 'never') == index_error
    assert result.health_cache['gigachat'] == result.health_cache['yandexgpt'] == 'fail'
    assert isinstance(local_router.providers[0], main.ProviderObserver)


def test_command_alias_and_new_admin_commands():
    methods = {name: Mock() for name in ('cmd_start', 'cmd_set_mode', 'cmd_reindex', 'cmd_status', 'cmd_help', 'cmd_feedback', 'cmd_escalate', 'cmd_diagnostics', 'handle_message', 'handle_callback_query')}
    application = SimpleNamespace(add_handler=Mock())
    main.register_command_handlers(application, SimpleNamespace(**methods))
    commands = {command: registered.args[0].callback for registered in application.add_handler.call_args_list for command in getattr(registered.args[0], 'commands', [])}
    assert commands['reload_faq'] is commands['reindex'] is methods['cmd_reindex']
    assert commands['status'] is methods['cmd_status']
    assert commands['diagnostics'] is methods['cmd_diagnostics']
    assert commands['escalate'] is methods['cmd_escalate']
