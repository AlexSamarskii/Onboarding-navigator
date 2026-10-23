"""Minimal redacted JSONL analytics. Redaction is heuristic, not a privacy guarantee."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from threading import RLock

_LOCK = RLock()
_PATTERNS = (
    r'\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b',
    r'(?i)\b(?:bearer)\s+\S+',
    r'(?i)\b(?:password|passwd|passphrase|token|api[_-]?key|secret|пароль|токен)\b\s*[:=]\s*(?:"[^"]*"|\'[^\']*\'|\S+)',
    r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
    r'(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)',
    r'(?i)\b(?:telegram[_ ]?id|user[_ ]?id)\s*[:=]\s*\d+',
)


def redact(text: str, raw_id=None) -> str:
    if not isinstance(text, str):
        raise ValueError('query must be text')
    if raw_id is not None:
        text = re.sub(r'(?<!\d)' + re.escape(str(raw_id)) + r'(?!\d)', '[REDACTED]', text)
    for pattern in _PATTERNS:
        text = re.sub(pattern, '[REDACTED]', text)
    return text


def safe_score(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('top_score must be finite and within [0,1]')
    return float(value)


@dataclass(frozen=True)
class UnansweredEntry:
    mode: str
    reason: str
    query_redacted: str
    top_score: float | None = None


class UnansweredWriter:
    """Process-local thread serialization only; infra must provide a writable parent.

    Each append is one UTF-8 write under a shared process lock. Multiple processes
    writing the same volume need an external writer; no shared-state claim is made.
    """
    def __init__(self, path, *, fsync=False):
        self.path = Path(path)
        self.fsync = fsync

    def write(self, entry: UnansweredEntry):
        if entry.reason not in {'missing_plan', 'low_score'} or not isinstance(entry.mode, str):
            raise ValueError('invalid unanswered entry')
        record = dict(timestamp=datetime.now(timezone.utc).isoformat(), mode=entry.mode,
                      reason=entry.reason, query_redacted=redact(entry.query_redacted),
                      top_score=safe_score(entry.top_score))
        line = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        with _LOCK:
            with self.path.open('ab', buffering=0) as stream:
                if stream.write(line) != len(line):
                    raise OSError('incomplete analytics append')
                if self.fsync:
                    import os
                    os.fsync(stream.fileno())
