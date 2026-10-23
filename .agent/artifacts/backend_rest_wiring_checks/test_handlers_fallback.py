from unittest.mock import Mock,AsyncMock
import pytest
from langchain_core.documents import Document
from _handlers_support import setup,texts
from telegram_rag_bot.hr_adapter import LowScoreFallback
from telegram_rag_bot.utils.metrics import FALLBACK_TOTAL

@pytest.mark.asyncio
async def test_low_score_then_auto_escalates():
    h,u=setup();h.rag_factory.create_chain.return_value=Mock(invoke=Mock(side_effect=LowScoreFallback([],0.5)))
    h.unanswered_writer=Mock();h._escalate=AsyncMock()
    before=FALLBACK_TOTAL.labels(type="rag")._value.get()
    await h.handle_message(u,None);await h.handle_message(u,None)
    assert FALLBACK_TOTAL.labels(type="rag")._value.get()==before+2
    assert h.unanswered_writer.write.call_count==2
    h._escalate.assert_awaited_once()
    assert h._escalate.call_args.args[1]=="fallback_x2"
    assert "нет подтверждённого ответа" in texts(u)

@pytest.mark.asyncio
async def test_context_is_cited_and_full_quote_not_truncated():
    h,u=setup();doc=Document(page_content="exact"*1000,metadata={"source":"faq.md","score":0.7})
    h.rag_factory.create_chain.return_value=Mock(invoke=Mock(return_value={"answer":"fact","context":[doc]}))
    await h.handle_message(u,None)
    assert "Источник: IT-доступы" in texts(u)
    assert "".join(call.args[0] for call in u.message.reply_text.call_args_list).count("exact")==1000
    assert (await h.session_manager.get_session(11))["rag_fallback_streak"]==0

@pytest.mark.asyncio
async def test_retrieval_score_recorded_once_if_llm_fails(monkeypatch):
    from telegram_rag_bot import handlers
    from langchain_core.runnables import RunnableLambda
    from langchain_core.retrievers import BaseRetriever
    from langchain_classic.chains.retrieval import create_retrieval_chain
    class Retriever(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager):
            return [Document(page_content="fact",metadata={"source":"faq.md","score":.8})]
    def fail(value):raise RuntimeError("fake LLM fail")
    h,u=setup()
    h.rag_factory.create_chain.return_value=create_retrieval_chain(Retriever(),RunnableLambda(fail))
    histogram=Mock();monkeypatch.setattr(handlers,"RAG_SCORE",histogram)
    await h.handle_message(u,None)
    histogram.observe.assert_called_once_with(.8)

@pytest.mark.asyncio
async def test_unknown_citation_and_display_name_literal():
    h,u=setup();h.mode_display_names["it_support"]="Untranslated custom mode"
    assert h._get_mode_display("it_support")=="Untranslated custom mode"
    doc=Document(page_content="fact",metadata={"source":"not-allowed.md","score":.7})
    h.rag_factory.create_chain.return_value=Mock(invoke=Mock(return_value={"answer":"answer","context":[doc]}))
    await h.handle_message(u,None)
    assert "основание недоступно" in texts(u)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["synthetic quota denied", None])
async def test_legacy_platform_quota_denial_before_chain(monkeypatch, message):
    from telegram_rag_bot import handlers
    h,u=setup()
    h.config["platform"]={"tenant_id":"synthetic-tenant", "callback_url":"https://synthetic.invalid"}
    quota=AsyncMock(return_value=(False,message))
    monkeypatch.setattr(handlers,"check_quota_before_llm",quota)
    await h.handle_message(u,None)
    quota.assert_awaited_once_with("synthetic-tenant","https://synthetic.invalid")
    h.rag_factory.create_chain.assert_not_called()
    assert (message or handlers.t("errors.access_limited")) in texts(u)


@pytest.mark.asyncio
async def test_legacy_platform_quota_allow_preserves_retrieval(monkeypatch):
    from telegram_rag_bot import handlers
    h,u=setup()
    h.config["platform"]={"tenant_id":"synthetic-tenant", "callback_url":"https://synthetic.invalid"}
    quota=AsyncMock(return_value=(True,None))
    monkeypatch.setattr(handlers,"check_quota_before_llm",quota)
    h.rag_factory.create_chain.return_value=Mock(invoke=Mock(return_value={"answer":"answer","context":[]}))
    await h.handle_message(u,None)
    quota.assert_awaited_once()
    h.rag_factory.create_chain.assert_called_once_with("it_support")
    assert "answer" in texts(u)
