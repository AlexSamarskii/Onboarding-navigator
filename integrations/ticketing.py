"""Timeout-bound webhook delivery with process-local UUID deduplication.

No cross-pod dedupe/shared state is promised. Memory fallback is process-local.
Query redaction is heuristic and cannot guarantee removal of all sensitive data.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
import uuid
import httpx
from analytics.writer import redact, safe_score
from telegram_rag_bot.utils.metrics import TICKETS_CREATED, TICKETS_FAILED

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Ticket:
    user_id: int
    mode: str
    query: str
    reason: str
    top_score: float | None = None
    ticket_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class TicketResult:
    ticket_id: str
    success: bool
    duplicate: bool = False
    error_key: str | None = None


class TicketClient:
    def __init__(self, url, hr_chat_id=None, timeout=5, max_attempts=3, backoff=(1, 2, 4), *, transport=None, sleep=asyncio.sleep, metrics=None):
        if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
            raise ValueError('ticket URL must be HTTP(S)')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError('invalid ticket timeout')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError('at most three attempts allowed')
        if len(backoff) < max_attempts - 1 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 60 for x in backoff):
            raise ValueError('invalid backoff')
        if hr_chat_id is not None and not isinstance(hr_chat_id, str):
            raise ValueError('HR chat ID must be a string or None')
        self.url, self.hr_chat_id, self.timeout = url, hr_chat_id, timeout
        self.max_attempts, self.backoff = max_attempts, tuple(backoff)
        self.transport, self.sleep = transport, sleep
        self.created, self.failed = metrics or (TICKETS_CREATED, TICKETS_FAILED)
        self._results = {}
        self._lock = asyncio.Lock()

    async def create(self, ticket: Ticket, *, session=None) -> TicketResult:
        """Three POSTs maximum; sleeps 1/2 before attempts 2/3, never after failure.

        A successful UUID is retained in-process and written to the supplied
        mutable session. Caller persists that session using its session manager.
        HTTP transport and sleep may be injected; tests need no real network.
        """
        ticket_id = str(uuid.UUID(str(ticket.ticket_id)))
        if type(ticket.user_id) is not int or ticket.reason not in {'explicit', 'fallback_x2'} or not isinstance(ticket.mode, str):
            raise ValueError('invalid ticket')
        timestamp = datetime.fromisoformat(ticket.timestamp.replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('timestamp requires timezone')
        payload = dict(ticket_id=ticket_id,
                       user_id_hash=hashlib.sha256(str(ticket.user_id).encode()).hexdigest(),
                       mode=ticket.mode, query=redact(ticket.query, ticket.user_id),
                       timestamp=timestamp.astimezone(timezone.utc).isoformat(),
                       reason=ticket.reason, top_score=safe_score(ticket.top_score),
                       notify_chat_id=self.hr_chat_id)
        async with self._lock:
            if ticket_id in self._results:
                result = self._results[ticket_id]
                return TicketResult(ticket_id, result.success, True, result.error_key)
            if session is not None and session.get('active_ticket_uuid') == ticket_id:
                return TicketResult(ticket_id, True, True)
            async with httpx.AsyncClient(transport=self.transport, trust_env=False) as client:
                for attempt in range(self.max_attempts):
                    if attempt:
                        await self.sleep(self.backoff[attempt - 1])
                    try:
                        response = await client.post(self.url, json=payload, timeout=self.timeout)
                        success = 200 <= response.status_code < 300
                    except (httpx.HTTPError, OSError):
                        success = False
                    if success:
                        self.created.inc()
                        if session is not None:
                            session['active_ticket_uuid'] = ticket_id
                        result = TicketResult(ticket_id, True)
                        self._results[ticket_id] = result
                        return result
            self.failed.inc()
            logger.error('ticket delivery failed after bounded attempts')
            result = TicketResult(ticket_id, False, error_key='ticket.failed')
            self._results[ticket_id] = result
            return result
