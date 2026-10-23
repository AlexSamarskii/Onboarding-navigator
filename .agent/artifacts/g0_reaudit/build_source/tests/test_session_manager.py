"""
Unit tests for telegram_rag_bot.utils.session_manager.SessionManager.

Tests cover:
- get_session: Session retrieval with Redis fallback (4 tests)
- set_session: Session storage with Redis fallback (2 tests)
- _default_session: Default session creation (1 test)
- get_active_users_count: Active users tracking (2 tests)

Target coverage: 80%
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from telegram_rag_bot.utils.session_manager import SessionManager


# === get_session tests ===


@pytest.mark.asyncio
async def test_get_session_redis_success():
    """Test get_session retrieves from Redis successfully."""
    # Arrange: Mock Redis client
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = (
            '{"mode": "it_support", "last_active": "2025-12-22T10:00:00"}'
        )
        mock_redis.return_value = mock_client

        manager = SessionManager(redis_url="redis://localhost:6379")

        # Act
        session = await manager.get_session(12345)

        # Assert
        assert session["mode"] == "it_support"
        mock_client.get.assert_called_once_with("session:12345")


@pytest.mark.asyncio
async def test_get_session_redis_fail_fallback_to_memory():
    """Test get_session falls back to memory when Redis fails."""
    # Arrange: Redis raises exception
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Connection refused")
        mock_redis.return_value = mock_client

        manager = SessionManager(redis_url="redis://localhost:6379")

        # Pre-populate memory store
        manager.memory_store[12345] = {
            "mode": "hr_support",
            "created_at": datetime.now().isoformat(),
        }

        # Act
        session = await manager.get_session(12345)

        # Assert: Falls back to memory
        assert session["mode"] == "hr_support"


@pytest.mark.asyncio
async def test_get_session_memory_ttl_expired():
    """Test get_session deletes expired sessions (TTL check)."""
    # Arrange: Memory-only manager
    manager = SessionManager(redis_url=None)

    # Add expired session (created > 24h ago)
    expired_time = datetime.now() - timedelta(hours=25)
    manager.memory_store[12345] = {
        "mode": "it_support",
        "created_at": expired_time.isoformat(),
    }

    # Act
    session = await manager.get_session(12345)

    # Assert: Returns default session (expired one deleted).
    # Default session no longer includes "mode" — handler resolves via config (Issue #16).
    assert session["user_id"] == 12345
    assert "created_at" in session
    assert 12345 not in manager.memory_store  # Expired session deleted


@pytest.mark.asyncio
async def test_get_session_invalid_created_at_format():
    """Test get_session handles invalid created_at format."""
    # Arrange
    manager = SessionManager(redis_url=None)

    # Add session with invalid created_at
    manager.memory_store[12345] = {
        "mode": "it_support",
        "created_at": "invalid_date_format",
    }

    # Act
    session = await manager.get_session(12345)

    # Assert: Treats as expired, returns default
    assert 12345 not in manager.memory_store


# === set_session tests ===


@pytest.mark.asyncio
async def test_set_session_redis_success():
    """Test set_session stores in Redis successfully."""
    # Arrange: Mock Redis client
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        manager = SessionManager(redis_url="redis://localhost:6379")

        # Act
        await manager.set_session(12345, {"mode": "it_support"})

        # Assert: setex called with TTL
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args
        assert call_args[0][0] == "session:12345"
        assert call_args[0][1] == 86400  # Default TTL


@pytest.mark.asyncio
async def test_set_session_redis_fail_fallback_to_memory():
    """Test set_session falls back to memory when Redis fails."""
    # Arrange: Redis setex raises exception
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.setex.side_effect = Exception("Connection lost")
        mock_redis.return_value = mock_client

        manager = SessionManager(redis_url="redis://localhost:6379")

        # Act
        await manager.set_session(12345, {"mode": "hr_support"})

        # Assert: Falls back to memory
        assert 12345 in manager.memory_store
        assert manager.memory_store[12345]["mode"] == "hr_support"


# === _default_session tests ===


def test_default_session_creates_valid_session():
    """Test _default_session creates session with default values."""
    # Arrange
    manager = SessionManager(redis_url=None)

    # Act
    session = manager._default_session(12345)

    # Assert: default session has user_id and created_at; mode omitted (handler resolves)
    assert session["user_id"] == 12345
    assert "created_at" in session
    assert "mode" not in session  # Intentionally omitted (Issue #16)


# === get_active_users_count tests ===


@pytest.mark.asyncio
async def test_get_active_users_count_redis_mode():
    """Test get_active_users_count tracks active users (Redis mode)."""
    # Arrange
    with patch("redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = '{"mode": "it_support"}'
        mock_redis.return_value = mock_client

        manager = SessionManager(redis_url="redis://localhost:6379")

        # Act: Get sessions for 3 users
        await manager.get_session(123)
        await manager.get_session(456)
        await manager.get_session(789)

        count = manager.get_active_users_count()

        # Assert: 3 active users
        assert count == 3


@pytest.mark.asyncio
async def test_get_active_users_count_memory_mode():
    """Test get_active_users_count tracks active users (memory mode)."""
    # Arrange
    manager = SessionManager(redis_url=None)

    # Act: Get sessions for 2 users
    await manager.get_session(111)
    await manager.get_session(222)

    count = manager.get_active_users_count()

    # Assert: 2 active users
    assert count == 2
