"""
Main entry point for Telegram bot with Multi-LLM-Orchestrator integration.

This module initializes all components (Router, RAG chains, session manager,
handlers) and runs the Telegram bot application.
"""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace
import logging
import signal
import time
from typing import Awaitable, Callable, Dict, Any, List, Optional, TYPE_CHECKING

from aiohttp import web
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from prometheus_client import generate_latest

from orchestrator import Router

from telegram_rag_bot.i18n import load_locale
from telegram_rag_bot.hr_adapter import HRFAISSProvider, IndexCoordinator
from telegram_rag_bot.diagnostics import load_graph
from telegram_rag_bot.utils.metrics import register_metrics, LLM_REQUESTS, FALLBACK_TOTAL
from integrations.ticketing import TicketClient
from analytics.writer import UnansweredWriter
from telegram_rag_bot.config_loader import ConfigLoader
from telegram_rag_bot.langchain_adapter.rag_chains import RAGChainFactory
from telegram_rag_bot.utils.session_manager import SessionManager
from telegram_rag_bot.utils.feedback_collector import FeedbackCollector
from telegram_rag_bot.handlers import TelegramHandlers
from telegram_rag_bot.usage_tracking import (
    create_track_usage_callback as create_track_usage_callback,
    _send_usage_to_platform as _send_usage_to_platform,
)

from orchestrator import Router

if TYPE_CHECKING:
    from orchestrator import UsageData
else:
    # Temporary type stub for v0.7.6 compatibility (will be available after pip install)
    try:
        from orchestrator import UsageData
    except ImportError:
        # Fallback for v0.7.5: create a minimal type stub
        from typing import TypedDict

        class UsageData(TypedDict):  # type: ignore
            """Usage data from Router (tokens, cost, latency, success status)."""

            provider_name: str
            model: str
            total_tokens: int
            prompt_tokens: int
            completion_tokens: int
            cost: float
            latency_ms: int
            success: bool


from orchestrator.providers import GigaChatProvider, YandexGPTProvider, ProviderConfig
from orchestrator.langchain import MultiLLMOrchestrator

logger = logging.getLogger(__name__)

# Global state для SIGHUP handler
reload_lock = asyncio.Lock()  # Prevent concurrent reloads
last_reload_time = 0.0  # For debouncing
shutdown_in_progress = False  # Flag для shutdown (игнорировать SIGHUP)
DEBOUNCE_SECONDS = 5.0  # Debounce duration

# Global references для SIGHUP handler (устанавливаются в main())
router: Router = None  # type: ignore
rag_factory: RAGChainFactory = None  # type: ignore

# Global references для SIGHUP handler (устанавливаются в main())
router: Router = None  # type: ignore
rag_factory: RAGChainFactory = None  # type: ignore



_generation_state = ContextVar("hr_generation_state", default=None)


@contextmanager
def generation_scope():
    """One model request only; never let failed attempts leak to another request."""
    token = _generation_state.set({"failed_gigachat": False, "switched": False})
    try:
        yield
    finally:
        _generation_state.reset(token)


class ProviderObserver:
    """Transparent provider decorator; health checks are not generation attempts."""
    def __init__(self, provider, health_cache):
        self.provider = provider
        self.health_cache = health_cache

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def generate(self, prompt, params=None):
        name = self.config.name
        state = _generation_state.get()
        if name == "yandexgpt" and state is not None and state["failed_gigachat"] and not state["switched"]:
            FALLBACK_TOTAL.labels(type="llm").inc()
            state["switched"] = True
        try:
            result = await self.provider.generate(prompt, params)
        except (Exception, asyncio.CancelledError):
            LLM_REQUESTS.labels(provider=name, status="failure").inc()
            if name == "gigachat" and state is not None:
                state["failed_gigachat"] = True
            raise
        LLM_REQUESTS.labels(provider=name, status="success").inc()
        return result

    async def health_check(self):
        name = self.config.name
        try:
            result = await self.provider.health_check()
        except (Exception, asyncio.CancelledError):
            self.health_cache[name] = "fail"
            self.health_cache.setdefault("last_check_iso", {})[name] = datetime.now(timezone.utc).isoformat()
            raise
        self.health_cache[name] = "ok" if result else "fail"
        self.health_cache.setdefault("last_check_iso", {})[name] = datetime.now(timezone.utc).isoformat()
        return result


class RequestScopedRouter(Router):
    """Forward to the unchanged Router with one context per route invocation.

    A forwarding Router subtype satisfies the existing LangChain model's type
    contract. It neither selects providers nor implements fallback: the original
    Router owns both, including when LangChain creates its own worker thread.
    """
    def __init__(self, delegate):
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    async def route(self, prompt, params=None):
        with generation_scope():
            return await self.delegate.route(prompt, params)


def normalize_runtime_config(config):
    """Add product bootstrap defaults without altering the ConfigLoader contract.

    Only the named runtime environment variables below provide credentials.
    This function does not read credential files. Legacy sections are retained.
    """
    config = deepcopy(config)
    config.setdefault("telegram", {"token": os.environ.get("TELEGRAM_TOKEN", "")})
    if "orchestrator" not in config:
        providers = []
        for name in config.get("llm", {}).get("providers", ["gigachat", "yandexgpt"]):
            if name == "gigachat":
                item = {"api_key": os.environ.get("GIGACHAT_KEY", ""), "model": "GigaChat", "scope": "GIGACHAT_API_PERS"}
                kind = "GigaChatProvider"
            elif name == "yandexgpt":
                item = {"api_key": os.environ.get("YANDEX_API_KEY", ""), "folder_id": os.environ.get("YANDEX_FOLDER_ID", ""), "model": "yandexgpt/latest"}
                kind = "YandexGPTProvider"
            else:
                raise ValueError("unsupported product LLM provider")
            providers.append({"name": name, "type": kind, "enabled": True, "config": item})
        config["orchestrator"] = {"strategy": "first-available", "providers": providers}
    config.setdefault("embeddings", {"type": "gigachat", "gigachat": {"api_key": os.environ.get("GIGACHAT_KEY", ""), "model": "Embeddings", "scope": "GIGACHAT_API_PERS"}})
    config.setdefault("vectorstore", {"type": "faiss", "faiss": {"indices_dir": ".faiss_indices"}})
    config.setdefault("langchain", {"chunk_size": 1000, "chunk_overlap": 100})
    config.setdefault("storage", {"sessions": {"url": None, "ttl_seconds": config.get("session", {}).get("ttl_seconds", 86400)}})
    if config.get("retrieval", {}).get("async_mode", False) is not False:
        raise ValueError("HR retrieval requires retrieval.async_mode=False")
    if config["vectorstore"].get("type") != "faiss":
        raise ValueError("HR retrieval requires the FAISS provider")
    return config


def observe_providers(providers, health_cache):
    # The core metric facade deliberately restricts labels to these two names.
    for provider in providers:
        if provider.config.name not in {"gigachat", "yandexgpt"}:
            raise ValueError("HR provider names must be gigachat or yandexgpt")
    return [provider if isinstance(provider, ProviderObserver) else ProviderObserver(provider, health_cache) for provider in providers]


def collect_sources(modes_directory, modes):
    """Collect only Markdown files within active canonical mode bundles."""
    root = Path(modes_directory).resolve(strict=True)
    result = {}
    for mode in modes:
        bundle = root / mode
        if not bundle.resolve(strict=True).is_relative_to(root):
            raise ValueError("mode source escapes configured root")
        for path in sorted(bundle.rglob("*.md")):
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(bundle.resolve()) or not resolved.is_file():
                raise ValueError("mode source escapes bundle")
            result[path] = mode
    return result


async def bootstrap_components(config_path="config/config.yaml"):
    """Initialize components without starting Telegram, HTTP or background tasks.

    Tests inject fakes at each boundary, including ConfigLoader; no live network
    is necessary to verify initialization order and startup failure behavior.
    """
    config_path = Path(config_path).resolve()
    config = ConfigLoader.load_config(str(config_path))
    locale = config.get("i18n", {}).get("default_locale", "ru")
    load_locale(config_path.parent / "i18n" / f"{locale}.yaml")
    register_metrics()
    config = normalize_runtime_config(config)
    setup_logging(config)
    health_cache = {"gigachat": "fail", "yandexgpt": "fail", "last_check_iso": {}}
    platform = config.get("platform", {})
    usage_callback = create_track_usage_callback(tenant_id=platform.get("tenant_id", ""), callback_url=platform.get("callback_url"), platform_key_id=platform.get("platform_key_id"))
    local_router = create_router(config["orchestrator"], usage_callback=usage_callback)
    # Do not start Router's Prometheus exporter: it writes the same LLM series.
    llm = MultiLLMOrchestrator(router=RequestScopedRouter(local_router))
    factory = RAGChainFactory(llm=llm, embeddings_config=config["embeddings"], vectorstore_config=config["vectorstore"], chunk_config=config["langchain"], modes=config["modes"], retrieval_config=config.get("retrieval", {}))
    provider_config = {**config["vectorstore"].get("faiss", {}), **config.get("rag", {})}
    provider = HRFAISSProvider(provider_config, factory.embeddings_provider, rag_factory=factory, score_threshold=config.get("rag", {}).get("score_threshold", 0.65))
    factory.vectorstore_provider = provider
    modes_directory = Path(config.get("modes_directory", config_path.parent / "modes")).resolve()
    coordinator = IndexCoordinator(provider, modes_directory, chunk_size=config["langchain"]["chunk_size"], chunk_overlap=config["langchain"]["chunk_overlap"])
    state = {"started_at": time.monotonic(), "last_reindex": "never"}
    try:
        await coordinator.ingest(collect_sources(modes_directory, config["modes"]))
        state["last_reindex"] = datetime.now(timezone.utc).isoformat()
    except Exception:
        logger.error("initial HR indexing failed; startup continues without a fresh index")
    ticketing = config.get("integrations", {}).get("ticketing", {})
    try:
        ticket_client = TicketClient(url=ticketing.get("url", ""), hr_chat_id=ticketing.get("hr_chat_id") or None)
    except ValueError:
        ticket_client = None
        logger.warning("ticket webhook unavailable; escalation will report failure")
    path = Path(config.get("analytics", {}).get("unanswered_path", "analytics/unanswered.jsonl"))
    if not path.parent.is_dir():
        logger.warning("analytics parent missing; writes unavailable until runtime volume is mounted")
    writer = UnansweredWriter(path)
    graph = None
    diagnostic_file = config["modes"].get("it_support", {}).get("diagnostics_file", "diagnostics.yaml")
    graph_path = modes_directory / "it_support" / diagnostic_file
    if graph_path.is_file():
        try:
            graph = load_graph(graph_path)
        except Exception:
            logger.error("diagnostic graph unavailable; startup continues")
    local_router.providers = observe_providers(local_router.providers, health_cache)
    sessions = SessionManager(redis_url=config["storage"]["sessions"].get("url"), ttl_seconds=config["storage"]["sessions"]["ttl_seconds"])
    feedback = FeedbackCollector(sessions.redis_client)
    handlers = TelegramHandlers(rag_factory=factory, session_manager=sessions, config=config, feedback_collector=feedback, coordinator=coordinator, ticket_client=ticket_client, unanswered_writer=writer, diagnostics_graph=graph, health_cache=health_cache, modes_directory=modes_directory, runtime_state=state, request_scope=generation_scope)
    return SimpleNamespace(config=config, router=local_router, rag_factory=factory, session_manager=sessions, handlers=handlers, health_cache=health_cache, runtime_state=state)


def register_command_handlers(application, handlers):
    from telegram.ext import CallbackQueryHandler
    for command, method in (("start", handlers.cmd_start), ("mode", handlers.cmd_set_mode), ("reindex", handlers.cmd_reindex), ("reload_faq", handlers.cmd_reindex), ("status", handlers.cmd_status), ("help", handlers.cmd_help), ("feedback", handlers.cmd_feedback), ("escalate", handlers.cmd_escalate), ("diagnostics", handlers.cmd_diagnostics)):
        application.add_handler(CommandHandler(command, method))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))
    application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))


def setup_logging(config: Dict[str, Any]) -> None:
    """
    Setup structured logging from configuration.

    Configures root logger with format and level from config.yaml.
    Supports both JSON (production) and text (development) formats.

    Args:
        config: Full configuration dictionary from ConfigLoader
    """
    from telegram_rag_bot.utils.logger import setup_structured_logging

    log_config = config.get("logging", {})
    log_format = log_config.get("format", "text")
    log_level_str = log_config.get("level", "INFO").upper()

    # Safe conversion: getattr(logging, "INFO", logging.INFO)
    log_level = getattr(logging, log_level_str, logging.INFO)

    setup_structured_logging(log_format=log_format, level=log_level)


async def track_usage(data: UsageData) -> None:
    """Track LLM usage for billing and analytics.

    This callback is invoked for every LLM request (success or failure).
    Errors are logged but don't interrupt the main request flow (fail-silent).

    **Evolution roadmap**:
    - v0.8.9 (current): Structured logs only
    - v0.9.0 (Week 4+): HTTP POST to Platform API (when callback_url in config)
    - v0.10.0 (Week 5+): Retry queue + ElasticSearch integration

    Args:
        data: Usage data from Router (tokens, cost, latency, success status)
            Can be a dict-like object or object with attributes.
    """
    try:
        # Support both dict-like and object access (for TypedDict compatibility)
        provider_name = (
            data.get("provider_name") if isinstance(data, dict) else data.provider_name
        )
        model = data.get("model") if isinstance(data, dict) else data.model
        total_tokens = (
            data.get("total_tokens") if isinstance(data, dict) else data.total_tokens
        )
        prompt_tokens = (
            data.get("prompt_tokens") if isinstance(data, dict) else data.prompt_tokens
        )
        completion_tokens = (
            data.get("completion_tokens")
            if isinstance(data, dict)
            else data.completion_tokens
        )
        cost = data.get("cost") if isinstance(data, dict) else data.cost
        latency_ms = (
            data.get("latency_ms") if isinstance(data, dict) else data.latency_ms
        )
        success = data.get("success") if isinstance(data, dict) else data.success

        logger.info(
            "llm_usage_tracked",
            extra={
                "usage": {
                    "provider": provider_name,
                    "model": model,
                    "total_tokens": total_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_rub": round(cost, 4),
                    "latency_ms": latency_ms,
                    "success": success,
                }
            },
        )
    except Exception as e:
        logger.warning(f"Usage tracking callback failed: {e}", exc_info=True)


def create_router(
    orchestrator_config: Dict[str, Any],
    usage_callback: Optional[Callable[[UsageData], Awaitable[None]]] = None,
) -> Router:
    """Create and configure Multi-LLM-Orchestrator Router.

    Args:
        orchestrator_config: Configuration dict with strategy and providers.
        usage_callback: Optional callback function for tracking LLM usage.
            If None, Router is created without usage tracking (backward compatible).

    Returns:
        Configured Router instance with enabled providers.

    Raises:
        ValueError: If no enabled providers are configured.
    """
    # Router v0.7.6+ supports usage_callback, v0.7.5 doesn't
    # Use try/except for backward compatibility
    if usage_callback:
        try:
            router = Router(
                strategy=orchestrator_config["strategy"],
                usage_callback=usage_callback,
            )
        except TypeError:
            # Fallback for v0.7.5 (usage_callback not supported)
            router = Router(strategy=orchestrator_config["strategy"])
            logger.warning(
                "Usage tracking callback not available (requires multi-llm-orchestrator>=0.7.6)"
            )
    else:
        # No callback provided → create Router without usage tracking
        router = Router(strategy=orchestrator_config["strategy"])

    for provider_cfg in orchestrator_config["providers"]:
        # Skip disabled providers
        if not provider_cfg.get("enabled", True):
            logger.info(f"Skipping disabled provider: {provider_cfg['name']}")
            continue

        # Create GigaChat provider
        if provider_cfg["type"] == "GigaChatProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                model=provider_cfg["config"]["model"],
                scope=provider_cfg["config"]["scope"],
                verify_ssl=verify_ssl,
            )
            router.add_provider(GigaChatProvider(config))
            logger.info(f"Added provider: {provider_cfg['name']} (GigaChat)")

        # Create YandexGPT provider
        elif provider_cfg["type"] == "YandexGPTProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                folder_id=provider_cfg["config"]["folder_id"],
                model=provider_cfg["config"]["model"],
                verify_ssl=verify_ssl,
            )
            router.add_provider(YandexGPTProvider(config))
            logger.info(f"Added provider: {provider_cfg['name']} (YandexGPT)")

    # Bug #3: router.providers всегда список (не генератор) в Multi-LLM-Orchestrator v0.7.0
    # Ensure at least one provider is enabled
    provider_count = len(router.providers)

    if provider_count == 0:
        raise ValueError("No enabled providers configured in config.yaml")

    return router


def build_providers_list(orchestrator_config: Dict[str, Any]) -> List[Any]:
    """
    Build list of Provider objects from config (for update_providers).

    Args:
        orchestrator_config: orchestrator section from config.yaml

    Returns:
        List of Provider objects (GigaChatProvider, YandexGPTProvider, ...)

    Raises:
        ValueError: If duplicate provider names found
    """
    providers = []
    provider_names = set()  # For duplicate detection

    for provider_cfg in orchestrator_config["providers"]:
        # Skip disabled providers
        if not provider_cfg.get("enabled", True):
            logger.debug(f"Skipping disabled provider: {provider_cfg['name']}")
            continue

        name = provider_cfg["name"]
        if name in provider_names:
            raise ValueError(f"Duplicate provider name: {name}")
        provider_names.add(name)

        # Create GigaChat provider
        if provider_cfg["type"] == "GigaChatProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                model=provider_cfg["config"]["model"],
                scope=provider_cfg["config"]["scope"],
                verify_ssl=verify_ssl,
            )
            providers.append(GigaChatProvider(config))
            logger.debug(f"Built provider: {provider_cfg['name']} (GigaChat)")

        # Create YandexGPT provider
        elif provider_cfg["type"] == "YandexGPTProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                folder_id=provider_cfg["config"]["folder_id"],
                model=provider_cfg["config"]["model"],
                verify_ssl=verify_ssl,
            )
            providers.append(YandexGPTProvider(config))
            logger.debug(f"Built provider: {provider_cfg['name']} (YandexGPT)")

    return providers


async def _reload_config_async() -> None:
    """
    Reload config.yaml and update Router providers without downtime.

    Steps:
    1. Acquire reload_lock (prevent concurrent reloads)
    2. Debounce check (ignore if reloaded <5s ago)
    3. Re-read config.yaml
    4. Build new providers list
    5. Await router.update_providers(new_providers, preserve_metrics=False)
    6. Clear chains cache (rag_factory.chains.clear())
    7. Log success

    Error handling:
    - Config parse error → log warning, keep old config
    - Env var missing → log warning, keep old config
    - update_providers() exception → log error, keep old config
    - Bot MUST NOT crash on reload failure
    """
    global router, rag_factory, last_reload_time

    async with reload_lock:
        # Debounce check
        now = time.time()
        if now - last_reload_time < DEBOUNCE_SECONDS:
            logger.warning(f"⚠️ SIGHUP ignored (reload <{DEBOUNCE_SECONDS}s ago)")
            return

        last_reload_time = now

        try:
            # Re-read config.yaml
            logger.info("🔄 Reloading config.yaml...")
            new_config = normalize_runtime_config(ConfigLoader.load_config("config/config.yaml"))

            # Build new providers list
            new_providers = build_providers_list(new_config["orchestrator"])
            existing_observer = next((p for p in router.providers if isinstance(p, ProviderObserver)), None)
            # HR routers retain observation; raw legacy routers keep their contract.
            if existing_observer is not None:
                new_providers = observe_providers(new_providers, existing_observer.health_cache)

            # Validate non-empty
            if not new_providers:
                logger.error("❌ No enabled providers in new config")
                logger.warning("⚠️ Skipping reload (keeping old configuration)")
                return

            # Update router providers
            await router.update_providers(new_providers, preserve_metrics=False)
            logger.info(f"✅ Router updated with {len(new_providers)} provider(s)")

            # Clear chains cache (new chains will use updated providers via router)
            rag_factory.chains.clear()
            logger.info("✅ RAG chains cache cleared")

            logger.info("✅ Config reloaded successfully")

        except ValueError as e:
            # Config parse error or validation error
            logger.warning(f"⚠️ Config reload failed (validation error): {e}")
            logger.warning("⚠️ Continuing with old configuration")
        except FileNotFoundError as e:
            # Config file not found
            logger.error(f"❌ Config file not found: {e}")
            logger.warning("⚠️ Continuing with old configuration")
        except Exception as e:
            # Any other error (update_providers exception, etc.)
            logger.error(f"❌ Config reload failed: {e}", exc_info=True)
            logger.warning("⚠️ Continuing with old configuration")


def _handle_sighup(signum, frame) -> None:
    """
    Handle SIGHUP signal for config reload (sync, schedules async task).

    Args:
        signum: Signal number (SIGHUP)
        frame: Current stack frame
    """
    global shutdown_in_progress

    if shutdown_in_progress:
        logger.warning("⚠️ SIGHUP ignored (shutdown in progress)")
        return

    logger.info(f"Received SIGHUP signal ({signum}), scheduling config reload...")

    try:
        # Get event loop (may raise RuntimeError if no loop running)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Loop is running, schedule task
            asyncio.create_task(_reload_config_async())
        else:
            # Loop not running, use run_coroutine_threadsafe
            asyncio.run_coroutine_threadsafe(_reload_config_async(), loop)
    except RuntimeError:
        # No event loop available, try to get running loop
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(_reload_config_async())
        except RuntimeError:
            logger.error("❌ No event loop available for config reload")
            logger.warning("⚠️ SIGHUP ignored (no event loop)")


async def health_handler(request: web.Request) -> web.Response:
    """
    Health check endpoint for Docker/Kubernetes.

    Checks:
    - Telegram bot application.running
    - Redis connection (if used)
    - Embeddings provider initialized
    - VectorStore provider initialized

    Returns:
        HTTP 200 if all checks pass, HTTP 503 if any check fails.
    """
    app = request.app
    application = app.get("application")
    session_manager = app.get("session_manager")
    rag_factory = app.get("rag_factory")

    checks = {}
    all_healthy = True

    # Check Telegram bot
    telegram_running = application.running if application else False
    checks["telegram"] = {
        "status": "ok" if telegram_running else "unhealthy",
        "running": telegram_running,
    }
    if not telegram_running:
        all_healthy = False

    # Check Redis (only if using Redis mode)
    # Critical: Health check должен проверять только наличие клиента, НЕ делать реальный ping
    # Реальный ping может быть медленным (>100ms) и блокировать health check
    redis_healthy = True  # Default: healthy (memory mode)
    if hasattr(session_manager, "use_redis"):
        if session_manager.use_redis:
            # Redis mode: проверить наличие клиента
            redis_healthy = session_manager.redis_client is not None
        # Else: memory mode — всегда healthy

    checks["redis"] = {
        "status": "ok" if redis_healthy else "unhealthy",
        "mode": (
            "redis"
            if hasattr(session_manager, "use_redis") and session_manager.use_redis
            else "memory"
        ),
    }
    if not redis_healthy:
        all_healthy = False

    # Check Embeddings provider
    embeddings_initialized = (
        rag_factory.embeddings_provider is not None if rag_factory else False
    )
    checks["embeddings"] = {
        "status": "ok" if embeddings_initialized else "unhealthy",
        "initialized": embeddings_initialized,
    }
    if not embeddings_initialized:
        all_healthy = False

    # Check VectorStore provider
    vectorstore_initialized = (
        rag_factory.vectorstore_provider is not None if rag_factory else False
    )
    checks["vectorstore"] = {
        "status": "ok" if vectorstore_initialized else "unhealthy",
        "initialized": vectorstore_initialized,
    }
    if not vectorstore_initialized:
        all_healthy = False

    status_code = 200 if all_healthy else 503
    response_data = {"status": "ok" if all_healthy else "unhealthy", "checks": checks}

    return web.json_response(response_data, status=status_code)


async def metrics_handler(request: web.Request) -> web.Response:
    """
    Prometheus metrics endpoint.

    Returns:
        HTTP 200 with Prometheus metrics in text/plain format.
    """
    metrics_data = generate_latest()
    return web.Response(body=metrics_data, content_type="text/plain")


async def update_active_users_metric(session_manager: SessionManager) -> None:
    """
    Background task to update ACTIVE_USERS metric periodically.

    Updates Prometheus gauge every 60 seconds with current active user count.

    Args:
        session_manager: SessionManager instance for getting active users count
    """
    from telegram_rag_bot.utils.metrics import ACTIVE_USERS

    while True:
        try:
            active_count = session_manager.get_active_users_count()
            ACTIVE_USERS.set(active_count)
            await asyncio.sleep(60)  # Update every 60 seconds
        except asyncio.CancelledError:
            logger.info("Background metrics task cancelled")
            break
        except Exception as e:
            logger.warning(f"Error updating active users metric: {e}")
            await asyncio.sleep(60)


async def main() -> None:
    """
    Main entry point for Telegram bot.

    Initializes all components in the correct order:
    1. ConfigLoader - Load config.yaml
    2. Router - Create Multi-LLM-Orchestrator with providers
    3. MultiLLMOrchestrator - LangChain LLM wrapper
    4. RAGChainFactory - Initialize RAG chains
    5. SessionManager - Redis/in-memory sessions
    6. TelegramHandlers - Bot command/message handlers
    7. Application - Telegram bot application
    8. Run - Start polling and idle loop

    Raises:
        Exception: Any fatal error during initialization or runtime.
    """
    # Initialize basic logging first (before config load)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logger.info("Starting Telegram bot...")

    application = None  # Initialize for finally block

    try:
        components = await bootstrap_components("config/config.yaml")
        config = components.config
        globals()["router"] = components.router
        globals()["rag_factory"] = components.rag_factory
        rag_factory = components.rag_factory
        session_manager = components.session_manager
        handlers = components.handlers
        token = config["telegram"]["token"]
        if not token or token.startswith("${"):
            raise ValueError("TELEGRAM_TOKEN runtime environment variable is required")
        metrics_task = asyncio.create_task(update_active_users_metric(session_manager))
        application = Application.builder().token(token).build()
        register_command_handlers(application, handlers)

        # 8.5. HTTP Server Configuration (Issue #3)
        # Support disabling HTTP server for Shared Bot Pool mode (prevents port conflicts)
        http_config = config.get("http_server", {"enabled": True, "port": 8000})

        if http_config.get("enabled", True):
            # Create HTTP server for health check and metrics
            # Critical: HTTP сервер должен запускаться параллельно с Telegram bot (не блокировать)
            app = web.Application()
            app["application"] = application
            app["session_manager"] = session_manager
            app["rag_factory"] = rag_factory

            app.router.add_get("/health", health_handler)
            app.router.add_get("/metrics", metrics_handler)

            runner = web.AppRunner(app)
            await runner.setup()

            port = http_config.get("port", 8000)
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            logger.info(f"✅ HTTP server started on port {port}")
        else:
            # Shared Pool mode: HTTP server disabled (external monitoring managed by Platform SaaS)
            logger.info(
                "⏭️ HTTP server disabled (Shared Pool mode). "
                "Health check and metrics managed externally by Platform SaaS."
            )

        # 9. Run
        logger.info("🚀 Starting polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        # Setup signal handlers for graceful shutdown in Docker (SIGTERM) and local (SIGINT)
        stop_event = asyncio.Event()

        def signal_handler(signum, frame):
            """Handle SIGTERM/SIGINT signals for graceful shutdown."""
            global shutdown_in_progress
            shutdown_in_progress = True
            logger.info(f"Received signal {signum}, initiating shutdown...")
            stop_event.set()

        signal.signal(signal.SIGTERM, signal_handler)  # Docker stop
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGHUP, _handle_sighup)  # Config hot-reload
        logger.info("✅ SIGHUP handler registered (config hot-reload enabled)")

        logger.info("🚀 Bot is running. Press Ctrl+C to stop.")
        await stop_event.wait()
        logger.info("Stop event triggered, shutting down...")

    except ImportError as e:
        logger.error("Multi-LLM-Orchestrator v0.7.0 not installed")
        logger.error(
            "Install with: pip install multi-llm-orchestrator[langchain]==0.7.0"
        )
        raise SystemExit(1) from e

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

    finally:
        # Cancel background metrics task
        if "metrics_task" in locals() and not metrics_task.done():
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass  # Expected
            logger.info("✅ Background metrics task cancelled")

        # Close HTTP server (if exists)
        if "runner" in locals() and runner:
            await runner.cleanup()
            logger.info("✅ HTTP server stopped")

        # Close OpenSearch connection (if using OpenSearch)
        if "rag_factory" in locals() and hasattr(rag_factory, "vectorstore_provider"):
            vectorstore = rag_factory.vectorstore_provider
            if hasattr(vectorstore, "close") and callable(vectorstore.close):
                try:
                    await vectorstore.close()
                    logger.info("✅ OpenSearch connection closed")
                except Exception as e:
                    logger.warning(f"Failed to close OpenSearch: {e}")

        # Note: Redis connection НЕ закрываем (синхронный клиент закроется автоматически при завершении процесса)

        # Shutdown Telegram application (correct order: updater -> application -> shutdown)
        if application:
            logger.info("Shutting down gracefully...")

            try:
                # 1. Stop updater first (critical: must be stopped before application.shutdown())
                if application.updater and application.updater.running:
                    await application.updater.stop()
                    logger.info("✅ Telegram updater stopped")

                # 2. Stop application
                if application.running:
                    await application.stop()
                    logger.info("✅ Telegram application stopped")

                # 3. Shutdown (cleanup resources)
                await application.shutdown()
                logger.info("✅ Telegram application shutdown complete")

            except RuntimeError as e:
                # Gracefully handle "still running" errors (shouldn't happen with correct order)
                if "still running" in str(e).lower():
                    logger.warning(f"⚠️ Shutdown warning (non-critical): {e}")
                else:
                    logger.error(f"❌ Unexpected error during shutdown: {e}")
                    raise

            logger.info("👋 Shutdown complete. Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
