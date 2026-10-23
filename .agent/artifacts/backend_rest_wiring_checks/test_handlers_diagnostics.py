from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from _handlers_support import setup,texts,ROOT
from telegram_rag_bot.diagnostics import load_graph

@pytest.mark.asyncio
async def test_diagnostic_flow_preserves_streak():
    h,u=setup();h.diagnostics_graph=load_graph(ROOT/"config/modes/it_support/diagnostics.yaml")
    await h.session_manager.record_rag_fallback(11)
    u.callback_query=SimpleNamespace(data="diag:start:vpn",answer=AsyncMock())
    await h.handle_callback_query(u,None)
    assert (await h.session_manager.get_session(11))["diagnostics_state"]["node"]=="client"
    u.callback_query.data="diag:choice:1"
    await h.handle_callback_query(u,None)
    assert "VPN" in texts(u)
    assert (await h.session_manager.get_session(11))["rag_fallback_streak"]==1
    assert (await h.session_manager.get_session(11))["diagnostics_state"] is None

@pytest.mark.asyncio
async def test_diagnostic_escalation_and_invalid():
    h,u=setup();h.diagnostics_graph=load_graph(ROOT/"config/modes/it_support/diagnostics.yaml")
    h._escalate=AsyncMock()
    u.callback_query=SimpleNamespace(data="diag:escalate",answer=AsyncMock())
    await h.handle_callback_query(u,None);h._escalate.assert_awaited_once()
    u.callback_query.data="diag:choice:99"
    await h.handle_callback_query(u,None)
    assert "Выберите один" in texts(u)

@pytest.mark.asyncio
async def test_diagnostics_escalation_uses_it_context_after_other_mode():
    h,u=setup();h.diagnostics_graph=load_graph(ROOT/"config/modes/it_support/diagnostics.yaml")
    session=await h.session_manager.get_session(11)
    session.update(mode="benefits",last_query="old benefits",active_ticket_uuid="old",ticket_operation={"mode":"benefits","query":"old benefits"})
    await h.session_manager.set_session(11,session)
    h.ticket_client=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(success=True,ticket_id="new")))
    u.callback_query=SimpleNamespace(data="diag:start:vpn",answer=AsyncMock())
    await h.handle_callback_query(u,None)
    u.callback_query.data="diag:escalate"
    await h.handle_callback_query(u,None)
    ticket=h.ticket_client.create.call_args.args[0]
    assert ticket.mode=="it_support" and ticket.query=="diagnostics:vpn"
