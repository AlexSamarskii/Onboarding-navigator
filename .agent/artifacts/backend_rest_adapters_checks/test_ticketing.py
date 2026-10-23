import json
import logging
import httpx
import pytest
from integrations.ticketing import TicketClient, Ticket

class Counter:
    def __init__(self):self.count=0
    def inc(self):self.count+=1

@pytest.mark.asyncio
@pytest.mark.parametrize('statuses,success,delays', [([201],True,[]),([500,500,500],False,[1,2]),([500,200],True,[1])])
async def test_retry_payload_metrics_redaction_and_dedupe(statuses,success,delays,caplog):
    calls=[]; sleeps=[]; created=Counter();failed=Counter()
    def handle(request):
        calls.append(request)
        return httpx.Response(statuses[len(calls)-1])
    async def sleep(seconds):sleeps.append(seconds)
    client=TicketClient('https://fake.test/hook', 'hr', transport=httpx.MockTransport(handle), sleep=sleep, metrics=(created,failed))
    ticket=Ticket(123456789,'it_support','password=hunter2 token=abcdef mail me a@b.test user_id=123456789','explicit',.7)
    session={}
    with caplog.at_level(logging.ERROR):result=await client.create(ticket,session=session)
    assert result.success is success
    assert sleeps==delays
    assert len(calls)==len(statuses)
    payloads=[json.loads(call.content) for call in calls]
    assert all(p==payloads[0] for p in payloads)
    payload=payloads[0]
    assert set(payload)=={'ticket_id','user_id_hash','mode','query','timestamp','reason','top_score','notify_chat_id'}
    assert len(payload['user_id_hash'])==64
    assert payload['timestamp'].endswith('+00:00')
    assert all(v not in payload['query'] for v in ['hunter2','abcdef','a@b.test','123456789'])
    assert all(r.extensions['timeout']['read']==5 for r in calls)
    await client.create(ticket,session=session)
    assert len(calls)==len(statuses)
    assert created.count==int(success) and failed.count==int(not success)
    assert 'hunter2' not in caplog.text and '123456789' not in caplog.text

@pytest.mark.asyncio
async def test_existing_session_ticket_never_posts():
    def handle(request):raise AssertionError('duplicate must not send')
    client=TicketClient('https://fake.test', transport=httpx.MockTransport(handle))
    ticket=Ticket(42,'it_support','help','explicit')
    result=await client.create(ticket,session={'active_ticket_uuid':ticket.ticket_id})
    assert result.duplicate and result.success
