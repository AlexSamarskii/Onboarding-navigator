"""
Feedback collector for user ratings and feedback storage.

Stores user feedback (ratings 1-5) in Redis with 90-day TTL.
Falls back to in-memory storage if Redis is unavailable.

Features:
- Save feedback with user_id, query, answer, rating, mode, timestamp
- Retrieve feedback history per user
- Redis storage with TTL 90 days (7776000 seconds)
- Memory fallback for development/testing
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

try:
    import redis
except ImportError:
    redis = None  # type: ignore

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """
    Collects and stores user feedback (ratings) for bot responses.

    Features:
    - Redis storage (if available) with 90-day TTL
    - In-memory fallback (dict) for development
    - JSON serialization for feedback data
    - Error handling with graceful degradation

    Example:
        >>> collector = FeedbackCollector(redis_client)
        >>> await collector.save_feedback(
        ...     user_id=123,
        ...     query="How to reset VPN password?",
        ...     answer="To reset VPN password...",
        ...     rating=4,
        ...     mode="it_support"
        ... )
        True
    """

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        """
        Initialize FeedbackCollector with Redis client.

        Args:
            redis_client: Redis client instance (from redis library).
                         If None, uses in-memory storage only.
        """
        self.redis_client = redis_client
        self.use_redis = redis_client is not None
        self._memory_storage: Dict[str, Dict[str, Any]] = {}

        if self.use_redis:
            logger.info("✅ Using Redis for feedback storage")
        else:
            logger.info("📦 Using in-memory feedback storage (development mode)")

    async def save_feedback(
        self,
        user_id: int,
        query: str,
        answer: str,
        rating: int,
        mode: str,
    ) -> bool:
        """
        Save user feedback to storage.

        Args:
            user_id: Telegram user ID
            query: User's question/query
            answer: Bot's response
            rating: Rating (1-5 stars)
            mode: Current bot mode (e.g., "it_support")

        Returns:
            True if feedback saved successfully, False otherwise

        Raises:
            ValueError: If rating is not in range 1-5
        """
        # Validate rating
        if not (1 <= rating <= 5):
            raise ValueError(f"Rating must be between 1 and 5, got {rating}")

        # Prepare feedback data
        timestamp = int(time.time())
        feedback_data = {
            "user_id": user_id,
            "query": query,
            "answer": answer,
            "rating": rating,
            "mode": mode,
            "timestamp": timestamp,
        }

        # Redis key format: feedback:{user_id}:{timestamp}
        redis_key = f"feedback:{user_id}:{timestamp}"

        # Serialize to JSON
        json_data = json.dumps(feedback_data, ensure_ascii=False)

        # Try Redis first
        if self.use_redis and self.redis_client:
            try:
                # TTL: 90 days = 7776000 seconds
                self.redis_client.setex(redis_key, 7776000, json_data)
                logger.info(
                    f"Feedback saved to Redis: user_id={user_id}, rating={rating}, mode={mode}"
                )
                return True
            except Exception as e:
                logger.warning(f"Redis save error: {e}, falling back to memory")
                # Fall through to memory

        # Memory fallback
        self._memory_storage[redis_key] = feedback_data
        logger.info(
            f"Feedback saved to memory: user_id={user_id}, rating={rating}, mode={mode}"
        )
        return True

    async def get_feedback(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get feedback history for a user.

        Args:
            user_id: Telegram user ID
            limit: Maximum number of feedback entries to return (default: 10)

        Returns:
            List of feedback dictionaries, sorted by timestamp (newest first).
            Empty list if no feedback found.
        """
        feedback_list: List[Dict[str, Any]] = []

        # Try Redis first
        if self.use_redis and self.redis_client:
            try:
                # Pattern: feedback:{user_id}:*
                pattern = f"feedback:{user_id}:*"

                # Use SCAN for large datasets, or KEYS for simplicity
                # For pilot (1-3 users), KEYS is acceptable
                keys = self.redis_client.keys(pattern)

                for key in keys:
                    try:
                        data = self.redis_client.get(key)
                        if data:
                            feedback_list.append(json.loads(data))
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning(f"Error parsing feedback key {key}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Redis get error: {e}, falling back to memory")
                # Fall through to memory

        # Memory fallback: filter by user_id
        memory_pattern = f"feedback:{user_id}:"
        for key, data in self._memory_storage.items():
            if key.startswith(memory_pattern):
                feedback_list.append(data)

        # Sort by timestamp (descending, newest first)
        feedback_list.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # Limit results
        return feedback_list[:limit]
