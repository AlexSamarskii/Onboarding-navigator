"""Independent boundary checks, fake transport only."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import httpx
import pytest
from analytics.writer import redact
from integrations.ticketing import Ticket, TicketClient
from langchain_core.documents import Document
from telegram_rag_bot.citations import extract_citation
from telegram_rag_bot.hr_adapter import _Facade, LowScoreFallback
from types import SimpleNamespace
from unittest.mock import Mock

@pytest.mark.parametrize('value,secret', [
    ('passphrase="alpha beta"', 'alpha'),
    ('password: abcDEF123', 'abcDEF123'),
    ('api_key=abcdef', 'abcdef'),
    ('Bearer fake-token-value', 'fake-token-value'),
    ('eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature', 'eyJhbGciOiJIUzI1NiJ9'),
    ('contact first.last@example.test', 'first.last@example.test'),
    ('call +7 (999) 123-45-67', '123-45-67'),
])
def test_named_redaction_patterns(value, secret):
    assert secret not in redact(value)
    assert '[REDACTED]' in redact(value)

@pytest.mark.asyncio
async def test_ticket_hash_timezone_and_transport_failure_once():
    requests = []; counts = [0, 0]; delays = []
    class Counter:
        def __init__(self, index): self.index = index
        def inc(self): counts[self.index] += 1
    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout('simulated raw-secret must not escape')
    async def sleep(value): delays.append(value)
    client = TicketClient('https://fake.test', transport=httpx.MockTransport(handle),
                          sleep=sleep, metrics=(Counter(0),Counter(1)))
    ticket = Ticket(12345, 'it_support', 'my id is 12345 password: hidden', 'fallback_x2',
                    timestamp='2026-01-01T03:00:00+03:00')
    first = await client.create(ticket)
    second = await client.create(ticket)
    assert not first.success and second.duplicate
    assert len(requests) == 3 and delays == [1,2] and counts == [0,1]
    payload = json.loads(requests[0].content)
    assert payload['user_id_hash'] == hashlib.sha256(b'12345').hexdigest()
    assert datetime.fromisoformat(payload['timestamp']) == datetime(2026,1,1,tzinfo=timezone.utc)
    assert payload['notify_chat_id'] is None
    assert 'hidden' not in payload['query'] and '12345' not in payload['query']

def test_citation_preserves_whitespace_and_never_mutates():
    docs = [Document(page_content='\n  exact fact.\n', metadata={'source':'faq.md'})]
    original = deepcopy(docs)
    citation = extract_citation(docs, {'faq.md':'Raw source title'})
    assert citation.quote == docs[0].page_content
    assert citation.source_display == 'Raw source title'
    assert docs == original

@pytest.mark.parametrize('distance', [float('inf'), -float('inf'), 'nan', None])
def test_invalid_distance_fails_closed(distance):
    store = SimpleNamespace(index=SimpleNamespace(metric_type=1),
        similarity_search_with_score=Mock(return_value=[(Document(page_content='x'), distance)]))
    with pytest.raises(LowScoreFallback) as error:
        _Facade(store,.65).as_retriever().invoke('q')
    assert error.value.top_score == 0 and error.value.candidates == []
    store.similarity_search_with_score.assert_called_once_with('q', k=3)
