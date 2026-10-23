"""HR adapter acceptance checks: real LCEL wiring and offline boundary fakes.

Coverage is checked by .agent/artifacts/backend_rest_i18n_checks/check_coverage.py
after the full test run; pytest is never recursively invoked by these tests.
"""
from datetime import datetime, timedelta
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import importlib
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from analytics.writer import UnansweredEntry, UnansweredWriter, redact
from integrations.ticketing import Ticket, TicketClient
from telegram_rag_bot.citations import extract_citation
from telegram_rag_bot.handlers import TelegramHandlers
from telegram_rag_bot.hr_adapter import HRFAISSProvider, LowScoreFallback
from telegram_rag_bot.i18n import load_locale, t
from telegram_rag_bot.langchain_adapter.rag_chains import RAGChainFactory
from telegram_rag_bot.utils.session_manager import SessionManager
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def locale():
    load_locale(ROOT / "config/i18n/ru.yaml")


@pytest.mark.parametrize("similarity", [0.5, 0.7])
def test_real_rag_factory_lcel_gate_and_provenance(tmp_path, monkeypatch, locale, similarity):
    """The protected factory builds LCEL; only storage/LLM boundaries are faked."""
    document = Document(page_content="VPN client; contact IT", metadata={"source": "faq.md"})
    search = Mock(return_value=[(document, 1 / similarity - 1)])
    store = SimpleNamespace(index=SimpleNamespace(metric_type=1), similarity_search_with_score=search)

    @lru_cache(maxsize=10)
    def fake_load(provider, mode):
        return store

    monkeypatch.setattr(LocalFAISSProvider, "load_index", fake_load)
    embedding = SimpleNamespace(dimension=3)
    provider = HRFAISSProvider({"indices_dir": str(tmp_path)}, embedding)
    monkeypatch.setattr("telegram_rag_bot.langchain_adapter.rag_chains.VectorStoreFactory.create",
                        lambda config, embeddings: provider)
    llm = Mock(return_value="A grounded answer")
    factory = RAGChainFactory(
        llm=RunnableLambda(llm), vectorstore_config={},
        chunk_config={"chunk_size": 100, "chunk_overlap": 10},
        modes={"it_support": {"system_prompt": "Answer from context", "faq_file": "faq.md"}},
        embeddings_instance=embedding, retrieval_config={"async_mode": False},
    )
    assert isinstance(factory.vectorstore_provider, LocalFAISSProvider)
    chain = factory.create_chain("it_support")
    if similarity < 0.65:
        with pytest.raises(LowScoreFallback) as failure:
            chain.invoke({"input": "VPN?"})
        assert failure.value.top_score == pytest.approx(similarity)
        llm.assert_not_called()
    else:
        result = chain.invoke({"input": "VPN?"})
        assert result["answer"] == "A grounded answer"
        assert result["context"][0].metadata["source"] == "faq.md"
        assert result["context"][0].metadata["score"] == pytest.approx(similarity)
        assert document.metadata == {"source": "faq.md"}
        citation = extract_citation(result["context"], {"faq.md": "mode.it_support"})
        assert citation.quote == document.page_content
        assert citation.source_display == t("mode.it_support")
        llm.assert_called_once()
    search.assert_called_once_with("VPN?", k=3)
    assert factory.create_chain("it_support") is chain


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 500])
async def test_webhook_exact_payload_retry_metrics_and_dedup(status, caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status)

    created, failed = Mock(), Mock()
    sleep = AsyncMock()
    client = TicketClient("https://synthetic.invalid/tickets", "synthetic-hr",
                          transport=httpx.MockTransport(respond), sleep=sleep,
                          metrics=(created, failed))
    ticket = Ticket(12345, "it_support", "password=synthetic-value user_id=12345", "explicit", 0.5)
    session = {}
    result = await client.create(ticket, session=session)
    assert result.success == (status == 201)
    assert len(requests) == (1 if result.success else 3)
    assert sleep.await_args_list == ([] if result.success else [((1,), {}), ((2,), {})])
    payloads = [json.loads(request.content) for request in requests]
    assert all(payload == payloads[0] for payload in payloads)
    payload = payloads[0]
    assert set(payload) == {"ticket_id", "user_id_hash", "mode", "query", "timestamp",
                            "reason", "top_score", "notify_chat_id"}
    assert payload["ticket_id"] == ticket.ticket_id
    assert payload["user_id_hash"] == hashlib.sha256(b"12345").hexdigest()
    assert "12345" not in payload["query"] and "synthetic-value" not in payload["query"]
    assert payload["query"].count("[REDACTED]") == 2
    assert datetime.fromisoformat(payload["timestamp"]).utcoffset() == timedelta(0)
    assert payload["reason"] == "explicit" and payload["top_score"] == 0.5
    assert payload["notify_chat_id"] == "synthetic-hr"
    assert all(request.extensions["timeout"][part] == 5
               for request in requests for part in ("connect", "read", "write", "pool"))
    assert created.inc.call_count == int(result.success)
    assert failed.inc.call_count == int(not result.success)
    await client.create(ticket, session=session)
    assert len(requests) == (1 if result.success else 3)
    assert created.inc.call_count == int(result.success)
    assert failed.inc.call_count == int(not result.success)
    assert "12345" not in caplog.text and "synthetic-value" not in caplog.text
    if result.success:
        second = TicketClient("https://synthetic.invalid", transport=httpx.MockTransport(respond),
                              metrics=(created, failed))
        assert (await second.create(ticket, session=session)).duplicate
        assert len(requests) == 1


@pytest.mark.parametrize("sensitive", [
    "eyJhbGciOiJIUzI1NiJ9.synthetic.signature", "token=synthetic-value",
    "password=synthetic-value", "passphrase=synthetic-value", "user@example.invalid",
    "+1 (555) 123-4567",
])
def test_redaction(sensitive):
    assert redact(sensitive) == "[REDACTED]"


@pytest.mark.parametrize("reason", ["missing_plan", "low_score"])
def test_analytics_jsonl_utc_no_identifiers(tmp_path, reason):
    path = tmp_path / "unanswered.jsonl"
    UnansweredWriter(path).write(UnansweredEntry("it_support", reason, "token=synthetic-value", 0.2))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(record) == {"timestamp", "mode", "reason", "query_redacted", "top_score"}
    assert record["query_redacted"] == "[REDACTED]"
    assert record["reason"] == reason
    assert datetime.fromisoformat(record["timestamp"]).utcoffset() == timedelta(0)


@pytest.mark.parametrize("relative,expected", [
    ("workspace/telegram-rag-bot-src/telegram_rag_bot/langchain_adapter/rag_chains.py",
     "929918df28c47e5013b97d61d1295a082c15de946749578f61b4247d9e6f0141"),
    ("workspace/telegram-rag-bot/orchestrator/router.py",
     "ae69fefa5d9a5573bd68de1394190097a99f2fcd1457db26c084799055e4093a"),
    ("workspace/telegram-rag-bot/orchestrator/retrieval/async_faiss.py",
     "c857bc9d5b4f2d1ce0f1b795bb28891d9c99461b65ebfb8f7fd679a1137b0b13"),
    ("workspace/telegram-rag-bot-src/telegram_rag_bot/vectorstore/local_faiss.py",
     "f7bb18e7d83377f817bf6818685ac16eda88ab4759026c1131883c30b001f301"),
])
def test_protected_core_baseline_sha256(relative, expected):
    """Constants copied from original backend_rest_core_snapshot protected_hashes."""
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative


@pytest.mark.asyncio
@pytest.mark.parametrize("pairs,expected", [
    ([("zeta", 0.2), ("beta", 0.6), ("alpha", 0.6), ("beta", 0.5), ("gamma", 0.4)],
     ["alpha", "beta", "gamma"]),
    ([("beta", 0.2), ("alpha", 0.3), ("beta", 0.1)], ["alpha", "beta"]),
])
async def test_fallback_suggestions_unique_ranked_and_bounded(locale, pairs, expected):
    session = SessionManager()
    config = {"modes": {"it_support": {"display_name": "mode.it_support"}}}
    handler = TelegramHandlers(Mock(), session, config, Mock(),
                               coordinator=Mock(), modes_directory=ROOT / "config/modes")
    handler._send = AsyncMock()
    handler._analytics = AsyncMock()
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=321), effective_message=message)
    candidates = [Document(page_content=text, metadata={"score": score}) for text, score in pairs]
    await handler._low_score(update, "query", "it_support", LowScoreFallback(candidates, 0.6))
    text = handler._send.call_args.args[1]
    start = text.index(t("fallback.suggestions_header")) + len(t("fallback.suggestions_header"))
    end = text.index(t("fallback.escalation_offer"))
    assert text[start:end].strip().splitlines() == expected


@pytest.mark.parametrize("case", ["product", "legacy", "invalid-score", "invalid-url", "invalid-admins"])
def test_product_configuration_security_contract(case, monkeypatch):
    """Validate offline configuration with synthetic environment only."""
    import yaml
    from telegram_rag_bot.config_loader import ConfigLoader
    monkeypatch.setattr("os.environ", {})
    config = yaml.safe_load((ROOT / "config/config.yaml").read_text(encoding="utf-8"))
    if case == "legacy":
        config = {"telegram": {}, "orchestrator": {}, "modes": {"directory": "modes"}}
    elif case == "invalid-score":
        config["rag"]["score_threshold"] = float("nan")
    elif case == "invalid-url":
        config["integrations"]["ticketing"]["url"] = "file:///synthetic"
    elif case == "invalid-admins":
        config["ADMIN_IDS"] = [True]
    if case.startswith("invalid"):
        with pytest.raises(ValueError):
            ConfigLoader._validate_config(config)
    else:
        ConfigLoader._validate_config(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("healthy", [True, False])
async def test_status_http_endpoints_are_offline_and_truthful(healthy):
    main = importlib.import_module("telegram_rag_bot.main")
    request = SimpleNamespace(app={
        "application": SimpleNamespace(running=healthy),
        "session_manager": SimpleNamespace(use_redis=True, redis_client=object() if healthy else None),
        "rag_factory": SimpleNamespace(embeddings_provider=object() if healthy else None,
                                       vectorstore_provider=object() if healthy else None),
    })
    response = await main.health_handler(request)
    assert response.status == (200 if healthy else 503)
    data = json.loads(response.text)
    assert set(data["checks"]) == {"telegram", "redis", "embeddings", "vectorstore"}
    assert all(check["status"] == ("ok" if healthy else "unhealthy") for check in data["checks"].values())
    metrics = await main.metrics_handler(request)
    assert metrics.status == 200 and metrics.content_type == "text/plain"
    assert b"bot_query_latency_seconds" in metrics.body


def test_provider_builders_keep_order_skip_disabled_and_reject_duplicates(monkeypatch):
    main = importlib.import_module("telegram_rag_bot.main")
    monkeypatch.setattr(main, "ProviderConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    for kind in ("GigaChatProvider", "YandexGPTProvider"):
        monkeypatch.setattr(main, kind, lambda config: SimpleNamespace(config=config))

    class Router:
        def __init__(self, **kwargs):
            self.providers = []

        def add_provider(self, provider):
            self.providers.append(provider)

    monkeypatch.setattr(main, "Router", Router)
    config = {"strategy": "first-available", "providers": [
        {"name": "gigachat", "type": "GigaChatProvider", "config": {
            "api_key": "synthetic-value", "model": "fake", "scope": "fake", "verify_ssl_certs": None}},
        {"name": "disabled", "type": "GigaChatProvider", "enabled": False, "config": {}},
        {"name": "yandexgpt", "type": "YandexGPTProvider", "config": {
            "api_key": "synthetic-value", "folder_id": "synthetic", "model": "fake"}},
    ]}
    for providers in (main.build_providers_list(config), main.create_router(config).providers,
                      main.create_router(config, usage_callback=AsyncMock()).providers):
        assert [provider.config.name for provider in providers] == ["gigachat", "yandexgpt"]
        assert all(provider.config.verify_ssl is True for provider in providers)
    duplicate = deepcopy(config)
    duplicate["providers"].append(config["providers"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        main.build_providers_list(duplicate)
    with pytest.raises(ValueError, match="No enabled"):
        main.create_router({"strategy": "first-available", "providers": []})


@pytest.mark.asyncio
async def test_index_coordinator_publishes_isolated_modes_and_retains_last_success(tmp_path, monkeypatch):
    from telegram_rag_bot.hr_adapter import IndexCoordinator
    root = tmp_path / "modes"
    for mode in ("it_support", "benefits"):
        (root / mode).mkdir(parents=True)
        (root / mode / "faq.md").write_text(mode, encoding="utf-8")
    provider = HRFAISSProvider({"indices_dir": str(tmp_path / "indices")},
                              SimpleNamespace(model=SimpleNamespace(embed_documents=Mock())))
    coordinator = IndexCoordinator(provider, root)

    class Built:
        def __init__(self, text, fail=False):
            self.text, self.fail = text, fail

        def save_local(self, path):
            (Path(path) / "text").write_text(self.text)
            if self.fail:
                raise RuntimeError("synthetic storage failure")

    def build(documents, embedding):
        assert len({document.metadata["mode"] for document in documents}) == 1
        return Built(documents[0].page_content)

    monkeypatch.setattr("telegram_rag_bot.hr_adapter.FAISS.from_documents", build)
    sources = {root / mode / "faq.md": mode for mode in ("it_support", "benefits")}
    await coordinator.ingest(sources)
    for mode in ("it_support", "benefits"):
        assert (provider.indices_dir / mode / "text").read_text() == mode

    with pytest.raises(ValueError):
        await coordinator.ingest({root / "it_support/../benefits/faq.md": "it_support"})
    external = tmp_path / "outside.md"
    external.write_text("outside")
    (root / "it_support/escape.md").symlink_to(external)
    with pytest.raises(ValueError):
        await coordinator.ingest({root / "it_support/escape.md": "it_support"})
    monkeypatch.setattr("telegram_rag_bot.hr_adapter.FAISS.from_documents",
                        lambda docs, embedding: Built("replacement", fail=docs[0].metadata["mode"] == "benefits"))
    with pytest.raises(RuntimeError):
        await coordinator.ingest(sources)
    for mode in ("it_support", "benefits"):
        assert (provider.indices_dir / mode / "text").read_text() == mode


class OfflineProvider:
    def __init__(self, name, *, fails=False, healthy=True):
        self.config = SimpleNamespace(name=name, model="synthetic")
        self.fails, self.healthy = fails, healthy

    async def generate(self, prompt, params=None):
        if self.fails:
            raise ValueError("synthetic provider failure")
        return "grounded answer"

    async def health_check(self):
        return self.healthy


@pytest.mark.asyncio
async def test_observer_request_scope_counts_real_switch_only(monkeypatch):
    main = importlib.import_module("telegram_rag_bot.main")
    from orchestrator import Router
    from prometheus_client import CollectorRegistry
    from telegram_rag_bot.utils.metrics import register_metrics
    registry = CollectorRegistry()
    metrics = register_metrics(registry)
    monkeypatch.setattr(main, "LLM_REQUESTS", metrics["LLM_REQUESTS"])
    monkeypatch.setattr(main, "FALLBACK_TOTAL", metrics["FALLBACK_TOTAL"])
    health = {}
    first, second = OfflineProvider("gigachat", fails=True), OfflineProvider("yandexgpt")
    router = Router(strategy="first-available")
    router.providers = main.observe_providers([first, second], health)
    scoped = main.RequestScopedRouter(router)
    await scoped.route("a")
    assert registry.get_sample_value("fallback_total", {"type": "llm"}) == 1
    await router.providers[1].generate("direct")
    assert registry.get_sample_value("fallback_total", {"type": "llm"}) == 1
    await asyncio.gather(scoped.route("b"), scoped.route("c"))
    assert registry.get_sample_value("fallback_total", {"type": "llm"}) == 3
    assert registry.get_sample_value("llm_requests_total", {"provider": "gigachat", "status": "failure"}) == 3
    assert registry.get_sample_value("llm_requests_total", {"provider": "yandexgpt", "status": "success"}) == 4
    assert await router.providers[1].health_check()
    assert health["gigachat"] == health["yandexgpt"] == "ok"
    first.healthy = False
    await scoped.route("unhealthy first provider")
    assert registry.get_sample_value("fallback_total", {"type": "llm"}) == 3
    assert health["gigachat"] == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_bootstrap_without_live_boundaries(tmp_path, monkeypatch, failed):
    main = importlib.import_module("telegram_rag_bot.main")
    events = []
    config = {"modes_directory": str(ROOT / "config/modes"),
              "modes": {"it_support": {"diagnostics_file": "diagnostics.yaml"}},
              "retrieval": {"async_mode": False}, "i18n": {"default_locale": "ru"},
              "rag": {"score_threshold": 0.65},
              "integrations": {"ticketing": {"url": "https://synthetic.invalid"}},
              "analytics": {"unanswered_path": str(tmp_path / "missing/unanswered.jsonl")}}
    monkeypatch.setattr("os.environ", {name: "synthetic" for name in
        ("TELEGRAM_TOKEN", "GIGACHAT_KEY", "YANDEX_API_KEY", "YANDEX_FOLDER_ID")})
    monkeypatch.setattr(main.ConfigLoader, "load_config", lambda path: events.append("config") or deepcopy(config))
    monkeypatch.setattr(main, "load_locale", lambda path: events.append("locale"))
    monkeypatch.setattr(main, "register_metrics", lambda: events.append("metrics"))
    monkeypatch.setattr(main, "setup_logging", lambda config: None)
    router = SimpleNamespace(providers=[OfflineProvider("gigachat"), OfflineProvider("yandexgpt")])
    monkeypatch.setattr(main, "create_router", lambda *args, **kwargs: router)
    monkeypatch.setattr(main, "MultiLLMOrchestrator", lambda **kwargs: SimpleNamespace(**kwargs))
    factory = SimpleNamespace(embeddings_provider=object(), vectorstore_provider=None, chains={})
    monkeypatch.setattr(main, "RAGChainFactory", lambda **kwargs: factory)
    provider = SimpleNamespace()
    monkeypatch.setattr(main, "HRFAISSProvider", lambda *args, **kwargs: provider)

    class Coordinator:
        def __init__(self, candidate, *args, **kwargs):
            assert factory.vectorstore_provider is candidate is provider

        async def ingest(self, sources):
            events.append("ingest")
            assert all(mode == "it_support" for mode in sources.values())
            if failed:
                raise RuntimeError("synthetic indexing failure")

    monkeypatch.setattr(main, "IndexCoordinator", Coordinator)
    def load_graph(path):
        if failed:
            raise ValueError("synthetic invalid graph")
        return "validated graph"
    monkeypatch.setattr(main, "load_graph", load_graph)
    monkeypatch.setattr(main, "TicketClient", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(main, "UnansweredWriter", lambda path: SimpleNamespace(path=path))
    monkeypatch.setattr(main, "SessionManager", lambda **kwargs: SimpleNamespace(redis_client=None))
    monkeypatch.setattr(main, "FeedbackCollector", lambda *args: None)
    monkeypatch.setattr(main, "TelegramHandlers", lambda **kwargs: SimpleNamespace(**kwargs))
    result = await main.bootstrap_components(ROOT / "config/config.yaml")
    assert events == ["config", "locale", "metrics", "ingest"]
    assert result.handlers.diagnostics_graph == (None if failed else "validated graph")
    assert (result.runtime_state["last_reindex"] == "never") == failed
    assert all(isinstance(provider, main.ProviderObserver) for provider in router.providers)


@pytest.mark.asyncio
async def test_usage_callback_handles_dict_object_and_malformed_input(caplog):
    main = importlib.import_module("telegram_rag_bot.main")
    import logging
    data = {"provider_name": "gigachat", "model": "synthetic", "total_tokens": 5,
            "prompt_tokens": 3, "completion_tokens": 2, "cost": 0.01,
            "latency_ms": 4, "success": True}
    with caplog.at_level(logging.INFO):
        await main.track_usage(data)
        await main.track_usage(SimpleNamespace(**data))
        await main.track_usage({})
    records = [record for record in caplog.records if record.message == "llm_usage_tracked"]
    assert len(records) == 2 and records[0].usage == records[1].usage
    assert "Usage tracking callback failed" in caplog.text


def hr_runtime():
    """Construct production handlers with in-memory sessions and fake boundaries."""
    from telegram_rag_bot.diagnostics import load_graph
    message = SimpleNamespace(text="query", reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
    update = SimpleNamespace(message=message, effective_message=message,
                             effective_user=SimpleNamespace(id=123), callback_query=None)
    config = {"ADMIN_IDS": [123], "modes": {"it_support": {
        "display_name": "mode.it_support", "source_titles": {"faq.md": "mode.it_support"}}}}
    factory = SimpleNamespace(create_chain=Mock(), vectorstore_provider=SimpleNamespace(
        load_index=Mock(return_value=SimpleNamespace(index=SimpleNamespace(ntotal=5)))))
    handler = TelegramHandlers(factory, SessionManager(), config, Mock(),
        coordinator=SimpleNamespace(ingest=AsyncMock(return_value={"it_support": 3})),
        modes_directory=ROOT / "config/modes",
        diagnostics_graph=load_graph(ROOT / "config/modes/it_support/diagnostics.yaml"))
    handler._send = AsyncMock()
    return handler, update


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,path", [("vpn", [1]), ("vpn", [0, 0]), ("vpn", [0, 1]),
                                           ("mail", [0]), ("mail", [1, 0]), ("mail", [1, 1])])
async def test_diagnostic_callbacks_follow_all_terminal_paths(locale, scenario, path):
    handler, update = hr_runtime()
    await handler.session_manager.record_rag_fallback(123)
    update.callback_query = SimpleNamespace(data=f"diag:start:{scenario}", answer=AsyncMock())
    await handler.handle_callback_query(update, None)
    for choice in path:
        assert (await handler.session_manager.get_session(123))["diagnostics_state"]["scenario"] == scenario
        update.callback_query.data = f"diag:choice:{choice}"
        await handler.handle_callback_query(update, None)
    session = await handler.session_manager.get_session(123)
    assert session["diagnostics_state"] is None
    assert session["rag_fallback_streak"] == 1
    assert "VPN" in handler._send.call_args.args[1] if scenario == "vpn" else "IT" in handler._send.call_args.args[1]
    update.callback_query.data = "diag:choice:99"
    await handler.handle_callback_query(update, None)
    assert handler._send.call_args.args[1] == t("diagnostics.invalid_choice")


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [True, False])
async def test_admin_reindex_and_status_fields(locale, monkeypatch, admin):
    handler, update = hr_runtime()
    handler.runtime_state["started_at"] = 123.0
    monkeypatch.setattr("telegram_rag_bot.handlers.time.monotonic", lambda: 123.0)
    if not admin:
        handler.config["ADMIN_IDS"] = []
    monkeypatch.setattr("telegram_rag_bot.handlers.version", lambda package: "0.14.6")
    await handler.cmd_reindex(update, None)
    await handler.cmd_status(update, None)
    if admin:
        handler.coordinator.ingest.assert_awaited_once()
        text = handler._send.call_args.args[1]
        expected = t("status.summary", mode="it_support", version="0.14.6", gigachat="fail",
                     yandexgpt="fail", documents=5, uptime_seconds=0,
                     last_reindex=handler.runtime_state["last_reindex"])
        assert text == expected
        assert handler.runtime_state["last_reindex"] != "never"
    else:
        handler.coordinator.ingest.assert_not_called()
        assert handler._send.call_args.args[1] == t("admin.denied")


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_handlers_ticket_operation_is_stable_and_deduplicated(locale, success):
    handler, update = hr_runtime()
    handler.ticket_client = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(success=success, ticket_id="synthetic-uuid")))
    await handler._escalate(update, "explicit", query="query")
    assert handler.ticket_client.create.call_args.args[0].reason == "explicit"
    if success:
        await handler._escalate(update, "explicit", query="query")
        handler.ticket_client.create.assert_awaited_once()
        assert (await handler.session_manager.get_session(123))["active_ticket_uuid"] == "synthetic-uuid"
        await handler._escalate(update, "explicit", query="new query")
        assert handler.ticket_client.create.await_count == 2
    else:
        assert handler._send.call_args.args[1] == t("ticket.failed")


@pytest.mark.asyncio
async def test_observed_router_reload_keeps_observers_and_health_cache(monkeypatch):
    main = importlib.import_module("telegram_rag_bot.main")
    cache = {"gigachat": "fail"}
    router = SimpleNamespace(providers=[main.ProviderObserver(OfflineProvider("gigachat"), cache)],
                             update_providers=AsyncMock())
    factory = SimpleNamespace(chains={"it_support": object()})
    provider = OfflineProvider("gigachat")
    monkeypatch.setattr(main, "router", router)
    monkeypatch.setattr(main, "rag_factory", factory)
    monkeypatch.setattr(main, "last_reload_time", 0)
    monkeypatch.setattr("os.environ", {})
    monkeypatch.setattr(main.ConfigLoader, "load_config", lambda path: {"orchestrator": {"providers": []}})
    monkeypatch.setattr(main, "build_providers_list", lambda config: [provider])
    await main._reload_config_async()
    router.update_providers.assert_awaited_once()
    observed = router.update_providers.call_args.args[0][0]
    assert isinstance(observed, main.ProviderObserver)
    assert observed.provider is provider and observed.health_cache is cache
    assert not factory.chains


@pytest.mark.parametrize("style", ["text", "json"])
def test_runtime_logging_formatter_and_level(style, monkeypatch):
    import logging
    from telegram_rag_bot.utils.logger import setup_structured_logging
    root = logging.getLogger()
    # Keep pytest's capture handlers intact after exercising actual setup.
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    monkeypatch.setattr(root, "level", root.level)
    main = importlib.import_module("telegram_rag_bot.main")
    main.setup_logging({"logging": {"format": style, "level": "WARNING"}})
    assert root.level == logging.WARNING and len(root.handlers) == 1
    record = logging.LogRecord("synthetic", logging.WARNING, __file__, 1, "message", (), None)
    rendered = root.handlers[0].formatter.format(record)
    if style == "json":
        assert json.loads(rendered)["message"] == "message"
    else:
        assert "[WARNING]" in rendered and "message" in rendered


@pytest.mark.parametrize("value,expected", [("[1,2]", [1, 2]), ("1,2", [1, 2]), ("", []),
                                           ("${SYNTHETIC_IDS}", "${SYNTHETIC_IDS}")])
def test_admin_environment_whitelist_parse(value, expected):
    from telegram_rag_bot.config_loader import ConfigLoader
    assert ConfigLoader._parse_admin_ids(value) == expected


@pytest.mark.parametrize("value", ["[true]", "[\"1\"]", "1,word", "[broken", "{}"])
def test_admin_environment_whitelist_rejects_bad_values(value):
    from telegram_rag_bot.config_loader import ConfigLoader
    with pytest.raises(ValueError):
        ConfigLoader._parse_admin_ids(value)


def test_embedding_wrapper_reuses_async_provider_without_live_io():
    from telegram_rag_bot.langchain_adapter.rag_chains import LangChainEmbeddingsWrapper
    provider = SimpleNamespace(embed_documents=AsyncMock(return_value=[[1.0, 0.0]]),
                               embed_query=AsyncMock(return_value=[1.0, 0.0]))
    wrapper = LangChainEmbeddingsWrapper(provider)
    assert wrapper.embed_documents(["document"]) == [[1.0, 0.0]]
    assert wrapper.embed_query("question") == [1.0, 0.0]
    provider.embed_documents.assert_awaited_once_with(["document"])
    provider.embed_query.assert_awaited_once_with("question")


@pytest.mark.asyncio
async def test_hr_cache_save_and_delete_preserve_freshness(tmp_path, monkeypatch):
    class Store:
        def __init__(self, text):
            self.text = text

        def save_local(self, path):
            (Path(path) / "text").write_text(self.text)

        def similarity_search_with_score(self, query, k):
            return [(Document(page_content=self.text, metadata={"source": "faq.md"}), 0)]

    @lru_cache(maxsize=10)
    def fake_load(provider, mode):
        store = Store((provider.indices_dir / mode / "text").read_text())
        store.index = SimpleNamespace(metric_type=1)
        return store

    monkeypatch.setattr(LocalFAISSProvider, "load_index", fake_load)
    factory = SimpleNamespace(chains={"it_support": object()})
    provider = HRFAISSProvider({"indices_dir": str(tmp_path)}, SimpleNamespace(), rag_factory=factory)
    provider.save_index(Store("old"), "it_support")
    assert provider.load_index("it_support").as_retriever().invoke("query")[0].page_content == "old"
    provider.save_index(Store("new"), "it_support")
    assert provider.load_index("it_support").as_retriever().invoke("query")[0].page_content == "new"
    assert factory.chains == {}
    provider.load_index.cache_clear()
    await provider.delete_index("it_support")
    assert not (tmp_path / "it_support").exists()
    with pytest.raises(FileNotFoundError):
        provider.load_index("it_support")


@pytest.mark.parametrize("distance,metric", [(float("nan"), 1), (-1, 1), ("bad", 1), (0, 0)])
def test_hr_invalid_score_fails_closed_once(distance, metric):
    from telegram_rag_bot.hr_adapter import _Facade
    search = Mock(return_value=[(Document(page_content="untrusted"), distance)])
    store = SimpleNamespace(index=SimpleNamespace(metric_type=metric), similarity_search_with_score=search)
    with pytest.raises(LowScoreFallback) as failure:
        _Facade(store, 0.65).as_retriever().invoke("query")
    assert failure.value.top_score == 0.0 and failure.value.candidates == []
    search.assert_called_once_with("query", k=3)


@pytest.mark.asyncio
async def test_observer_health_exception_keeps_failure_native():
    main = importlib.import_module("telegram_rag_bot.main")
    provider = OfflineProvider("gigachat")
    error = RuntimeError("synthetic health failure")
    provider.health_check = AsyncMock(side_effect=error)
    cache = {}
    with pytest.raises(RuntimeError) as failure:
        await main.ProviderObserver(provider, cache).health_check()
    assert failure.value is error and cache["gigachat"] == "fail"
    assert datetime.fromisoformat(cache["last_check_iso"]["gigachat"]).utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_active_user_metrics_task_cancels_cleanly(monkeypatch):
    main = importlib.import_module("telegram_rag_bot.main")
    manager = SimpleNamespace(get_active_users_count=Mock(return_value=4))
    gauge = Mock()
    monkeypatch.setattr("telegram_rag_bot.utils.metrics.ACTIVE_USERS", gauge)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    await main.update_active_users_metric(manager)
    gauge.set.assert_called_once_with(4)
    sleep.assert_awaited_once_with(60)


@pytest.mark.parametrize("shutdown", [True, False])
def test_sighup_is_nonfatal_when_no_loop_or_shutdown(monkeypatch, caplog, shutdown):
    main = importlib.import_module("telegram_rag_bot.main")
    monkeypatch.setattr(main, "shutdown_in_progress", shutdown)
    monkeypatch.setattr(main.asyncio, "get_event_loop", Mock(side_effect=RuntimeError("synthetic no loop")))
    monkeypatch.setattr(main.asyncio, "get_running_loop", Mock(side_effect=RuntimeError("synthetic no loop")))
    main._handle_sighup(1, None)
    if shutdown:
        main.asyncio.get_event_loop.assert_not_called()
    else:
        assert "no event loop" in caplog.text


def test_metrics_registry_isolated_idempotent_and_labels_are_bounded():
    from prometheus_client import CollectorRegistry, Gauge
    from telegram_rag_bot.utils.metrics import register_metrics
    registry = CollectorRegistry()
    first, second = register_metrics(registry), register_metrics(registry)
    assert first["LLM_REQUESTS"] is second["LLM_REQUESTS"]
    for args, kwargs in [((), {"provider": "raw-id", "status": "success"}),
                         ((), {"user_id": "123"}), (("gigachat",), {"status": "success"}),
                         (("gigachat",), {}), (("gigachat", "success", "extra"), {})]:
        with pytest.raises(ValueError):
            first["LLM_REQUESTS"].labels(*args, **kwargs)
    collision = CollectorRegistry()
    Gauge("bot_query_latency_seconds", "incompatible schema", registry=collision)
    with pytest.raises(ValueError, match="incompatible"):
        register_metrics(collision)
