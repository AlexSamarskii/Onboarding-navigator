"""
Session management for user context (current mode, history, etc).

Supports both Redis (production) and memory (development) storage.
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from functools import wraps
from collections import defaultdict
from asyncio import Lock

logger = logging.getLogger(__name__)


def _serialized_event(method):
    @wraps(method)
    async def wrapped(self, user_id, *args, **kwargs):
        async with self._event_locks[user_id]:
            return await method(self, user_id, *args, **kwargs)
    return wrapped


class SessionManager:
    """
    User session manager with Redis → memory fallback.

    Features:
    - Redis storage (if available)
    - In-memory fallback (dict)
    - TTL support (default 24h)
    - Lazy cleanup (on get_session)

    Memory fallback is process-local only: it provides neither shared state nor
    cross-pod ticket deduplication. Redis I/O remains synchronous with bounded
    socket/connect timeouts. Event helpers serialize same-session updates within this process/event loop;
    callers performing manual get/set read-modify-write must serialize themselves.
    set_profile is the explicit profile-input API; set_session never refreshes
    its set_at_iso. record_rag_fallback/record_rag_success/record_ticket_created
    are the only automatic streak event APIs; diagnostics writes do not count.
    """

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 86400):
        """
        Initialize SessionManager with Redis → memory fallback.

        Args:
            redis_url: Redis connection URL (None for memory-only)
            ttl_seconds: Session TTL in seconds (default: 24h)
        """
        if type(ttl_seconds) is not int or ttl_seconds < 0:
            raise ValueError("ttl_seconds must be a nonnegative integer")
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.memory_store: Dict[int, Dict[str, Any]] = {}
        self.use_redis = False
        self._event_locks = defaultdict(Lock)
        self.redis_client = None
        self._active_users = set()  # Track active user IDs for metrics

        # Attempt Redis connection if URL provided
        if redis_url:
            try:
                import redis

                self.redis_client = redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
                self.redis_client.ping()  # Verify connection
                self.use_redis = True
                logger.info("✅ Using Redis for session storage")
            except Exception as e:
                logger.warning(
                    "Redis unavailable; using process-local memory storage"
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
            Session dictionary normalized identically for Redis and memory.
            A miss yields _default_session, preserving the legacy behavior.

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
                    session = self._normalize(user_id, json.loads(data))
                    return session
            except Exception as e:
                logger.error("Redis read failed; using process-local memory")
                # Fall through to memory

        # Same explicit profile expiry applies to either storage backend.
        if user_id in self.memory_store:
            session = self._normalize(user_id, self.memory_store[user_id])
            if session.get("created_at") != self.memory_store[user_id].get("created_at"):
                if session.get("profile"):
                    self.memory_store[user_id] = deepcopy(session)
                else:
                    del self.memory_store[user_id]
            return session
        return self._default_session(user_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            raise ValueError("invalid session timestamp")
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    def _expired(self, value: Any, now: datetime, legacy_local: bool = False) -> bool:
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
            if legacy_local and isinstance(parsed, datetime) and parsed.tzinfo is None:
                # Baseline created_at was written with datetime.now(), in local time.
                parsed = parsed.astimezone(timezone.utc)
            elapsed = (now - self._timestamp(parsed)).total_seconds()
            return elapsed < 0 or elapsed >= self.ttl_seconds
        except (TypeError, ValueError, OverflowError):
            return True

    def _normalize(self, user_id: int, stored: Any) -> dict:
        now = self._now()
        if not isinstance(stored, dict):
            return self._default_session(user_id)
        session = deepcopy(stored)
        profile = session.get("profile")
        has_profile = isinstance(profile, dict) and bool(profile)
        profile_expired = has_profile and self._expired(profile.get("set_at_iso"), now)
        session_expired = "created_at" in session and self._expired(session["created_at"], now, legacy_local=True)
        if profile_expired:
            session["profile"] = {}
            session["rag_fallback_streak"] = 0
            session["diagnostics_state"] = {}
            session["active_ticket_uuid"] = None
        if session_expired:
            # A newly entered profile must survive an older session window.
            fresh = self._default_session(user_id)
            if has_profile and not profile_expired:
                fresh["profile"] = session["profile"]
            session = fresh
        session.setdefault("profile", {})
        session.setdefault("diagnostics_state", {})
        session.setdefault("rag_fallback_streak", 0)
        session.setdefault("active_ticket_uuid", None)
        return session

    @_serialized_event
    async def set_profile(self, user_id: int, role: str, department: str) -> dict:
        """Record explicit input; this alone starts/refreshes the profile TTL."""
        if not isinstance(role, str) or not isinstance(department, str):
            raise ValueError("role and department must be strings")
        session = await self.get_session(user_id)
        session["profile"] = {"role": role, "department": department,
                              "set_at_iso": self._now().isoformat()}
        await self.set_session(user_id, session)
        return session

    @_serialized_event
    async def record_rag_fallback(self, user_id: int) -> dict:
        """Count only a confirmed low-score RAG event, never diagnostics/LLM switches."""
        session = await self.get_session(user_id)
        session["rag_fallback_streak"] += 1
        await self.set_session(user_id, session)
        return session

    @_serialized_event
    async def record_rag_success(self, user_id: int) -> dict:
        session = await self.get_session(user_id)
        session["rag_fallback_streak"] = 0
        await self.set_session(user_id, session)
        return session

    @_serialized_event
    async def record_ticket_created(self, user_id: int) -> dict:
        """Clear the streak and active operation only on confirmed creation."""
        session = await self.get_session(user_id)
        session["rag_fallback_streak"] = 0
        session["active_ticket_uuid"] = None
        await self.set_session(user_id, session)
        return session

    async def set_session(self, user_id: int, session: Dict[str, Any]) -> None:
        """
        Set user session with TTL.

        Args:
            user_id: Telegram user ID
            session: Session data dictionary
        """
        session = deepcopy(session)
        # TTL zero means immediate expiry, not invalid Redis SETEX 0.
        if self.ttl_seconds == 0:
            self.memory_store.pop(user_id, None)
            if self.use_redis and self.redis_client:
                try:
                    self.redis_client.delete(f"session:{user_id}")
                except Exception:
                    logger.error("Redis expiry failed")
            return
        if "created_at" not in session:
            session["created_at"] = self._now().isoformat()
        session.setdefault("profile", {})
        session.setdefault("diagnostics_state", {})
        session.setdefault("rag_fallback_streak", 0)
        session.setdefault("active_ticket_uuid", None)

        # Ensure created_at is string for JSON serialization
        if isinstance(session.get("created_at"), datetime):
            created = session["created_at"]
            # Baseline accepts naive local datetime objects as well as strings.
            # Convert via local timezone, never attach UTC to a local wall time.
            session["created_at"] = created.astimezone(timezone.utc).isoformat()

        # Redis path
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.setex(
                    f"session:{user_id}", self.ttl_seconds, json.dumps(session)
                )
                return
            except Exception as e:
                logger.error("Redis write failed; using process-local memory")
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
            "created_at": self._now().isoformat(),
            "profile": {},
            "diagnostics_state": {},
            "rag_fallback_streak": 0,
            "active_ticket_uuid": None,
        }

    def get_active_users_count(self) -> int:
        """
        Get count of active user sessions.

        Returns:
            Number of active users (for Prometheus metrics)
        """
        return len(self._active_users)
