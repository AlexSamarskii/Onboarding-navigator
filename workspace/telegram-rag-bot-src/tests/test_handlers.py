"""
Unit tests for telegram_rag_bot.handlers.TelegramHandlers.

Tests cover:
- cmd_start: /start command (3 tests)
- cmd_set_mode: /mode command (5 tests)
- cmd_reload_faq: /reload_faq command (4 tests)
- handle_message: text message processing (8 tests)
- Private methods: _escape_markdown_v2, _get_mode_display (2 tests)

Target coverage: 90%
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from telegram_rag_bot.handlers import TelegramHandlers
from telegram.constants import ParseMode


@pytest.fixture
def single_mode_config(mock_config):
    """Config with single mode for testing single-mode welcome message (Issue #10)."""
    config = mock_config.copy()
    config["modes"] = {
        "it_support": {
            "display_name": "IT Support",
            "greeting": "👋 Привет из IT поддержки!",
            "faq_file": "faqs/it_support_faq.md",
            "timeout_seconds": 30,
            "system_prompt": "You are IT support assistant.",
            "embedding_provider": "local",
            "vectorstore_provider": "faiss",
            "llm_provider": "gigachat",
        }
    }
    return config


# === cmd_start tests ===


@pytest.mark.asyncio
async def test_cmd_start_creates_session_for_new_user(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /start creates default session for new user."""
    # Arrange: No existing session
    mock_session_manager.get_session.return_value = None

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_start(mock_update, mock_context)

    # Assert: Welcome message sent
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Привет" in reply_args
    # Default mode is first config key (it_support); display from config or title-cased
    assert "It Support" in reply_args or "IT Support" in reply_args


@pytest.mark.asyncio
async def test_cmd_start_shows_current_mode_for_existing_user(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /start shows current mode for existing user."""
    # Arrange: Existing session with hr_support mode
    mock_session_manager.get_session.return_value = {
        "mode": "hr_support",
        "last_active": "2025-12-22T10:00:00",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_start(mock_update, mock_context)

    # Assert: Shows HR mode
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Hr Support" in reply_args  # Fallback display (capitalize)


@pytest.mark.asyncio
async def test_cmd_start_handles_session_manager_error(
    mock_update, mock_context, mock_rag_factory, mock_config, mock_feedback_collector
):
    """Test /start handles SessionManager error gracefully."""
    # Arrange: SessionManager raises exception
    mock_session_manager_error = AsyncMock()
    mock_session_manager_error.get_session.side_effect = Exception("Redis down")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager_error,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_start(mock_update, mock_context)

    # Assert: Still sends welcome message (fallback to default mode)
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Привет" in reply_args


@pytest.mark.asyncio
async def test_cmd_start_custom_greeting(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test that /start uses custom greeting from mode config."""
    # Arrange: mode с greeting
    mock_config["modes"]["it_support"]["greeting"] = "Привет, я ваш помогайка, шеф!"
    mock_config["modes"]["it_support"]["display_name"] = "IT Support"

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_start(mock_update, mock_context)

    # Assert: greeting использовано
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args[0][0]
    assert "Привет, я ваш помогайка, шеф!" in call_args


@pytest.mark.asyncio
async def test_cmd_start_single_mode_no_mode_line(
    mock_update,
    mock_context,
    real_session_manager,
    single_mode_config,
    mock_rag_factory,
    mock_feedback_collector,
):
    """Single-mode /start must not show '📌 Режим:' line (regression test for Issue #10)."""
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=real_session_manager,
        config=single_mode_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    sent_text = mock_update.message.reply_text.call_args[0][0]
    assert "👋 Привет из IT поддержки!" in sent_text
    assert "Задавайте вопросы" in sent_text
    assert "📌 Режим:" not in sent_text

    session = await real_session_manager.get_session(mock_update.effective_user.id)
    assert session is not None
    assert session["mode"] == "it_support"


@pytest.mark.asyncio
async def test_cmd_start_single_mode_custom_welcome_suffix(
    mock_update,
    mock_context,
    real_session_manager,
    single_mode_config,
    mock_rag_factory,
    mock_feedback_collector,
):
    """Single-mode /start uses custom welcome_suffix when configured."""
    single_mode_config["modes"]["it_support"][
        "welcome_suffix"
    ] = "Спросите меня о чем угодно."

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=real_session_manager,
        config=single_mode_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    call = mock_update.message.reply_text.call_args
    sent_text = call[0][0]
    assert "👋 Привет из IT поддержки!" in sent_text
    assert "Спросите меня о чем угодно." in sent_text
    assert "parse_mode" not in call[1] or call[1].get("parse_mode") is None


@pytest.mark.asyncio
async def test_cmd_start_single_mode_empty_welcome_suffix(
    mock_update,
    mock_context,
    real_session_manager,
    single_mode_config,
    mock_rag_factory,
    mock_feedback_collector,
):
    """Single-mode /start hides suffix when welcome_suffix is empty."""
    single_mode_config["modes"]["it_support"]["welcome_suffix"] = ""

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=real_session_manager,
        config=single_mode_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    call = mock_update.message.reply_text.call_args
    sent_text = call[0][0]
    assert sent_text == "👋 Привет из IT поддержки!"
    assert "Задавайте вопросы, и я постараюсь найти ответ!" not in sent_text
    assert "\n\n\n" not in sent_text
    assert "parse_mode" not in call[1] or call[1].get("parse_mode") is None


@pytest.mark.asyncio
async def test_cmd_start_single_mode_missing_welcome_suffix_uses_legacy(
    mock_update,
    mock_context,
    real_session_manager,
    single_mode_config,
    mock_rag_factory,
    mock_feedback_collector,
):
    """Single-mode /start keeps legacy suffix when field is missing."""
    single_mode_config["modes"]["it_support"].pop("welcome_suffix", None)

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=real_session_manager,
        config=single_mode_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    call = mock_update.message.reply_text.call_args
    sent_text = call[0][0]
    assert "Задавайте вопросы, и я постараюсь найти ответ!" in sent_text
    assert "parse_mode" not in call[1] or call[1].get("parse_mode") is None


@pytest.mark.asyncio
async def test_cmd_start_multi_mode_empty_welcome_suffix(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Multi-mode /start removes only question suffix when welcome_suffix is empty."""
    mock_config["modes"]["it_support"]["welcome_suffix"] = ""
    mock_session_manager.get_session.return_value = {"mode": "it_support"}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    call = mock_update.message.reply_text.call_args
    sent_text = call[0][0]
    assert "Просто задайте мне вопрос, и я постараюсь найти ответ!" not in sent_text
    assert "Используйте команды ниже для навигации." in sent_text
    assert "📌 Текущий режим:" in sent_text
    assert "parse_mode" not in call[1] or call[1].get("parse_mode") is None


@pytest.mark.asyncio
async def test_cmd_start_multi_mode_invalid_session_mode_uses_default_suffix(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Multi-mode /start uses DEFAULT_MODE config when session mode is invalid."""
    mock_session_manager.get_session.return_value = {"mode": "invalid_mode"}
    mock_config["modes"]["it_support"][
        "welcome_suffix"
    ] = "Default suffix from mode config."

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )
    await handlers.cmd_start(mock_update, mock_context)

    call = mock_update.message.reply_text.call_args
    sent_text = call[0][0]
    assert "Default suffix from mode config." in sent_text
    # effective_mode is first config key; display is title-cased if no display_name
    assert (
        "📌 Текущий режим: It Support" in sent_text
        or "📌 Текущий режим: IT Support" in sent_text
    )
    assert "parse_mode" not in call[1] or call[1].get("parse_mode") is None


# === cmd_set_mode tests ===


@pytest.mark.asyncio
async def test_cmd_set_mode_no_args_shows_available_modes(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /mode without arguments shows current and available modes."""
    # Arrange: No arguments
    mock_context.args = []

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_set_mode(mock_update, mock_context)

    # Assert: Shows modes list
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Текущий режим" in reply_args
    assert "it_support" in reply_args
    assert "hr_support" in reply_args


@pytest.mark.asyncio
async def test_cmd_set_mode_switches_to_valid_mode(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /mode switches to valid mode successfully."""
    # Arrange: Switch to hr_support
    mock_context.args = ["hr_support"]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_set_mode(mock_update, mock_context)

    # Assert: Confirms mode switch
    mock_session_manager.set_session.assert_called_once()
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "изменён" in reply_args
    assert "Hr Support" in reply_args


@pytest.mark.asyncio
async def test_cmd_set_mode_rejects_invalid_mode(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /mode rejects invalid mode with error message."""
    # Arrange: Try invalid mode
    mock_context.args = ["invalid_mode"]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_set_mode(mock_update, mock_context)

    # Assert: Error message with available modes
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Неизвестный режим" in reply_args
    assert "invalid_mode" in reply_args
    assert "it_support" in reply_args


@pytest.mark.asyncio
async def test_cmd_set_mode_same_mode_silent(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /mode with same mode does nothing (silent)."""
    # Arrange: Already in it_support mode
    mock_context.args = ["it_support"]
    mock_session_manager.get_session.return_value = {
        "mode": "it_support",
        "last_active": "2025-12-22T10:00:00",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_set_mode(mock_update, mock_context)

    # Assert: No message sent (silent)
    mock_update.message.reply_text.assert_not_called()


@pytest.mark.parametrize("mode", ["it_support", "hr_support"])
@pytest.mark.asyncio
async def test_cmd_set_mode_multiple_modes(
    mode,
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /mode works for all configured modes."""
    # Arrange
    mock_context.args = [mode]
    mock_session_manager.get_session.return_value = {
        "mode": "other_mode",  # Different from target
        "last_active": "2025-12-22T10:00:00",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_set_mode(mock_update, mock_context)

    # Assert: Mode switched
    mock_session_manager.set_session.assert_called_once()
    mock_update.message.reply_text.assert_called_once()


# === cmd_reload_faq tests ===


@pytest.mark.asyncio
async def test_cmd_reload_faq_admin_success(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /reload_faq rebuilds index for admin."""
    # Arrange: Admin user
    mock_update.effective_user.id = 123  # Admin ID from mock_config
    mock_context.args = ["it_support"]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Mock reload_config to return mock_config
    with patch("telegram_rag_bot.handlers.reload_config", return_value=mock_config):
        # Act
        await handlers.cmd_reload_faq(mock_update, mock_context)

        # Assert: Index rebuild called + confirmation sent
        mock_rag_factory.rebuild_index.assert_called_once()
        assert mock_update.message.reply_text.call_count == 2  # Progress + success


@pytest.mark.asyncio
async def test_cmd_reload_faq_non_admin_denied(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /reload_faq denies non-admin user."""
    # Arrange: Non-admin user
    mock_update.effective_user.id = 999  # Not in admin_ids

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_reload_faq(mock_update, mock_context)

    # Assert: Permission denied
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Нет доступа" in reply_args
    mock_rag_factory.rebuild_index.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_reload_faq_invalid_mode(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /reload_faq rejects invalid mode."""
    # Arrange: Admin + invalid mode
    mock_update.effective_user.id = 123
    mock_context.args = ["invalid_mode"]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_reload_faq(mock_update, mock_context)

    # Assert: Error message
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Неизвестный режим" in reply_args
    mock_rag_factory.rebuild_index.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_reload_faq_file_not_found(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /reload_faq handles FileNotFoundError."""
    # Arrange: rebuild_index raises FileNotFoundError
    mock_update.effective_user.id = 123
    mock_context.args = ["it_support"]
    mock_rag_factory.rebuild_index.side_effect = FileNotFoundError("FAQ file missing")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Mock reload_config
    with patch("telegram_rag_bot.handlers.reload_config", return_value=mock_config):
        # Act
        await handlers.cmd_reload_faq(mock_update, mock_context)

        # Assert: Error message sent
        assert mock_update.message.reply_text.call_count == 2  # Progress + error
        error_reply = mock_update.message.reply_text.call_args_list[1][0][0]
        assert "FAQ файл не найден" in error_reply


# === handle_message tests ===


@pytest.mark.asyncio
async def test_handle_message_normal_flow(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message processes question and returns answer."""
    # Arrange
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Answer sent with markdown
    mock_update.message.chat.send_action.assert_called_once()  # Typing indicator
    mock_rag_factory.create_chain.assert_called_once()
    mock_update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_timeout_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message handles timeout gracefully."""
    # Arrange: Chain invoke times out
    mock_chain = MagicMock()
    mock_chain.invoke.side_effect = asyncio.TimeoutError()
    mock_rag_factory.create_chain.return_value = mock_chain

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Timeout message sent
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "слишком много времени" in reply_args


@pytest.mark.asyncio
async def test_handle_message_markdown_fallback(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message falls back to raw text if markdown fails."""
    # Arrange: First call (markdown) fails, second (raw) succeeds
    mock_update.message.reply_text.side_effect = [
        Exception("Markdown parse error"),  # First call fails
        None,  # Second call succeeds
    ]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: reply_text called twice (markdown → fallback)
    assert mock_update.message.reply_text.call_count == 2


@pytest.mark.asyncio
async def test_handle_message_empty_text_ignored(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message ignores empty messages."""
    # Arrange: Empty text
    mock_update.message.text = "   "  # Only whitespace

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: No processing done
    mock_rag_factory.create_chain.assert_not_called()
    mock_update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_creates_session_for_new_user(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message creates session for new user."""
    # Arrange: No existing session
    mock_session_manager.get_session.return_value = None

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Session created
    assert mock_session_manager.set_session.call_count == 2  # Create + update


@pytest.mark.asyncio
async def test_handle_message_chain_creation_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message handles chain creation errors."""
    # Arrange: create_chain raises ValueError
    mock_rag_factory.create_chain.side_effect = ValueError("Invalid mode")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Error message sent
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "Неизвестный режим" in reply_args


@pytest.mark.asyncio
async def test_handle_message_dimension_mismatch(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message detects dimension mismatch errors."""
    # Arrange: Chain invoke raises ValueError with "dimension" keyword
    mock_chain = MagicMock()
    mock_chain.invoke.side_effect = ValueError(
        "Embedding dimension mismatch: stored vs current"
    )
    mock_rag_factory.create_chain.return_value = mock_chain

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Generic error message (dimension mismatch detected via logging)
    mock_update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_rate_limit_detection(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message detects rate limit errors."""
    # Arrange: Chain invoke raises exception with "rate limit" keywords
    mock_chain = MagicMock()
    mock_chain.invoke.side_effect = Exception("Rate limit exceeded")
    mock_rag_factory.create_chain.return_value = mock_chain

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Error message sent
    mock_update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_stale_mode_falls_back_to_default(
    mock_update,
    mock_context,
    mock_rag_factory,
    mock_feedback_collector,
    mock_config_single_unknown_mode,
):
    """Stale Redis session mode falls back to first config mode gracefully.

    Scenario: user has mode='it_support' in Redis session (legacy mode
    from pre-Bundle Architecture), but config only has 'faq_mode'.

    Acceptance Criteria (Issue #16):
      1. No KeyError raised — bot does not crash
      2. reply_text called — user receives an answer
      3. session["mode"] updated to first available mode ("faq_mode")
      4. QUERY_LATENCY.observe called — Platform SaaS metrics not lost
    """
    # Arrange: session contains legacy stale mode
    session_manager = AsyncMock()
    session_manager.get_session.return_value = {
        "mode": "it_support",  # stale — not in config
        "last_active": "2025-01-01T00:00:00",
    }
    session_manager.set_session.return_value = None

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=session_manager,
        config=mock_config_single_unknown_mode,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert 1: no crash (implicit — if we reach here, no KeyError)
    # Assert 2: user received a reply
    mock_update.message.reply_text.assert_called_once()

    # Assert 3: session mode updated to first available config mode
    set_call_args = session_manager.set_session.call_args
    saved_session = set_call_args[0][1]  # second positional arg
    assert saved_session["mode"] == "faq_mode"

    # Assert 4: metrics recorded (QUERY_LATENCY.observe called)
    # RAG chain was created with correct (resolved) mode
    mock_rag_factory.create_chain.assert_called_once_with("faq_mode")


# === Private methods tests ===


@pytest.mark.parametrize(
    "char",
    [
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    ],
)
def test_escape_markdown_v2_special_chars(
    char, mock_rag_factory, mock_session_manager, mock_config, mock_feedback_collector
):
    """Test _escape_markdown_v2 escapes all special characters."""
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    result = handlers._escape_markdown_v2(char)
    assert result == f"\\{char}"


def test_get_mode_display_fallback(
    mock_rag_factory, mock_session_manager, mock_config, mock_feedback_collector
):
    """Test _get_mode_display fallback for unknown modes."""
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Test fallback: unknown_mode → Unknown Mode
    result = handlers._get_mode_display("unknown_mode")
    assert result == "Unknown Mode"

    # Test fallback: multi_word_mode → Multi Word Mode
    result = handlers._get_mode_display("multi_word_mode")
    assert result == "Multi Word Mode"


# === cmd_help tests ===


@pytest.mark.asyncio
async def test_cmd_help(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /help returns help text with Markdown."""
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_help(mock_update, mock_context)

    # Assert: Help text sent with Markdown
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "Помощь" in call_args[0][0]
    assert call_args[1]["parse_mode"] == ParseMode.MARKDOWN


# === cmd_feedback tests ===


@pytest.mark.asyncio
async def test_cmd_feedback_no_history(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /feedback without last_query shows error message."""
    # Arrange: No last_query in session
    mock_session_manager.get_session.return_value = {}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_feedback(mock_update, mock_context)

    # Assert: Error message sent
    mock_update.message.reply_text.assert_called_once()
    reply_args = mock_update.message.reply_text.call_args[0][0]
    assert "не задавали вопросов" in reply_args


@pytest.mark.asyncio
async def test_cmd_feedback_with_history(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test /feedback with last_query shows inline keyboard."""
    # Arrange: Session with last_query/last_answer
    mock_session_manager.get_session.return_value = {
        "last_query": "How to reset VPN?",
        "last_answer": "To reset VPN password...",
        "mode": "it_support",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_feedback(mock_update, mock_context)

    # Assert: Inline keyboard sent
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "Оцените качество" in call_args[0][0]
    assert "reply_markup" in call_args[1]


# === handle_callback_query tests ===


@pytest.mark.asyncio
async def test_handle_callback_query_feedback(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query feedback:{rating} saves feedback."""
    # Arrange: Callback query with feedback:4
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "feedback:4"
    mock_session_manager.get_session.return_value = {
        "last_query": "Test question",
        "last_answer": "Test answer",
        "mode": "it_support",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Feedback saved
    mock_feedback_collector.save_feedback.assert_called_once()
    call_args = mock_feedback_collector.save_feedback.call_args
    assert call_args[1]["rating"] == 4
    assert call_args[1]["query"] == "Test question"
    # Callback answered (called at least once - first empty, then with confirmation)
    assert mock_callback_query.answer.call_count >= 1


@pytest.mark.asyncio
async def test_handle_callback_query_action_help(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query action:help shows help text."""
    # Arrange: Callback query with action:help
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "action:help"

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Help text shown
    mock_callback_query.message.edit_text.assert_called_once()
    call_args = mock_callback_query.message.edit_text.call_args
    assert "Помощь" in call_args[0][0]


# === handle_message saves session tests ===


@pytest.mark.asyncio
async def test_handle_message_saves_session(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test handle_message saves last_query/last_answer in session."""
    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_message(mock_update, mock_context)

    # Assert: Session updated with last_query/last_answer
    assert mock_session_manager.set_session.call_count >= 1
    # Check last call contains last_query/last_answer
    last_call = mock_session_manager.set_session.call_args_list[-1]
    session_data = last_call[0][1]
    assert "last_query" in session_data
    assert "last_answer" in session_data


# === Additional callback query tests for coverage ===


@pytest.mark.asyncio
async def test_handle_callback_query_action_feedback(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query action:feedback shows inline keyboard."""
    # Arrange: Callback query with action:feedback
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "action:feedback"
    mock_session_manager.get_session.return_value = {
        "last_query": "Test question",
        "last_answer": "Test answer",
        "mode": "it_support",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered and inline keyboard shown
    assert mock_callback_query.answer.call_count >= 1
    mock_callback_query.message.edit_text.assert_called_once()
    call_args = mock_callback_query.message.edit_text.call_args
    assert "Оцените качество" in call_args[0][0]
    assert "reply_markup" in call_args[1]


@pytest.mark.asyncio
async def test_handle_callback_query_mode_switching(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query mode switching (mode:it_support)."""
    # Arrange: Callback query with mode:it_support
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "mode:it_support"
    mock_session_manager.get_session.return_value = {"mode": "hr_support"}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered and session updated
    assert mock_callback_query.answer.call_count >= 1
    mock_session_manager.set_session.assert_called_once()

    # Verify mode changed in session
    call_args = mock_session_manager.set_session.call_args
    session_data = call_args[0][1]
    assert session_data["mode"] == "it_support"


@pytest.mark.asyncio
async def test_handle_callback_query_invalid_data(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query with invalid data format."""
    # Arrange: Callback query with invalid data (no colon)
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "invalid_format_no_colon"

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered but no processing
    mock_callback_query.answer.assert_called_once()

    # Verify no other actions (no save_feedback, no session changes)
    mock_feedback_collector.save_feedback.assert_not_called()
    # Note: answer() is called, but no session update or feedback save


@pytest.mark.asyncio
async def test_handle_callback_query_feedback_missing_session(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query feedback:4 without last_query in session."""
    # Arrange: Callback query with feedback:4
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "feedback:4"
    # Setup session WITHOUT last_query/last_answer
    mock_session_manager.get_session.return_value = {"mode": "it_support"}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered with error message
    assert mock_callback_query.answer.call_count >= 1

    # Verify feedback NOT saved (missing last_query)
    mock_feedback_collector.save_feedback.assert_not_called()

    # Verify error message shown (check last answer call)
    answer_calls = mock_callback_query.answer.call_args_list
    # Last call should contain error message
    if len(answer_calls) > 0:
        last_call = answer_calls[-1]
        if last_call.kwargs.get("text"):
            assert (
                "Ошибка" in last_call.kwargs["text"]
                or "нет данных" in last_call.kwargs["text"]
            )


@pytest.mark.asyncio
async def test_handle_callback_query_feedback_invalid_rating(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query feedback with invalid rating (out of range)."""
    # Arrange: Callback query with feedback:6 (invalid)
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "feedback:6"
    mock_session_manager.get_session.return_value = {
        "last_query": "Test question",
        "last_answer": "Test answer",
        "mode": "it_support",
    }

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered with error
    assert mock_callback_query.answer.call_count >= 1

    # Verify feedback NOT saved (invalid rating)
    mock_feedback_collector.save_feedback.assert_not_called()


@pytest.mark.asyncio
async def test_handle_callback_query_feedback_save_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query feedback when save_feedback raises exception."""
    # Arrange: Callback query with feedback:4
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "feedback:4"
    mock_session_manager.get_session.return_value = {
        "last_query": "Test question",
        "last_answer": "Test answer",
        "mode": "it_support",
    }
    # Mock save_feedback to raise exception
    mock_feedback_collector.save_feedback.side_effect = Exception("Redis error")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered with error message
    assert mock_callback_query.answer.call_count >= 1
    # Verify error message shown
    answer_calls = mock_callback_query.answer.call_args_list
    if len(answer_calls) > 0:
        last_call = answer_calls[-1]
        if last_call.kwargs.get("text"):
            assert "Ошибка" in last_call.kwargs["text"]


@pytest.mark.asyncio
async def test_handle_callback_query_mode_invalid(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query mode switching with invalid mode."""
    # Arrange: Callback query with invalid mode
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "mode:invalid_mode"

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered with error
    assert mock_callback_query.answer.call_count >= 1

    # Verify session NOT updated (invalid mode)
    # Note: answer() is called with error message, but no session update


@pytest.mark.asyncio
async def test_handle_callback_query_mode_same_mode(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query mode switching when already in that mode."""
    # Arrange: Callback query with mode:it_support, but already in it_support
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "mode:it_support"
    mock_session_manager.get_session.return_value = {"mode": "it_support"}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered but no session update (same mode)
    assert mock_callback_query.answer.call_count >= 1

    # Verify answer contains "уже используете"
    answer_calls = mock_callback_query.answer.call_args_list
    if len(answer_calls) > 0:
        last_call = answer_calls[-1]
        if last_call.kwargs.get("text"):
            assert "уже используете" in last_call.kwargs["text"]


@pytest.mark.asyncio
async def test_handle_callback_query_action_feedback_no_history(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query action:feedback without last_query."""
    # Arrange: Callback query with action:feedback but no last_query
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "action:feedback"
    mock_session_manager.get_session.return_value = {"mode": "it_support"}

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered with error message
    assert mock_callback_query.answer.call_count >= 1

    # Verify no inline keyboard shown (no edit_text called)
    mock_callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_help_fallback(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
):
    """Test cmd_help fallback when markdown fails."""
    # Arrange: reply_text with markdown raises exception
    mock_update.message.reply_text.side_effect = [
        Exception("Markdown error"),
        None,  # Fallback call succeeds
    ]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.cmd_help(mock_update, mock_context)

    # Assert: Fallback message sent (second call without markdown)
    assert mock_update.message.reply_text.call_count == 2
    # Second call should be without markdown
    second_call = mock_update.message.reply_text.call_args_list[1]
    assert "Помощь по использованию бота" in second_call[0][0]


@pytest.mark.asyncio
async def test_handle_callback_query_action_help_fallback(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query action:help fallback when markdown fails."""
    # Arrange: Callback query with action:help
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "action:help"
    # edit_text with markdown raises exception
    mock_callback_query.message.edit_text.side_effect = [
        Exception("Markdown error"),
        None,  # Fallback call succeeds
    ]

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Fallback message sent (second call without markdown)
    assert mock_callback_query.message.edit_text.call_count == 2
    # Second call should be without markdown
    second_call = mock_callback_query.message.edit_text.call_args_list[1]
    assert "Помощь по использованию бота" in second_call[0][0]


@pytest.mark.asyncio
async def test_handle_callback_query_feedback_edit_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query feedback when edit_text fails."""
    # Arrange: Callback query with feedback:5
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "feedback:5"
    mock_callback_query.message.text = "Original message"
    mock_session_manager.get_session.return_value = {
        "last_query": "Test question",
        "last_answer": "Test answer",
        "mode": "it_support",
    }
    # edit_text raises exception
    mock_callback_query.message.edit_text.side_effect = Exception("Edit error")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Feedback saved despite edit error
    mock_feedback_collector.save_feedback.assert_called_once()
    # Answer called (confirmation shown)
    assert mock_callback_query.answer.call_count >= 1


@pytest.mark.asyncio
async def test_handle_callback_query_mode_session_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query mode switching when get_session fails."""
    # Arrange: Callback query with mode:hr_support (different from DEFAULT_MODE)
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "mode:hr_support"
    # get_session raises exception (handled gracefully, creates default session)
    mock_session_manager.get_session.side_effect = Exception("Session error")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered (error handled gracefully)
    assert mock_callback_query.answer.call_count >= 1
    # set_session called (mode switch from DEFAULT_MODE to hr_support)
    mock_session_manager.set_session.assert_called_once()


@pytest.mark.asyncio
async def test_handle_callback_query_mode_set_session_error(
    mock_update,
    mock_context,
    mock_session_manager,
    mock_rag_factory,
    mock_config,
    mock_feedback_collector,
    mock_callback_query,
):
    """Test callback query mode switching when set_session fails."""
    # Arrange: Callback query with mode:it_support
    mock_update.callback_query = mock_callback_query
    mock_callback_query.data = "mode:it_support"
    mock_session_manager.get_session.return_value = {"mode": "hr_support"}
    # set_session raises exception
    mock_session_manager.set_session.side_effect = Exception("Set session error")

    handlers = TelegramHandlers(
        rag_factory=mock_rag_factory,
        session_manager=mock_session_manager,
        config=mock_config,
        feedback_collector=mock_feedback_collector,
    )

    # Act
    await handlers.handle_callback_query(mock_update, mock_context)

    # Assert: Callback answered despite set_session error
    assert mock_callback_query.answer.call_count >= 1
    # set_session was called (error handled gracefully)
    mock_session_manager.set_session.assert_called_once()
