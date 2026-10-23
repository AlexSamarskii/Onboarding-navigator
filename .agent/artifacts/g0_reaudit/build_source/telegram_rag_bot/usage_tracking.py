"""Usage tracking helpers for Telegram RAG Bot.

This module provides:

- create_track_usage_callback: closure factory for usage tracking callback
- _send_usage_to_platform: HTTP POST reporting to Platform SaaS API
- check_quota_before_llm: quota pre-check before LLM invocation (Platform SaaS)
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

import httpx

logger = logging.getLogger("telegram_rag_bot.main")

# Strong reference store — prevents GC from collecting background tasks
# before they complete. Official pattern:
# https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_tasks: set = set()

# Quota pre-check cache: tenant_id -> (allowed, block_message, cached_at).
# TTL 30s; both allowed=True and allowed=False are cached (fail-open on errors).
_quota_cache: Dict[str, tuple[bool, Optional[str], float]] = {}
QUOTA_CACHE_TTL_SECONDS = 30.0


def _log_task_exception(t: asyncio.Task) -> None:
    """Done callback: discard task from set and log any exception."""
    _background_tasks.discard(t)
    if not t.cancelled() and (exc := t.exception()):
        logger.error("_send_usage_to_platform failed: %s", exc, exc_info=exc)


async def check_quota_before_llm(
    tenant_id: str, callback_url: str
) -> tuple[bool, Optional[str]]:
    """Check tenant quota via Platform API before invoking LLM (fail-open).

    GET {callback_url}/api/v1/quota/status/{tenant_id}. Response:
    {"allowed": bool, "message": str?}. If allowed is false, returns (False, message).
    On HTTP 5xx, RequestError, timeout, or invalid JSON: logs WARNING and
    returns (True, None) so the request continues (fail-open).

    Results are cached per tenant_id for QUOTA_CACHE_TTL_SECONDS (30s).
    Both allowed=True and allowed=False are cached.

    Args:
        tenant_id: Platform tenant ID.
        callback_url: Platform API base URL.

    Returns:
        (allowed, block_message): (True, None) to continue; (False, msg) to block.
        block_message may be None (caller should use fallback text).
    """
    now = time.time()
    cached = _quota_cache.get(tenant_id)
    if cached is not None and (now - cached[2]) <= QUOTA_CACHE_TTL_SECONDS:
        return (cached[0], cached[1])

    url = f"{callback_url.rstrip('/')}/api/v1/quota/status/{tenant_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(
            "Quota pre-check failed (fail-open): %s",
            e,
            extra={"tenant_id": tenant_id, "url": url},
        )
        return (True, None)

    if response.status_code != 200:
        logger.warning(
            "Quota pre-check non-200 (fail-open): status=%s",
            response.status_code,
            extra={"tenant_id": tenant_id, "url": url},
        )
        return (True, None)

    try:
        body = response.json()
    except Exception as e:
        logger.warning(
            "Quota pre-check invalid JSON (fail-open): %s",
            e,
            extra={"tenant_id": tenant_id},
        )
        return (True, None)

    allowed = body.get("allowed", True)
    message = body.get("message") if body.get("message") else None
    _quota_cache[tenant_id] = (allowed, message, time.time())
    if not allowed:
        return (False, message)
    return (True, None)


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


def create_track_usage_callback(
    tenant_id: str,
    callback_url: Optional[str],
    platform_key_id: Optional[str],
) -> Callable[["UsageData"], Awaitable[None]]:
    """Create track_usage callback with captured config parameters.

    Returns an async function that logs usage data and optionally sends it
    to Platform SaaS API via HTTP POST.

    Args:
        tenant_id: Platform tenant ID (required if callback_url is set).
        callback_url: Platform API base URL (optional, if None → only logging).
        platform_key_id: Platform key ID for Managed tier (optional, can be None for BYOK).

    Returns:
        Async function that accepts UsageData and tracks usage.

    Example:
        >>> callback = create_track_usage_callback(
        ...     tenant_id="550e8400-...",
        ...     callback_url="https://platform.example.com",
        ...     platform_key_id="987fcdeb-...",
        ... )
        >>> await callback(usage_data)
    """

    async def track_usage(data: "UsageData") -> None:
        """Track LLM usage for billing and analytics.

        This callback is invoked for every LLM request (success or failure).
        Errors are logged but don't interrupt the main request flow (fail-silent).

        Args:
            data: Usage data from Router (tokens, cost, latency, success status).
                Can be a dict-like object or object with attributes.
        """
        try:
            # Support both dict-like and object access (for TypedDict compatibility)
            provider_name = (
                data.get("provider_name")
                if isinstance(data, dict)
                else data.provider_name
            )
            model = data.get("model") if isinstance(data, dict) else data.model
            total_tokens = (
                data.get("total_tokens")
                if isinstance(data, dict)
                else data.total_tokens
            )
            prompt_tokens = (
                data.get("prompt_tokens")
                if isinstance(data, dict)
                else data.prompt_tokens
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

            # Structured logging (existing v0.8.9 behavior)
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

            # HTTP POST to Platform API (v0.9.0+)
            # Callback runs in worker thread (asyncio.to_thread(chain.invoke)); ensure_future
            # + shield + wait_for(0.1) give the POST task time to start without blocking
            # the response for the full 2s timeout. If POST completes within 0.1s, we're done;
            # otherwise we release after 0.1s so UX stays under ~0.5s extra latency.
            if callback_url:
                loop = asyncio.get_running_loop()
                task = asyncio.ensure_future(
                    _send_usage_to_platform(
                        data,
                        tenant_id,
                        callback_url,
                        platform_key_id,
                    ),
                    loop=loop,
                )
                _background_tasks.add(task)
                task.add_done_callback(_log_task_exception)

                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                except asyncio.TimeoutError:
                    # Task started but did not finish in 0.1s — OK, POST is in flight
                    pass
        except Exception as e:  # pragma: no cover - defensive logging
            logger.warning(f"Usage tracking callback failed: {e}", exc_info=True)

    return track_usage


async def _send_usage_to_platform(
    data: "UsageData",
    tenant_id: str,
    callback_url: str,
    platform_key_id: Optional[str],
) -> None:
    """Send usage data to Platform API (single attempt, fail-silent).

    Implements HTTP POST to Platform SaaS API with:
    - Single attempt, timeout 2 seconds
    - 429: ERROR log, return (no retry)
    - Any other error: ERROR log, return (fail-silent)

    Args:
        data: Usage data from Router (tokens, cost, latency, success status).
        tenant_id: Platform tenant ID (required).
        callback_url: Platform API base URL (e.g., "https://platform.example.com").
        platform_key_id: Platform key ID for Managed tier (optional, None for BYOK).
    """
    # Валидация: если tenant_id пустой → warning, return
    if not tenant_id:
        logger.warning("tenant_id is empty, skipping usage report")
        return

    # Построить URL
    url = f"{callback_url.rstrip('/')}/api/v1/usage/report"

    # Поддержка dict-like и object access для UsageData
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
    latency_ms = data.get("latency_ms") if isinstance(data, dict) else data.latency_ms
    success = data.get("success") if isinstance(data, dict) else data.success

    # Построить payload (JSON)
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider": provider_name,  # НЕ нормализовать, как есть
        "model": model,
        "tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform_key_id": platform_key_id,  # None → null в JSON
        "telegram_user_id": data.get("telegram_user_id") if isinstance(data, dict) else getattr(data, "telegram_user_id", None),  # Issue #15; None acceptable
    }

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code == 200:
            logger.debug(
                "Usage reported to Platform API",
                extra={"tenant_id": tenant_id, "provider": provider_name},
            )
            return

        if response.status_code == 429:
            logger.error(
                "Quota exceeded (429), Platform API rejected request",
                extra={
                    "tenant_id": tenant_id,
                    "provider": provider_name,
                    "status_code": 429,
                },
            )
            return

        logger.error(
            "Platform API returned %s",
            response.status_code,
            extra={
                "tenant_id": tenant_id,
                "provider": provider_name,
                "status_code": response.status_code,
            },
        )
    except Exception as e:  # pragma: no cover - network errors are covered in tests
        logger.error("_send_usage_to_platform failed: %s", e, exc_info=True)
