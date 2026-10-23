"""
Unit tests for telegram_rag_bot.usage_tracking callbacks.

Tests cover:
- track_usage logs structured data correctly
- track_usage fail-silent behavior (doesn't crash on errors)
- HTTP POST to Platform API (v0.9.0+)
- Retry logic with exponential backoff
- 429 Quota Exceeded handling
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from typing import TypedDict
import httpx


# Type stub for UsageData (matches orchestrator v0.7.6)
class UsageData(TypedDict):
    """Usage data from Router (tokens, cost, latency, success status)."""

    provider_name: str
    model: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cost: float
    latency_ms: int
    success: bool


@pytest.mark.asyncio
async def test_track_usage_logs_correctly():
    """Test that track_usage logs structured data."""
    from telegram_rag_bot.usage_tracking import create_track_usage_callback

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    callback = create_track_usage_callback(
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url=None,
        platform_key_id=None,
    )

    with patch("telegram_rag_bot.usage_tracking.logger.info") as mock_logger:
        await callback(data)

        # Verify logger called with correct message
        mock_logger.assert_called_once()
        call_args = mock_logger.call_args
        assert call_args[0][0] == "llm_usage_tracked"

        # Verify structured data
        usage = call_args[1]["extra"]["usage"]
        assert usage["provider"] == "gigachat"
        assert usage["total_tokens"] == 150
        assert usage["cost_rub"] == 0.45
        assert usage["success"] is True


@pytest.mark.asyncio
async def test_track_usage_fail_silent():
    """Test that track_usage doesn't crash on errors."""
    from telegram_rag_bot.usage_tracking import create_track_usage_callback

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    callback = create_track_usage_callback(
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url=None,
        platform_key_id=None,
    )

    with (
        patch(
            "telegram_rag_bot.usage_tracking.logger.info",
            side_effect=Exception("Test error"),
        ),
        patch("telegram_rag_bot.usage_tracking.logger.warning") as mock_warning,
    ):
        # Should NOT raise exception
        await callback(data)

        # Verify warning was logged
        mock_warning.assert_called_once()
        assert "Usage tracking callback failed" in mock_warning.call_args[0][0]


# === HTTP POST tests (v0.9.0+) ===


@pytest.mark.asyncio
async def test_create_track_usage_callback_uses_create_task_when_callback_url_set():
    """track_usage callback should schedule _send_usage_to_platform via asyncio.ensure_future."""
    from telegram_rag_bot.usage_tracking import create_track_usage_callback
    import asyncio as _asyncio

    callback = create_track_usage_callback(
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://platform.example.com",
        platform_key_id="987fcdeb-51a2-...",
    )

    data: UsageData = {
        "provider_name": "gigachat_primary",
        "model": "GigaChat-Pro",
        "total_tokens": 450,
        "prompt_tokens": 150,
        "completion_tokens": 300,
        "cost": 0.0135,
        "latency_ms": 1234,
        "success": True,
    }

    with patch(
        "telegram_rag_bot.usage_tracking.asyncio.ensure_future"
    ) as mock_ensure_future:
        await callback(data)

        # ensure_future MUST be called exactly once (schedules _send_usage_to_platform)
        mock_ensure_future.assert_called_once()
        task_arg = mock_ensure_future.call_args[0][0]
        assert _asyncio.iscoroutine(task_arg)


@pytest.mark.asyncio
async def test_create_track_usage_callback_does_not_use_create_task_when_no_callback_url():
    """If callback_url is None, track_usage should not schedule _send_usage_to_platform."""
    from telegram_rag_bot.usage_tracking import create_track_usage_callback

    callback = create_track_usage_callback(
        tenant_id="",
        callback_url=None,
        platform_key_id=None,
    )

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with patch(
        "telegram_rag_bot.usage_tracking.asyncio.ensure_future"
    ) as mock_ensure_future:
        await callback(data)

        # Only structured logging, no background task
        mock_ensure_future.assert_not_called()


@pytest.mark.asyncio
async def test_background_tasks_holds_strong_reference():
    """Background tasks set should hold strong reference until completion."""
    from telegram_rag_bot.usage_tracking import (
        create_track_usage_callback,
        _background_tasks,
    )

    _background_tasks.clear()

    callback = create_track_usage_callback(
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://platform.example.com",
        platform_key_id="987fcdeb-51a2-...",
    )

    data: UsageData = {
        "provider_name": "gigachat_primary",
        "model": "GigaChat-Pro",
        "total_tokens": 450,
        "prompt_tokens": 150,
        "completion_tokens": 300,
        "cost": 0.0135,
        "latency_ms": 1234,
        "success": True,
    }

    task_mock = MagicMock()

    with patch(
        "telegram_rag_bot.usage_tracking.asyncio.ensure_future"
    ) as mock_ensure_future:
        mock_ensure_future.return_value = task_mock
        await callback(data)

    mock_ensure_future.assert_called_once()
    assert task_mock in _background_tasks
    task_mock.add_done_callback.assert_called_once()

    callback_arg = task_mock.add_done_callback.call_args[0][0]
    assert callable(callback_arg)
    assert getattr(callback_arg, "__name__", None) == "_log_task_exception"


@pytest.mark.asyncio
async def test_background_tasks_discard_on_done():
    """Background tasks set should discard task on completion."""
    from telegram_rag_bot.usage_tracking import (
        create_track_usage_callback,
        _background_tasks,
    )

    _background_tasks.clear()

    callback = create_track_usage_callback(
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://platform.example.com",
        platform_key_id="987fcdeb-51a2-...",
    )

    data: UsageData = {
        "provider_name": "gigachat_primary",
        "model": "GigaChat-Pro",
        "total_tokens": 450,
        "prompt_tokens": 150,
        "completion_tokens": 300,
        "cost": 0.0135,
        "latency_ms": 1234,
        "success": True,
    }

    task_mock = MagicMock()

    with patch(
        "telegram_rag_bot.usage_tracking.asyncio.ensure_future"
    ) as mock_ensure_future:
        mock_ensure_future.return_value = task_mock
        await callback(data)

    assert task_mock in _background_tasks

    callback_arg = task_mock.add_done_callback.call_args[0][0]
    callback_arg(task_mock)

    assert task_mock not in _background_tasks


@pytest.mark.asyncio
async def test_send_usage_to_platform_retry_logic():
    """Test non-200 response: single attempt, error logged (no retry in current impl)."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        assert mock_client.post.call_count == 1
        mock_logger.error.assert_called()
        assert "500" in str(mock_logger.error.call_args)


@pytest.mark.asyncio
async def test_send_usage_to_platform_429_no_retry():
    """Test 429 handling: NO retry, ERROR log."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 429  # Quota exceeded
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        # Verify only 1 attempt (NO retry)
        assert mock_client.post.call_count == 1

        # Verify ERROR log
        mock_logger.error.assert_called_once()
        assert "Quota exceeded (429)" in mock_logger.error.call_args[0][0]


@pytest.mark.asyncio
async def test_send_usage_to_platform_platform_key_id_null():
    """Test that platform_key_id=None is sent as null in JSON."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,  # BYOK tier
        )

        # Verify payload contains platform_key_id as None
        payload = mock_client.post.call_args[1]["json"]
        assert payload["platform_key_id"] is None


@pytest.mark.asyncio
async def test_send_usage_to_platform_telegram_user_id_in_payload():
    """Test that telegram_user_id (Issue #15) is included in usage report payload."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
        "telegram_user_id": 123456789,
    }

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["telegram_user_id"] == 123456789


@pytest.mark.asyncio
async def test_send_usage_to_platform_telegram_user_id_absent_is_null():
    """Test that missing telegram_user_id in data sends null in payload."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["telegram_user_id"] is None


@pytest.mark.asyncio
async def test_send_usage_to_platform_empty_tenant_id():
    """Test that empty tenant_id skips HTTP POST."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with (
        patch("telegram_rag_bot.usage_tracking.logger.warning") as mock_warning,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        await _send_usage_to_platform(
            data,
            tenant_id="",  # Empty tenant_id
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        # Verify HTTP POST was NOT called
        mock_client_class.assert_not_called()

        # Verify warning was logged
        mock_warning.assert_called_once()
        assert "tenant_id is empty" in mock_warning.call_args[0][0]


@pytest.mark.asyncio
async def test_send_usage_to_platform_network_error_retry():
    """Test that network errors are logged (single attempt, fail-silent)."""
    from telegram_rag_bot.usage_tracking import _send_usage_to_platform

    data: UsageData = {
        "provider_name": "gigachat",
        "model": "GigaChat-Pro",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost": 0.45,
        "latency_ms": 1200,
        "success": True,
    }

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.RequestError(
            "Connection failed", request=MagicMock()
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await _send_usage_to_platform(
            data,
            tenant_id="550e8400-...",
            callback_url="https://platform.example.com",
            platform_key_id=None,
        )

        assert mock_client.post.call_count == 1
        mock_logger.error.assert_called_once()
        assert "failed" in mock_logger.error.call_args[0][0].lower()


# === Quota pre-check (check_quota_before_llm) ===


@pytest.mark.asyncio
async def test_check_quota_before_llm_200_allowed_true():
    """Quota API 200 with allowed=true returns (True, None) and caches result."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"allowed": True}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed, block_message = await check_quota_before_llm(
            "tenant-1", "https://platform.example.com"
        )

        assert allowed is True
        assert block_message is None
        mock_client.get.assert_called_once()
        call_url = mock_client.get.call_args[0][0]
        assert "quota/status/tenant-1" in call_url


@pytest.mark.asyncio
async def test_check_quota_before_llm_200_allowed_false():
    """Quota API 200 with allowed=false returns (False, message)."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "allowed": False,
            "message": "Ваш пробный период завершён.",
        }
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed, block_message = await check_quota_before_llm(
            "tenant-2", "https://platform.example.com"
        )

        assert allowed is False
        assert block_message == "Ваш пробный период завершён."


@pytest.mark.asyncio
async def test_check_quota_before_llm_5xx_fail_open():
    """Quota API 5xx: fail-open, returns (True, None) and logs WARNING."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed, block_message = await check_quota_before_llm(
            "tenant-3", "https://platform.example.com"
        )

        assert allowed is True
        assert block_message is None
        mock_logger.warning.assert_called_once()
        assert "fail-open" in mock_logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_check_quota_before_llm_network_error_fail_open():
    """Quota API RequestError: fail-open, returns (True, None)."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("Connection failed", request=MagicMock())
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed, block_message = await check_quota_before_llm(
            "tenant-4", "https://platform.example.com"
        )

        assert allowed is True
        assert block_message is None
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_check_quota_before_llm_cache_hit():
    """Second call with same tenant_id within TTL uses cache (no second GET)."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm, _quota_cache

    _quota_cache.clear()

    with patch(
        "telegram_rag_bot.usage_tracking.httpx.AsyncClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"allowed": False, "message": "Cached"}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed1, msg1 = await check_quota_before_llm(
            "tenant-cache", "https://platform.example.com"
        )
        allowed2, msg2 = await check_quota_before_llm(
            "tenant-cache", "https://platform.example.com"
        )

        assert allowed1 is False and msg1 == "Cached"
        assert allowed2 is False and msg2 == "Cached"
        assert mock_client.get.call_count == 1

    _quota_cache.clear()


@pytest.mark.asyncio
async def test_check_quota_before_llm_invalid_json_fail_open():
    """Quota API 200 with invalid JSON: fail-open, returns (True, None)."""
    from telegram_rag_bot.usage_tracking import check_quota_before_llm

    with (
        patch("telegram_rag_bot.usage_tracking.logger") as mock_logger,
        patch("telegram_rag_bot.usage_tracking.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        allowed, block_message = await check_quota_before_llm(
            "tenant-5", "https://platform.example.com"
        )

        assert allowed is True
        assert block_message is None
        mock_logger.warning.assert_called_once()
        assert "invalid json" in mock_logger.warning.call_args[0][0].lower()


def test_public_api_exposes_create_track_usage_callback():
    """Public API should expose create_track_usage_callback from usage_tracking."""
    from telegram_rag_bot import create_track_usage_callback as public_fn
    from telegram_rag_bot.usage_tracking import (
        create_track_usage_callback as internal_fn,
    )

    assert public_fn is internal_fn
