"""
Main entry point for Telegram bot with Multi-LLM-Orchestrator integration.

This module initializes all components (Router, RAG chains, session manager,
handlers) and runs the Telegram bot application.
"""

import asyncio
import logging
import signal
import time
from typing import Awaitable, Callable, Dict, Any, List, Optional, TYPE_CHECKING

from aiohttp import web
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from prometheus_client import generate_latest

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
            new_config = ConfigLoader.load_config("config/config.yaml")

            # Build new providers list
            new_providers = build_providers_list(new_config["orchestrator"])

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
        # 1. Load config
        config = ConfigLoader.load_config("config/config.yaml")
        logger.info("✅ Config loaded successfully")
        logger.info(
            "Bot starting | Available modes: %s | Default: %s",
            list(config["modes"].keys()),
            list(config["modes"].keys())[0],
        )

        # 1.5. Setup structured logging from config
        setup_logging(config)

        # 1.6. Create track_usage callback with platform config
        platform_config = config.get("platform", {})
        tenant_id = platform_config.get("tenant_id", "")
        callback_url = platform_config.get("callback_url")
        platform_key_id = platform_config.get("platform_key_id")

        track_usage_callback = create_track_usage_callback(
            tenant_id=tenant_id,
            callback_url=callback_url,
            platform_key_id=platform_key_id,
        )

        # Bug #2: Validate critical environment variables
        telegram_token = config["telegram"]["token"]
        if not telegram_token or telegram_token.startswith("${"):
            logger.error("TELEGRAM_TOKEN environment variable not set")
            logger.error("Create .env file with: TELEGRAM_TOKEN=your_token_here")
            raise SystemExit(1)

        # Validate at least one provider has valid API key
        has_valid_provider = False
        for provider_cfg in config["orchestrator"]["providers"]:
            if not provider_cfg.get("enabled", True):
                continue
            api_key = provider_cfg["config"].get("api_key", "")
            if api_key and not api_key.startswith("${"):
                has_valid_provider = True
                break

        if not has_valid_provider:
            logger.error("No enabled provider has valid API key set")
            logger.error("Set environment variables: GIGACHAT_KEY, YANDEX_API_KEY")
            raise SystemExit(1)

        # Bug #2: Validate embeddings/vectorstore environment variables
        # Validate embeddings config (if using cloud providers)
        if config["embeddings"]["type"] == "gigachat":
            gigachat_api_key = config["embeddings"]["gigachat"].get("api_key", "")
            if not gigachat_api_key or gigachat_api_key.startswith("${"):
                logger.error(
                    "GIGACHAT_EMBEDDINGS_KEY not set (required for gigachat embeddings)"
                )
                logger.error(
                    "Set environment variable: GIGACHAT_EMBEDDINGS_KEY=your_key_here"
                )
                raise SystemExit(1)

        # Validate vectorstore config (if using OpenSearch)
        if config["vectorstore"]["type"] == "opensearch":
            opensearch_host = config["vectorstore"]["opensearch"].get("host", "")
            if not opensearch_host or opensearch_host.startswith("${"):
                logger.error(
                    "OPENSEARCH_HOST not set (required for opensearch vectorstore)"
                )
                logger.error("Set environment variable: OPENSEARCH_HOST=your_host_here")
                raise SystemExit(1)

        # 2. Create Router with providers and usage callback
        router = create_router(
            config["orchestrator"], usage_callback=track_usage_callback
        )
        provider_count = len(router.providers)
        logger.info(f"✅ Router created with {provider_count} providers")

        # Make router available globally for SIGHUP handler
        globals()["router"] = router

        # 3. Create LangChain LLM
        llm = MultiLLMOrchestrator(router=router)
        logger.info("✅ LangChain LLM created (MultiLLMOrchestrator)")

        # 4. Create RAG factory
        rag_factory = RAGChainFactory(
            llm=llm,
            embeddings_config=config["embeddings"],
            vectorstore_config=config["vectorstore"],
            chunk_config=config["langchain"],
            modes=config["modes"],
            retrieval_config=config.get(
                "retrieval", {}
            ),  # v0.11.0: async FAISS support
        )
        logger.info("✅ RAG factory initialized")

        # Make rag_factory available globally for SIGHUP handler
        globals()["rag_factory"] = rag_factory

        # 4.4. Warmup embeddings model (preload to avoid first-request delay)
        logger.info("🔥 Warming up embeddings model...")
        try:
            # Trigger embeddings loading by encoding a test string
            test_text = "test warmup query"
            _ = await rag_factory.embeddings_provider.embed_query(test_text)
            logger.info("✅ Embeddings model warmed up and ready")
        except Exception as e:
            logger.warning(f"⚠️ Embeddings warmup failed (will load on first use): {e}")

        # 4.5. Build FAISS indices for all modes (if using FAISS)
        if config["vectorstore"]["type"] == "faiss":
            logger.info("🔨 Building FAISS indices for all modes...")
            from pathlib import Path

            # Get indices_dir from vectorstore config (default: .faiss_indices)
            vectorstore_config = config["vectorstore"]
            faiss_config = vectorstore_config.get("faiss", {})
            indices_dir_str = faiss_config.get("indices_dir", ".faiss_indices")
            indices_dir = Path(indices_dir_str)

            for mode_name, mode_data in config["modes"].items():
                try:
                    # Получить путь к FAQ файлу
                    faq_file = mode_data.get("faq_file")

                    if not faq_file:
                        logger.warning(
                            f"⏭️ Mode '{mode_name}' has no faq_file, skipping index build"
                        )
                        continue

                    # Проверить существование индекса
                    index_path = indices_dir / mode_name

                    if index_path.exists() and (index_path / "index.faiss").exists():
                        logger.info(
                            f"✅ FAISS index already exists for mode '{mode_name}', skipping"
                        )
                        continue

                    # Создать индекс
                    logger.info(
                        f"🔨 Building FAISS index for mode '{mode_name}' from {faq_file}..."
                    )
                    await rag_factory.rebuild_index(mode_name, faq_file)
                    logger.info(f"✅ FAISS index built for mode '{mode_name}'")

                except Exception as e:
                    logger.error(
                        f"❌ Failed to build FAISS index for mode '{mode_name}': {e}",
                        exc_info=True,
                    )
                    # Не падать, продолжить для других modes
                    continue

            logger.info("✅ All FAISS indices ready")

        # 5. Create session manager
        session_manager = SessionManager(
            redis_url=config["storage"]["sessions"].get("url"),
            ttl_seconds=config["storage"]["sessions"]["ttl_seconds"],
        )
        logger.info("✅ Session manager initialized")

        # 5.5. Create feedback collector
        feedback_collector = FeedbackCollector(session_manager.redis_client)
        logger.info("✅ Feedback collector initialized")

        # 5.6. Start background task for metrics
        metrics_task = asyncio.create_task(update_active_users_metric(session_manager))
        logger.info("✅ Background metrics task started")

        # 6. Create handlers
        handlers = TelegramHandlers(
            rag_factory=rag_factory,
            session_manager=session_manager,
            config=config,
            feedback_collector=feedback_collector,
        )
        logger.info("✅ Telegram handlers created")

        # 7. Create application
        application = Application.builder().token(config["telegram"]["token"]).build()

        # 8. Register handlers
        application.add_handler(CommandHandler("start", handlers.cmd_start))
        application.add_handler(CommandHandler("mode", handlers.cmd_set_mode))
        application.add_handler(CommandHandler("reload_faq", handlers.cmd_reload_faq))
        application.add_handler(CommandHandler("help", handlers.cmd_help))
        application.add_handler(CommandHandler("feedback", handlers.cmd_feedback))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message)
        )
        from telegram.ext import CallbackQueryHandler

        application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
        logger.info("✅ Handlers registered (help, feedback, callback)")

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
