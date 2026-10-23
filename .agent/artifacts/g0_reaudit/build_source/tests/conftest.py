"""
Shared pytest fixtures for telegram-rag-bot tests.

Provides reusable mocks for:
- Telegram objects (Update, Context)
- Config dictionary
- SessionManager
- RAGChainFactory
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update
from telegram.ext import ContextTypes

from telegram_rag_bot.utils.session_manager import SessionManager
from telegram_rag_bot.utils.feedback_collector import FeedbackCollector


@pytest.fixture
def mock_config():
    """
    Test configuration dictionary.

    Returns:
        Dict with minimal config for handlers/chains.
    """
    return {
        "telegram": {"admin_ids": [123, 456]},  # Test admin users
        "modes": {
            "it_support": {
                "faq_file": "faqs/it_support_faq.md",
                "timeout_seconds": 30,
                "system_prompt": "You are IT support assistant.",
                "embedding_provider": "local",
                "vectorstore_provider": "faiss",
                "llm_provider": "gigachat",
            },
            "hr_support": {
                "faq_file": "faqs/hr_faq.md",
                "timeout_seconds": 30,
                "system_prompt": "You are HR support assistant.",
                "embedding_provider": "local",
                "vectorstore_provider": "faiss",
                "llm_provider": "yandex",
            },
        },
        "orchestrator": {"default_model": "gigachat"},
    }


@pytest.fixture
def mock_config_single_unknown_mode():
    """Config where legacy mode 'it_support' does NOT exist.

    Used to test stale-session fallback: simulates Bundle Architecture
    migration where old mode keys are removed from config/modes/.
    """
    return {
        "telegram": {"admin_ids": [123]},
        "modes": {
            "faq_mode": {
                "faq_file": "faqs/faq.md",
                "timeout_seconds": 30,
                "system_prompt": "You are FAQ bot.",
                "embedding_provider": "local",
                "vectorstore_provider": "faiss",
                "llm_provider": "gigachat",
            }
        },
        "orchestrator": {"default_model": "gigachat"},
    }


@pytest.fixture
def mock_update():
    """
    Mock Telegram Update object with default setup.

    Returns:
        AsyncMock with typical Update structure.
    """
    update = AsyncMock(spec=Update)
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.message = AsyncMock()
    update.message.text = "Test question about IT"
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """
    Mock Telegram Context object.

    Returns:
        AsyncMock with ContextTypes.DEFAULT_TYPE spec.
    """
    context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    return context


@pytest.fixture
def mock_session_manager():
    """
    Mock SessionManager with default behavior.

    Returns:
        AsyncMock with get_session/set_session methods.
    """
    manager = AsyncMock()
    manager.get_session.return_value = {
        "mode": "it_support",
        "last_active": "2025-12-22T12:00:00",
    }
    manager.set_session.return_value = None
    return manager


@pytest.fixture
def real_session_manager():
    """
    Real SessionManager instance with in-memory storage.

    Use for testing SessionManager itself or fallback logic.

    Returns:
        SessionManager with redis_url=None (memory mode).
    """
    return SessionManager(redis_url=None)


@pytest.fixture
def mock_rag_factory():
    """
    Mock RAGChainFactory with create_chain/rebuild_index.

    Returns:
        MagicMock with mock chain that returns test answer.
    """
    factory = MagicMock()

    # Mock chain with invoke method
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = {
        "answer": "This is a test answer from the FAQ system.",
        "source_documents": [],
    }

    factory.create_chain.return_value = mock_chain
    factory.rebuild_index.return_value = None

    return factory


@pytest.fixture
def mock_feedback_collector():
    """
    Mock FeedbackCollector with default behavior.

    Returns:
        AsyncMock with save_feedback/get_feedback methods.
    """
    collector = AsyncMock(spec=FeedbackCollector)
    collector.save_feedback = AsyncMock(return_value=True)
    collector.get_feedback = AsyncMock(return_value=[])
    return collector


@pytest.fixture
def mock_callback_query():
    """
    Mock Telegram CallbackQuery object.

    Returns:
        AsyncMock with CallbackQuery structure.
    """
    from telegram import CallbackQuery

    query = AsyncMock(spec=CallbackQuery)
    query.data = "feedback:4"
    query.from_user = AsyncMock()
    query.from_user.id = 12345
    query.message = AsyncMock()
    query.message.text = "Test message"
    query.message.edit_text = AsyncMock()
    query.answer = AsyncMock()
    return query
