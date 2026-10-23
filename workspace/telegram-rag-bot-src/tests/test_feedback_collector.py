"""
Unit tests for telegram_rag_bot.utils.feedback_collector.FeedbackCollector.

Tests cover:
- save_feedback: Save feedback to Redis/memory (3 tests)
- get_feedback: Retrieve feedback history (2 tests)
- Error handling: Invalid rating, Redis errors (2 tests)
- Memory fallback: Redis unavailable (1 test)

Target coverage: 80%
"""

import pytest
from unittest.mock import MagicMock
import json

from telegram_rag_bot.utils.feedback_collector import FeedbackCollector


# === save_feedback tests ===


@pytest.mark.asyncio
async def test_save_feedback_success():
    """Test save_feedback saves to Redis successfully."""
    # Arrange: Mock Redis client
    mock_redis = MagicMock()
    mock_redis.setex = MagicMock()

    collector = FeedbackCollector(redis_client=mock_redis)

    # Act
    result = await collector.save_feedback(
        user_id=123,
        query="How to reset VPN password?",
        answer="To reset VPN password...",
        rating=4,
        mode="it_support",
    )

    # Assert: Feedback saved
    assert result is True
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    assert call_args[0][0].startswith("feedback:123:")
    assert call_args[0][1] == 7776000  # TTL 90 days
    # Check JSON data contains expected fields
    json_data = call_args[0][2]
    data = json.loads(json_data)
    assert data["user_id"] == 123
    assert data["rating"] == 4
    assert data["mode"] == "it_support"


@pytest.mark.asyncio
async def test_save_feedback_invalid_rating():
    """Test save_feedback raises ValueError for invalid rating."""
    # Arrange
    collector = FeedbackCollector(redis_client=None)

    # Act & Assert: Rating 0 → ValueError
    with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
        await collector.save_feedback(
            user_id=123, query="Test", answer="Test", rating=0, mode="it_support"
        )

    # Act & Assert: Rating 6 → ValueError
    with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
        await collector.save_feedback(
            user_id=123, query="Test", answer="Test", rating=6, mode="it_support"
        )


@pytest.mark.asyncio
async def test_save_feedback_memory_fallback():
    """Test save_feedback falls back to memory when Redis unavailable."""
    # Arrange: Redis raises exception
    mock_redis = MagicMock()
    mock_redis.setex.side_effect = Exception("Connection refused")

    collector = FeedbackCollector(redis_client=mock_redis)

    # Act
    result = await collector.save_feedback(
        user_id=456,
        query="Test question",
        answer="Test answer",
        rating=5,
        mode="it_support",
    )

    # Assert: Saved to memory
    assert result is True
    assert len(collector._memory_storage) == 1
    # Check memory storage contains feedback
    key = list(collector._memory_storage.keys())[0]
    assert key.startswith("feedback:456:")
    assert collector._memory_storage[key]["rating"] == 5


# === get_feedback tests ===


@pytest.mark.asyncio
async def test_get_feedback():
    """Test get_feedback retrieves feedback from Redis."""
    # Arrange: Mock Redis with multiple feedback entries
    mock_redis = MagicMock()
    mock_feedback_1 = {
        "user_id": 123,
        "query": "Question 1",
        "answer": "Answer 1",
        "rating": 4,
        "mode": "it_support",
        "timestamp": 1000,
    }
    mock_feedback_2 = {
        "user_id": 123,
        "query": "Question 2",
        "answer": "Answer 2",
        "rating": 5,
        "mode": "it_support",
        "timestamp": 2000,
    }

    mock_redis.keys.return_value = [
        "feedback:123:1000",
        "feedback:123:2000",
    ]
    mock_redis.get.side_effect = [
        json.dumps(mock_feedback_1),
        json.dumps(mock_feedback_2),
    ]

    collector = FeedbackCollector(redis_client=mock_redis)

    # Act
    feedback_list = await collector.get_feedback(user_id=123, limit=10)

    # Assert: Returns sorted list (newest first)
    assert len(feedback_list) == 2
    assert feedback_list[0]["timestamp"] == 2000  # Newest first
    assert feedback_list[1]["timestamp"] == 1000
    assert feedback_list[0]["rating"] == 5


@pytest.mark.asyncio
async def test_get_feedback_empty():
    """Test get_feedback returns empty list when no feedback found."""
    # Arrange: Mock Redis with no keys
    mock_redis = MagicMock()
    mock_redis.keys.return_value = []

    collector = FeedbackCollector(redis_client=mock_redis)

    # Act
    feedback_list = await collector.get_feedback(user_id=999, limit=10)

    # Assert: Empty list
    assert feedback_list == []


@pytest.mark.asyncio
async def test_get_feedback_memory_fallback():
    """Test get_feedback falls back to memory when Redis unavailable."""
    # Arrange: Redis raises exception
    mock_redis = MagicMock()
    mock_redis.keys.side_effect = Exception("Connection refused")

    collector = FeedbackCollector(redis_client=mock_redis)

    # Pre-populate memory storage
    collector._memory_storage["feedback:789:1000"] = {
        "user_id": 789,
        "query": "Test",
        "answer": "Test",
        "rating": 3,
        "mode": "it_support",
        "timestamp": 1000,
    }

    # Act
    feedback_list = await collector.get_feedback(user_id=789, limit=10)

    # Assert: Returns from memory
    assert len(feedback_list) == 1
    assert feedback_list[0]["user_id"] == 789
    assert feedback_list[0]["rating"] == 3


@pytest.mark.asyncio
async def test_get_feedback_limit():
    """Test get_feedback respects limit parameter."""
    # Arrange: Mock Redis with 5 feedback entries
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [
        f"feedback:123:{i}" for i in range(1000, 6000, 1000)
    ]
    mock_redis.get.side_effect = [
        json.dumps(
            {
                "user_id": 123,
                "query": f"Question {i}",
                "answer": f"Answer {i}",
                "rating": 4,
                "mode": "it_support",
                "timestamp": i,
            }
        )
        for i in range(1000, 6000, 1000)
    ]

    collector = FeedbackCollector(redis_client=mock_redis)

    # Act: Request only 2 entries
    feedback_list = await collector.get_feedback(user_id=123, limit=2)

    # Assert: Returns only 2 entries (newest first)
    assert len(feedback_list) == 2
    assert feedback_list[0]["timestamp"] == 5000
    assert feedback_list[1]["timestamp"] == 4000
