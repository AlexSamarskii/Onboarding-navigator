from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from _handlers_support import setup,texts

@pytest.mark.asyncio
async def test_explicit_success_and_duplicate():
    h,u=setup()
    h.ticket_client=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(success=True,ticket_id="confirmed")))
    await h._escalate(u)
    assert h.ticket_client.create.call_args.args[0].reason=="explicit"
    assert (await h.session_manager.get_session(11))["active_ticket_uuid"]=="confirmed"
    await h._escalate(u)
    assert h.ticket_client.create.await_count==1
    assert "confirmed" in texts(u)

@pytest.mark.asyncio
async def test_failed_ticket():
    h,u=setup();h.ticket_client=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(success=False)))
    await h._escalate(u)
    assert "не удалось создать заявку" in texts(u)

@pytest.mark.asyncio
async def test_distinct_mode_or_query_is_not_blocked_by_old_ticket():
    h,u=setup()
    h.ticket_client=SimpleNamespace(create=AsyncMock(side_effect=[
        SimpleNamespace(success=True,ticket_id="first"),SimpleNamespace(success=True,ticket_id="second")]))
    await h._escalate(u, query="vpn issue")
    session=await h.session_manager.get_session(11)
    session.update(mode="onboarding_plan",last_query="onboarding_plan:unknown/unknown")
    await h.session_manager.set_session(11,session)
    await h._escalate(u)
    assert h.ticket_client.create.await_count==2
    second=h.ticket_client.create.call_args.args[0]
    assert second.mode=="onboarding_plan" and second.query=="onboarding_plan:unknown/unknown"
    await h._escalate(u)
    assert h.ticket_client.create.await_count==2
