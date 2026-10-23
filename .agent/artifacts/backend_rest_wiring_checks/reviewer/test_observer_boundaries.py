"""Independent observer boundaries: no live clients or environment access."""
import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
wiring = importlib.import_module("telegram_rag_bot.main")


class Counter:
    def __init__(self):
        self.events = []

    def labels(self, **labels):
        return SimpleNamespace(inc=lambda: self.events.append(labels))


@pytest.mark.asyncio
async def test_failed_request_then_direct_yandex_and_concurrent_isolation(monkeypatch):
    counter = Counter()
    attempts = Counter()
    monkeypatch.setattr(wiring, "FALLBACK_TOTAL", counter)
    monkeypatch.setattr(wiring, "LLM_REQUESTS", attempts)
    gigachat = wiring.ProviderObserver(SimpleNamespace(config=SimpleNamespace(name="gigachat"), generate=AsyncMock(side_effect=RuntimeError("synthetic"))), {})
    yandex = wiring.ProviderObserver(SimpleNamespace(config=SimpleNamespace(name="yandexgpt"), generate=AsyncMock(return_value="ok")), {})

    async def failed(prompt, params):
        return await gigachat.generate(prompt, params)

    with pytest.raises(RuntimeError):
        await wiring.RequestScopedRouter(SimpleNamespace(route=failed)).route("x")
    await yandex.generate("direct")
    assert counter.events == []

    barrier = asyncio.Event()

    async def fallback(prompt, params):
        try:
            await gigachat.generate(prompt, params)
        except RuntimeError:
            barrier.set()
            await asyncio.sleep(0)
            return await yandex.generate(prompt, params)

    async def direct(prompt, params):
        await barrier.wait()
        return await yandex.generate(prompt, params)

    await asyncio.gather(wiring.RequestScopedRouter(SimpleNamespace(route=fallback)).route("fallback"), wiring.RequestScopedRouter(SimpleNamespace(route=direct)).route("direct"))
    assert counter.events == [{"type": "llm"}]
    assert len(attempts.events) == 5


@pytest.mark.asyncio
async def test_health_exception_propagates_without_generation_metrics(monkeypatch):
    counter = Counter()
    monkeypatch.setattr(wiring, "LLM_REQUESTS", counter)
    cache = {}
    observer = wiring.ProviderObserver(SimpleNamespace(config=SimpleNamespace(name="gigachat"), health_check=AsyncMock(side_effect=RuntimeError("synthetic"))), cache)
    with pytest.raises(RuntimeError):
        await observer.health_check()
    assert cache["gigachat"] == "fail"
    assert cache["last_check_iso"]["gigachat"]
    assert not counter.events


@pytest.mark.asyncio
async def test_cancellation_restores_request_context():
    async def cancelled(prompt, params):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await wiring.RequestScopedRouter(SimpleNamespace(route=cancelled)).route("x")
    assert wiring._generation_state.get() is None


@pytest.mark.asyncio
async def test_cancelled_generation_counts_failure_and_propagates(monkeypatch):
    counter = Counter()
    monkeypatch.setattr(wiring, "LLM_REQUESTS", counter)
    provider = SimpleNamespace(config=SimpleNamespace(name="gigachat"), generate=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await wiring.ProviderObserver(provider, {}).generate("synthetic")
    assert counter.events == [{"provider": "gigachat", "status": "failure"}]


@pytest.mark.asyncio
async def test_cancelled_health_records_fail_without_generation_count(monkeypatch):
    counter, cache = Counter(), {}
    monkeypatch.setattr(wiring, "LLM_REQUESTS", counter)
    provider = SimpleNamespace(config=SimpleNamespace(name="gigachat"), health_check=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await wiring.ProviderObserver(provider, cache).health_check()
    assert cache["gigachat"] == "fail"
    assert cache["last_check_iso"]["gigachat"]
    assert counter.events == []
