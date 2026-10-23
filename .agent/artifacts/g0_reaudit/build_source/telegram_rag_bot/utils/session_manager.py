"""
Session management for user context (current mode, history, etc).

Supports both Redis (production) and memory (development) storage.
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SessionManager:
    """
    User session manager with Redis → memory fallback.

    Features:
    - Redis storage (if available)
    - In-memory fallback (dict)
    - TTL support (default 24h)
    - Lazy cleanup (on get_session)
    """

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 86400):
        """
        Initialize SessionManager with Redis → memory fallback.

        Args:
            redis_url: Redis connection URL (None for memory-only)
            ttl_seconds: Session TTL in seconds (default: 24h)
        """
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.memory_store: Dict[int, Dict[str, Any]] = {}
        self.use_redis = False
        self.redis_client = None
        self._active_users = set()  # Track active user IDs for metrics

        # Attempt Redis connection if URL provided
        if redis_url:
            try:
                import redis

                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()  # Verify connection
                self.use_redis = True
                logger.info("✅ Using Redis for session storage")
            except Exception as e:
                logger.warning(
                    f"⚠️ Redis unavailable: {e}. Falling back to memory storage."
                )
                self.use_redis = False
        else:
            logger.info("📦 Using in-memory session storage (MVP mode)")

    async def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user session with lazy TTL cleanup.

        Args:
            user_id: Telegram user ID

        Returns:
            Session dict or None if not found (Redis path only).
            Always returns dict (via _default_session) in memory path.

        Example:
            >>> session = await session_manager.get_session(123)
            >>> if session is None:
            ...     session = {"mode": "it_support"}
        """
        # Track active user for metrics
        self._active_users.add(user_id)

        # Redis path
        if self.use_redis and self.redis_client:
            try:
                data = self.redis_client.get(f"session:{user_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
                # Fall through to memory

        # Memory path (with lazy TTL cleanup)
        if user_id in self.memory_store:
            session = self.memory_store[user_id]

            # Check TTL (lazy cleanup)
            created_at = session.get("created_at")
            if created_at:
                # Parse ISO format datetime string
                try:
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at)
                    else:
                        # Already datetime object
                        created_dt = created_at

                    if datetime.now() - created_dt > timedelta(
                        seconds=self.ttl_seconds
                    ):
                        # TTL expired → delete and return default
                        del self.memory_store[user_id]
                        logger.debug(f"Session expired for user {user_id}")
                        return self._default_session(user_id)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid created_at format for user {user_id}: {e}")
                    # Invalid format → treat as expired
                    del self.memory_store[user_id]
                    return self._default_session(user_id)

            return session

        # Not found → return default
        return self._default_session(user_id)

    async def set_session(self, user_id: int, session: Dict[str, Any]) -> None:
        """
        Set user session with TTL.

        Args:
            user_id: Telegram user ID
            session: Session data dictionary
        """
        # Add created_at if missing
        if "created_at" not in session:
            session["created_at"] = datetime.now().isoformat()

        # Ensure created_at is string for JSON serialization
        if isinstance(session.get("created_at"), datetime):
            session["created_at"] = session["created_at"].isoformat()

        # Redis path
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.setex(
                    f"session:{user_id}", self.ttl_seconds, json.dumps(session)
                )
                return
            except Exception as e:
                logger.error(f"Redis set error: {e}. Falling back to memory.")
                # Fall through to memory

        # Memory path
        self.memory_store[user_id] = session

    def _default_session(self, user_id: int) -> Dict[str, Any]:
        """
        Create default session for new user.

        mode intentionally omitted — handler resolves via DEFAULT_MODE to avoid
        stale-mode issues after config migration (e.g. Bundle Architecture).

        Args:
            user_id: Telegram user ID

        Returns:
            Default session dictionary (no "mode" key)
        """
        return {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
        }

    def get_active_users_count(self) -> int:
        """
        Get count of active user sessions.

        Returns:
            Number of active users (for Prometheus metrics)
        """
        return len(self._active_users)
