"""Independent boundary checks using fakes, no external I/O."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from langchain_core.documents import Document
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
_spec = spec_from_file_location("_review_handler_support", Path(__file__).resolve().parents[1] / "_handlers_support.py")
_support = module_from_spec(_spec)
_spec.loader.exec_module(_support)
setup = _support.setup
from telegram_rag_bot.hr_adapter import LowScoreFallback

@pytest.mark.asyncio
async def test_concurrent_duplicate_ticket_is_one_operation():
    handler, update = setup()
    async def create(*args, **kwargs):
        await asyncio.sleep(0)
        return SimpleNamespace(success=True, ticket_id="synthetic-ticket")
    handler.ticket_client = SimpleNamespace(create=AsyncMock(side_effect=create))
    await asyncio.gather(handler._escalate(update), handler._escalate(update))
    assert handler.ticket_client.create.await_count == 1
    assert (await handler.session_manager.get_session(11))["active_ticket_uuid"] == "synthetic-ticket"

@pytest.mark.asyncio
async def test_success_resets_prior_fallback_and_score_is_once(monkeypatch):
    from telegram_rag_bot import handlers
    handler, update = setup()
    await handler.session_manager.record_rag_fallback(11)
    histogram = Mock()
    monkeypatch.setattr(handlers, "RAG_SCORE", histogram)
    handler.rag_factory.create_chain.return_value = Mock(invoke=Mock(return_value={
        "answer": "answer", "context": [Document(page_content="fact", metadata={"source": "faq.md", "score": .75})]}))
    await handler.handle_message(update, None)
    histogram.observe.assert_called_once_with(.75)
    assert (await handler.session_manager.get_session(11))["rag_fallback_streak"] == 0

@pytest.mark.asyncio
async def test_low_score_retriever_callback_is_not_double_observed(monkeypatch):
    from telegram_rag_bot import handlers
    from langchain_core.retrievers import BaseRetriever
    from langchain_core.runnables import RunnableLambda
    from langchain_classic.chains.retrieval import create_retrieval_chain
    class FailedRetriever(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager):
            raise LowScoreFallback([], .4)
    document_chain = Mock(return_value="should not run")
    handler, update = setup()
    handler.rag_factory.create_chain.return_value = create_retrieval_chain(FailedRetriever(), RunnableLambda(document_chain))
    histogram = Mock()
    monkeypatch.setattr(handlers, "RAG_SCORE", histogram)
    await handler.handle_message(update, None)
    histogram.observe.assert_called_once_with(.4)
    document_chain.assert_not_called()
    assert (await handler.session_manager.get_session(11))["rag_fallback_streak"] == 1
