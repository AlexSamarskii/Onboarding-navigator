"""
Telegram bot handlers for commands and messages.

Handles:
- /start, /mode, /reload_faq commands
- Text message processing through RAG
- Session management
- Error handling
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode, ChatAction

from telegram_rag_bot.langchain_adapter.rag_chains import RAGChainFactory
from telegram_rag_bot.utils.session_manager import SessionManager
from telegram_rag_bot.utils.feedback_collector import FeedbackCollector
from telegram_rag_bot.utils.metrics import QUERY_LATENCY, ERROR_COUNT
from telegram_rag_bot.config_loader import reload_config
from telegram_rag_bot.usage_tracking import check_quota_before_llm

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """
    Telegram bot handlers for commands and messages.

    Handles:
    - /start, /mode, /reload_faq, /help, /feedback commands
    - Text message processing through RAG
    - Callback query handling (inline buttons)
    - Session management
    - Error handling
    """

    # Constants
    MAX_MESSAGE_LENGTH = 4096

    def __init__(
        self,
        rag_factory: RAGChainFactory,
        session_manager: SessionManager,
        config: Dict[str, Any],
        feedback_collector: FeedbackCollector,
    ):
        """
        Initialize handlers.

        Args:
            rag_factory: RAGChainFactory instance for creating RAG chains
            session_manager: SessionManager instance for user sessions
            config: Full configuration dictionary from ConfigLoader
            feedback_collector: FeedbackCollector instance for storing user feedback
        """
        self.rag_factory = rag_factory
        self.session_manager = session_manager
        self.config = config
        self.feedback_collector = feedback_collector

        # Default mode: first key in config["modes"] (avoids KeyError on stale session)
        self.DEFAULT_MODE = list(config["modes"].keys())[0]

        # Mode display names: from config or fallback to title-cased key
        self.mode_display_names = {
            key: cfg.get("display_name", key.replace("_", " ").title())
            for key, cfg in config["modes"].items()
        }

    def _is_admin(self, user_id: int) -> bool:
        """
        Check if user is admin.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user is in admin_ids list
        """
        admin_ids = self.config["telegram"].get("admin_ids", [])
        return user_id in admin_ids

    def _escape_markdown_v2(self, text: str) -> str:
        """
        Escape special characters for Telegram MarkdownV2.

        Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !

        Args:
            text: Text to escape

        Returns:
            Escaped text
        """
        escape_chars = "_*[]()~`>#+-=|{}.!"
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")
        return text

    def _get_mode_display(self, mode: str) -> str:
        """
        Get human-readable mode name.

        Args:
            mode: Mode key (e.g., "it_support")

        Returns:
            Human-readable name (e.g., "IT Support")
        """
        display = self.mode_display_names.get(mode)
        if display is None:
            # Fallback: capitalize snake_case
            display = mode.replace("_", " ").title()
        return display

    async def cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /start command.

        Shows welcome message and available commands.
        Does NOT create session (created on first message).

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.message:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or "User"

        modes = self.config["modes"]

        # Если только один mode — автоматически выбрать
        if len(modes) == 1:
            mode_id = list(modes.keys())[0]

            # Обновить session
            try:
                session = await self.session_manager.get_session(user_id)
                if session is None:
                    session = {}
                session["mode"] = mode_id
                session["last_active"] = datetime.now().isoformat()
                await self.session_manager.set_session(user_id, session)
            except Exception as e:
                logger.warning(f"Failed to update session: {e}")

            # Отправить сообщение без кнопок
            mode_config = modes[mode_id]
            greeting = mode_config.get("greeting")
            _LEGACY_SUFFIX_SINGLE = "Задавайте вопросы, и я постараюсь найти ответ!"
            welcome_suffix = mode_config.get("welcome_suffix", _LEGACY_SUFFIX_SINGLE)

            if welcome_suffix:
                if greeting:
                    welcome_text = f"{greeting}\n\n{welcome_suffix}"
                else:
                    welcome_text = f"👋 Привет! Я FAQ бот компании.\n\n{welcome_suffix}"
            else:
                if greeting:
                    welcome_text = greeting
                else:
                    welcome_text = "👋 Привет! Я FAQ бот компании."
            await update.message.reply_text(welcome_text)
            logger.info(f"User {user_id} started bot (auto-selected mode: {mode_id})")
            return

        # Если несколько modes — показать кнопки
        # Critical: Get session with fallback to default if not found or error
        # This ensures bot works even if Redis/SessionManager fails
        try:
            session = await self.session_manager.get_session(user_id)
            if session is None:
                session = {}  # Empty session → will use DEFAULT_MODE
        except Exception as e:
            logger.warning(f"Session manager error in /start: {e}")
            session = {}  # Fallback to empty session (in-memory)

        current_mode = session.get("mode", self.DEFAULT_MODE)
        effective_mode = current_mode if current_mode in modes else self.DEFAULT_MODE
        mode_display = self._get_mode_display(effective_mode)

        # Check for custom greeting
        mode_config = modes.get(effective_mode, {})
        greeting = mode_config.get("greeting")
        _LEGACY_SUFFIX_MULTI = "Просто задайте мне вопрос, и я постараюсь найти ответ!"
        welcome_suffix = mode_config.get("welcome_suffix", _LEGACY_SUFFIX_MULTI)

        sections = []
        if greeting:
            sections.append(greeting)
        else:
            sections.extend(
                [
                    "👋 Привет! Я FAQ бот компании.",
                    "Я помогу ответить на ваши вопросы, используя базу знаний.",
                ]
            )
        if welcome_suffix:
            sections.append(welcome_suffix)
        sections.extend(
            [
                "Используйте команды ниже для навигации.",
                f"📌 Текущий режим: {mode_display}",
            ]
        )
        welcome_text = "\n\n".join(sections)

        # Create inline keyboard with mode buttons
        keyboard = []
        for mode_key, mode_config in modes.items():
            display_name = mode_config.get("display_name", mode_key)
            keyboard.append(
                [InlineKeyboardButton(display_name, callback_data=f"mode:{mode_key}")]
            )

        # Add feedback and help buttons
        keyboard.append(
            [InlineKeyboardButton("💬 Оставить отзыв", callback_data="action:feedback")]
        )
        keyboard.append(
            [InlineKeyboardButton("❓ Помощь", callback_data="action:help")]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message with inline keyboard
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)

        logger.info(f"User {user_id} ({username}) started bot")

    async def cmd_set_mode(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /mode command.

        Usage: /mode <mode_name>
        Without argument: shows current mode + available modes

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.message:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Critical: Get session once (used in both branches)
        # This optimizes session loading (not twice)
        try:
            session = await self.session_manager.get_session(user_id)
            if session is None:
                session = {"mode": self.DEFAULT_MODE}
        except Exception as e:
            logger.warning(f"Session error in /mode: {e}")
            session = {"mode": self.DEFAULT_MODE}

        current_mode = session.get("mode", self.DEFAULT_MODE)

        # No argument → show current + available modes
        if not context.args:
            current_mode_display = self._get_mode_display(current_mode)
            available_modes = ", ".join(self.config["modes"].keys())

            await update.message.reply_text(
                f"📌 Текущий режим: {current_mode_display}\n\n"
                f"📋 Доступные режимы: {available_modes}\n\n"
                f"Используйте: /mode <режим>"
            )
            return

        # With argument → switch mode
        new_mode = context.args[0].lower().strip()

        # Validate mode exists
        if new_mode not in self.config["modes"]:
            available_modes = ", ".join(self.config["modes"].keys())
            await update.message.reply_text(
                f"❌ Неизвестный режим: {new_mode}\n\n"
                f"Доступные режимы: {available_modes}"
            )
            return

        # Check if mode changed
        if new_mode == current_mode:
            # Already in this mode → no message
            return

        # Update session
        session["mode"] = new_mode
        session["last_active"] = datetime.now().isoformat()

        # Critical: Save session with error handling (consistency with other methods)
        try:
            await self.session_manager.set_session(user_id, session)
        except Exception as e:
            logger.warning(f"Failed to update session in /mode: {e}")
            # Continue anyway → user sees confirmation even if session save fails

        # Send confirmation
        mode_display = self._get_mode_display(new_mode)
        await update.message.reply_text(f"✅ Режим изменён на: {mode_display}")

        logger.info(f"User {user_id} switched to mode: {new_mode}")

    async def cmd_reload_faq(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /reload_faq command (admin only).

        Rebuilds FAISS index for specified mode.
        Usage: /reload_faq [mode_name]
        Without argument: rebuilds current mode

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.message:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Admin check
        if not self._is_admin(user_id):
            await update.message.reply_text(
                "❌ Нет доступа. Команда только для администраторов."
            )
            return

        # Determine mode to rebuild
        if context.args:
            mode = context.args[0].lower().strip()
        else:
            # No argument → use current mode from session
            try:
                session = await self.session_manager.get_session(user_id)
                if session is None:
                    session = {"mode": self.DEFAULT_MODE}
            except Exception as e:
                logger.warning(f"Session error in /reload_faq: {e}")
                session = {"mode": self.DEFAULT_MODE}

            mode = session.get("mode", self.DEFAULT_MODE)

        # Validate mode
        if mode not in self.config["modes"]:
            available_modes = ", ".join(self.config["modes"].keys())
            await update.message.reply_text(
                f"❌ Неизвестный режим: {mode}\n\n"
                f"Доступные режимы: {available_modes}"
            )
            return

        # Show progress message
        mode_display = self._get_mode_display(mode)
        await update.message.reply_text(
            f"🔨 Пересобираю индекс для режима {mode_display}..."
        )

        # Reload config (перезагружает modes из файлов)
        try:
            self.config = reload_config()  # ← ОБНОВЛЯЕМ self.config

            # ВАЖНО: обновить modes в rag_factory тоже!
            if hasattr(self, "rag_factory") and self.rag_factory:
                self.rag_factory.modes = self.config["modes"]

            logger.info("✅ Config reloaded (modes updated)")
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")
            await update.message.reply_text(f"❌ Ошибка перезагрузки конфига: {e}")
            return

        # Get FAQ file path (defensive .get() for reliability after config reload)
        faq_file = self.config["modes"].get(mode, {}).get("faq_file", "")

        # Rebuild index (async operation)
        try:
            await self.rag_factory.rebuild_index(mode, faq_file)
        except FileNotFoundError:
            await update.message.reply_text(
                f"❌ Ошибка: FAQ файл не найден\n{faq_file}"
            )
            logger.error(f"FAQ file not found: {faq_file}", exc_info=True)
            return
        except Exception as e:
            logger.error(f"Failed to rebuild index for {mode}: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Ошибка при пересборке индекса\n{str(e)}"
            )
            return

        # Send success message
        await update.message.reply_text(f"✅ Индекс обновлён для режима {mode_display}")

        logger.info(f"Admin {user_id} reloaded FAQ index for mode: {mode}")

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle text messages.

        Processes user questions through RAG chain and returns answers.
        Shows typing indicator during processing.

        Args:
            update: Telegram Update object
            context: Callback context

        Flow:
            1. Get user_id and session
            2. Show typing indicator
            3. Create/get RAG chain for mode
            4. Invoke chain with timeout
            5. Format answer (escape markdown)
            6. Send response (with fallback)
            7. Update session

        Error Handling:
            - Empty messages → ignored
            - Session errors → fallback to default
            - Chain errors → user-friendly messages
            - Timeout → "Запрос занял слишком много времени"
            - Send errors → fallback to raw text
        """
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.message.text:
            return  # Ignore non-text messages (stickers, photos, etc.)

        user_id = update.effective_user.id
        text = update.message.text.strip()

        # Ignore empty messages
        if not text:
            return

        # Critical: Засечь время для метрики latency
        start_time = time.time()

        # Critical: Get session with fallback to default if not found or error
        # This ensures bot works even if Redis/SessionManager fails
        try:
            session = await self.session_manager.get_session(user_id)
            if session is None:
                # First message from user → create new session
                session = {
                    "mode": self.DEFAULT_MODE,
                    "last_active": datetime.now().isoformat(),
                }
                # Critical: Save new session to SessionManager for persistence
                # Without this, session will be recreated on every request
                try:
                    await self.session_manager.set_session(user_id, session)
                    logger.info(f"Created new session for user {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to create session: {e}")
                    # Continue with in-memory session (fallback)
        except Exception as e:
            logger.warning(f"Session manager error: {e}")
            # Fallback to default session (in-memory)
            session = {
                "mode": self.DEFAULT_MODE,
                "last_active": datetime.now().isoformat(),
            }

        mode = session.get("mode", self.DEFAULT_MODE)

        # Validate mode
        if mode not in self.config["modes"]:
            logger.warning(f"Invalid mode {mode} for user {user_id}, using default")
            mode = self.DEFAULT_MODE
            session["mode"] = mode

        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        # Get timeout from config (defensive: fallback to DEFAULT_MODE if mode missing)
        mode_cfg = self.config["modes"].get(mode) or self.config["modes"].get(
            self.DEFAULT_MODE, {}
        )
        timeout = mode_cfg.get("timeout_seconds", 30)

        # 🔍 DEBUG: Log input query
        logger.info(
            f"🔍 RAG INPUT | User: {user_id} | Mode: {mode} | Query: {text[:100]}"
        )

        # Quota pre-check (Platform SaaS): skip if no platform config (BYOK)
        platform_cfg = self.config.get("platform", {})
        tenant_id = platform_cfg.get("tenant_id", "")
        callback_url = platform_cfg.get("callback_url")
        if callback_url and tenant_id:
            allowed, block_message = await check_quota_before_llm(
                tenant_id, callback_url
            )
            if not allowed:
                await update.message.reply_text(
                    block_message
                    or "Доступ ограничен. Перейдите на ubpl.ru для продолжения."
                )
                return

        # Create/get chain (with error handling)
        try:
            chain = self.rag_factory.create_chain(mode)
            # 🔍 DEBUG: Log chain creation success
            logger.info(f"✅ Chain created for mode: {mode}")
        except ValueError:
            # Mode not found
            available_modes = ", ".join(self.config["modes"].keys())
            await update.message.reply_text(
                f"❌ Неизвестный режим: {mode}\n\n"
                f"Доступные режимы: {available_modes}"
            )
            return
        except FileNotFoundError as e:
            # FAQ file not found (critical error)
            logger.error(f"FAQ file not found for mode {mode}: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Ошибка конфигурации. Обратитесь к администратору."
            )
            return
        except Exception as e:
            logger.error(f"Failed to create chain for mode {mode}: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Ошибка загрузки модели. Обратитесь к администратору."
            )
            return

        # Critical: Invoke chain with timeout (sync operation in async thread)
        # asyncio.to_thread() ensures non-blocking execution
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(chain.invoke, {"input": text}), timeout=timeout
            )

            # 🔍 DEBUG: Log full response structure
            logger.info(f"🤖 RAG RESPONSE TYPE: {type(response)}")
            logger.info(
                f"🤖 RAG RESPONSE KEYS: {list(response.keys()) if isinstance(response, dict) else 'NOT A DICT'}"
            )

            # 🔍 DEBUG: Log retrieved context documents
            if isinstance(response, dict):
                context_docs = response.get("context", [])
                logger.info(f"📄 RETRIEVED DOCS: {len(context_docs)} documents")

                # Log first doc snippet if documents found
                if context_docs:
                    first_doc = str(context_docs[0])
                    logger.info(f"📄 FIRST DOC (200 chars): {first_doc[:200]}")
                else:
                    logger.warning("⚠️ NO DOCUMENTS RETRIEVED!")
        except asyncio.TimeoutError:
            latency = time.time() - start_time
            ERROR_COUNT.labels(error_type="timeout").inc()
            await update.message.reply_text(
                "⏱️ Запрос занял слишком много времени. Попробуйте упростить вопрос."
            )
            logger.warning(
                f"Query timeout for user {user_id} (mode={mode})",
                extra={"user_id": user_id, "mode": mode, "latency": latency},
            )
            return
        except ValueError as e:
            latency = time.time() - start_time
            # Check if it's dimension mismatch error
            if "dimension" in str(e).lower():
                ERROR_COUNT.labels(error_type="dimension_mismatch").inc()
            else:
                ERROR_COUNT.labels(error_type="unknown").inc()
            logger.error(f"Error invoking chain: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
            return
        except Exception as e:
            latency = time.time() - start_time
            # Check if it's rate limit error
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                ERROR_COUNT.labels(error_type="rate_limit").inc()
            else:
                ERROR_COUNT.labels(error_type="unknown").inc()
            logger.error(f"Error invoking chain: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
            return

        # Extract answer
        # CHECK: Response can be None if chain fails
        if response is None:
            latency = time.time() - start_time
            logger.warning(
                f"RAG chain returned None for user {user_id}, mode: {mode}",
                extra={"user_id": user_id, "mode": mode, "latency": latency},
            )
            ERROR_COUNT.labels(error_type="chain_none_response").inc()
            await update.message.reply_text(
                "Извините, не удалось получить ответ из базы знаний. "
                "Попробуйте позже или обратитесь к администратору."
            )
            return

        # Extract answer with fallback handling
        if isinstance(response, dict):
            answer = response.get("answer", response.get("result", str(response)))
        else:
            answer = str(response)
            logger.warning(f"⚠️ Response not a dict! Type: {type(response)}")

        # 🔍 DEBUG: Log LLM answer details
        logger.info(f"🤖 LLM ANSWER LENGTH: {len(answer)} chars")
        logger.info(f"🤖 LLM ANSWER (first 300 chars): {answer[:300]}")
        if len(answer) > 100:
            logger.info(f"🤖 LLM ANSWER (last 100 chars): {answer[-100:]}")
        else:
            logger.info(f"🤖 LLM ANSWER (full): {answer}")

        # Critical: Escape markdown for Telegram MarkdownV2
        # LLM output may contain special chars: _ * [ ] ( ) ~ ` > # + - = | { } . !
        formatted_answer = self._escape_markdown_v2(answer)

        # Check length (safe truncation)
        if len(formatted_answer) > self.MAX_MESSAGE_LENGTH:
            truncated = formatted_answer[: self.MAX_MESSAGE_LENGTH - 100]
            formatted_answer = truncated + "\n\n\\.\\.\\.  \\(сообщение обрезано\\)"

        # 🔍 DEBUG: Log what we're sending to user
        logger.info(f"📤 SENDING TO USER (first 300 chars): {answer[:300]}")
        logger.info(f"📤 FORMATTED (first 300 chars): {formatted_answer[:300]}")

        # Critical: Fallback if markdown parsing fails
        # Send raw answer without markdown to ensure user gets response
        message_sent = False  # Track if message was successfully sent
        try:
            await update.message.reply_text(
                formatted_answer, parse_mode=ParseMode.MARKDOWN_V2
            )
            message_sent = True
            # 🔍 DEBUG: Log successful message send
            logger.info(f"✅ Message sent successfully to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send with markdown: {e}", exc_info=True)
            # Fallback: send raw answer without markdown
            try:
                await update.message.reply_text(answer)  # Raw text fallback
                message_sent = True  # Mark as sent if fallback succeeded
            except Exception as e2:
                logger.error(f"Failed to send fallback message: {e2}")
                # Both attempts failed → do not update session or log success

        # Update session only if message was sent
        if message_sent:
            # Save last_query and last_answer for feedback
            session["last_query"] = text
            session["last_answer"] = answer
            session["last_active"] = datetime.now().isoformat()
            try:
                await self.session_manager.set_session(user_id, session)
            except Exception as e:
                logger.warning(f"Failed to update session: {e}")

            # Log success only if message was sent
            latency = time.time() - start_time
            # Record query latency metric
            QUERY_LATENCY.labels(mode=mode).observe(latency)
            logger.info(
                f"User {user_id} (mode={mode}) query: '{text[:50]}...' | "
                f"Answer length: {len(answer)} chars",
                extra={"user_id": user_id, "mode": mode, "latency": latency},
            )
        else:
            # Message failed to send → log error
            latency = time.time() - start_time
            logger.error(
                f"Failed to send answer to user {user_id} (mode={mode}) | "
                f"Query: '{text[:50]}...'",
                extra={"user_id": user_id, "mode": mode, "latency": latency},
            )

    async def cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /help command.

        Shows user instructions and available commands.

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.message:
            return
        if not update.effective_user:
            return

        help_text = (
            "📚 **Помощь по использованию бота**\n\n"
            "Я помогаю отвечать на вопросы по IT поддержке.\n\n"
            "**Основные команды:**\n"
            "• `/start` — приветствие и настройки\n"
            "• `/help` — эта инструкция\n"
            "• `/feedback` — оценить качество ответа\n\n"
            "**Примеры вопросов:**\n"
            "• Как сбросить пароль VPN?\n"
            "• Как подключиться к корпоративной WiFi?\n"
            "• Где скачать Zoom?"
        )

        try:
            await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Failed to send help message: {e}", exc_info=True)
            # Fallback: send without markdown
            await update.message.reply_text(
                "📚 Помощь по использованию бота\n\n"
                "Я помогаю отвечать на вопросы по IT поддержке.\n\n"
                "Основные команды:\n"
                "• /start — приветствие и настройки\n"
                "• /help — эта инструкция\n"
                "• /feedback — оценить качество ответа\n\n"
                "Примеры вопросов:\n"
                "• Как сбросить пароль VPN?\n"
                "• Как подключиться к корпоративной WiFi?\n"
                "• Где скачать Zoom?"
            )

        logger.info(f"User {update.effective_user.id} requested help")

    async def cmd_feedback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /feedback command.

        Shows inline keyboard for rating the last bot response.

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.message:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Get session to check for last_query/last_answer
        try:
            session = await self.session_manager.get_session(user_id)
            if session is None:
                session = {}
        except Exception as e:
            logger.warning(f"Session error in /feedback: {e}")
            session = {}

        # Check if user has asked questions before
        last_query = session.get("last_query")
        last_answer = session.get("last_answer")

        if not last_query or not last_answer:
            await update.message.reply_text(
                "Вы ещё не задавали вопросов. Задайте вопрос боту, чтобы оставить отзыв."
            )
            return

        # Create inline keyboard with rating buttons
        keyboard = [
            [
                InlineKeyboardButton("⭐️", callback_data="feedback:1"),
                InlineKeyboardButton("⭐️⭐️", callback_data="feedback:2"),
                InlineKeyboardButton("⭐️⭐️⭐️", callback_data="feedback:3"),
                InlineKeyboardButton("⭐️⭐️⭐️⭐️", callback_data="feedback:4"),
                InlineKeyboardButton("⭐️⭐️⭐️⭐️⭐️", callback_data="feedback:5"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = "⭐️ Оцените качество последнего ответа:"

        try:
            await update.message.reply_text(text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send feedback request: {e}", exc_info=True)

        logger.info(f"User {user_id} requested feedback")

    async def handle_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle callback queries from inline buttons.

        Processes:
        - feedback:{rating} — save user rating
        - action:feedback — show feedback keyboard
        - action:help — show help text
        - mode:{mode_name} — switch mode

        Args:
            update: Telegram Update object
            context: Callback context
        """
        if not update.callback_query:
            return
        if not update.effective_user:
            return

        query = update.callback_query
        user_id = update.effective_user.id

        # Answer callback immediately (Telegram requirement)
        try:
            await query.answer()
        except Exception as e:
            logger.error(f"Failed to answer callback query: {e}", exc_info=True)
            return

        # Parse callback data
        if not query.data:
            logger.warning(f"Empty callback data from user {user_id}")
            return

        parts = query.data.split(":")
        if len(parts) < 2:
            logger.warning(f"Invalid callback data format: {query.data}")
            return

        action = parts[0]
        value = parts[1] if len(parts) > 1 else None

        # Handle feedback:{rating}
        if action == "feedback" and value:
            try:
                rating = int(value)
                if not (1 <= rating <= 5):
                    raise ValueError(f"Rating out of range: {rating}")

                # Get session for last_query/last_answer
                try:
                    session = await self.session_manager.get_session(user_id)
                    if session is None:
                        session = {}
                except Exception as e:
                    logger.warning(f"Session error in callback: {e}")
                    session = {}

                last_query = session.get("last_query")
                last_answer = session.get("last_answer")
                mode = session.get("mode", self.DEFAULT_MODE)

                if not last_query or not last_answer:
                    await query.answer(
                        text="Ошибка: нет данных для оценки", show_alert=False
                    )
                    return

                # Save feedback
                try:
                    await self.feedback_collector.save_feedback(
                        user_id=user_id,
                        query=last_query,
                        answer=last_answer,
                        rating=rating,
                        mode=mode,
                    )
                except ValueError as e:
                    logger.error(f"Invalid feedback data: {e}")
                    await query.answer(
                        text="Ошибка: некорректная оценка", show_alert=False
                    )
                    return
                except Exception as e:
                    logger.error(f"Failed to save feedback: {e}", exc_info=True)
                    await query.answer(
                        text="Ошибка при сохранении отзыва", show_alert=False
                    )
                    return

                # Show confirmation
                await query.answer(
                    text="✅ Спасибо за оценку! Ваш отзыв поможет улучшить бота.",
                    show_alert=False,
                )

                # Update message with confirmation
                rating_stars = "⭐️" * rating
                confirmation_text = (
                    f"\n\n✅ Оценка сохранена: {rating_stars} ({rating})"
                )

                if query.message and query.message.text:
                    try:
                        await query.message.edit_text(
                            query.message.text + confirmation_text
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update message: {e}")

                logger.info(f"User {user_id} rated response: {rating} stars")

            except ValueError as e:
                logger.error(f"Invalid rating value: {e}")
                await query.answer(text="Ошибка: некорректная оценка", show_alert=False)

        # Handle action:feedback
        elif action == "action" and value == "feedback":
            # Show feedback keyboard (same logic as cmd_feedback)
            try:
                session = await self.session_manager.get_session(user_id)
                if session is None:
                    session = {}
            except Exception as e:
                logger.warning(f"Session error in callback: {e}")
                session = {}

            last_query = session.get("last_query")
            last_answer = session.get("last_answer")

            if not last_query or not last_answer:
                await query.answer(text="Вы ещё не задавали вопросов", show_alert=False)
                return

            keyboard = [
                [
                    InlineKeyboardButton("⭐️", callback_data="feedback:1"),
                    InlineKeyboardButton("⭐️⭐️", callback_data="feedback:2"),
                    InlineKeyboardButton("⭐️⭐️⭐️", callback_data="feedback:3"),
                    InlineKeyboardButton("⭐️⭐️⭐️⭐️", callback_data="feedback:4"),
                    InlineKeyboardButton("⭐️⭐️⭐️⭐️⭐️", callback_data="feedback:5"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            text = "⭐️ Оцените качество последнего ответа:"

            try:
                if query.message:
                    await query.message.edit_text(text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Failed to show feedback keyboard: {e}", exc_info=True)

        # Handle action:help
        elif action == "action" and value == "help":
            help_text = (
                "📚 **Помощь по использованию бота**\n\n"
                "Я помогаю отвечать на вопросы по IT поддержке.\n\n"
                "**Основные команды:**\n"
                "• `/start` — приветствие и настройки\n"
                "• `/help` — эта инструкция\n"
                "• `/feedback` — оценить качество ответа\n\n"
                "**Примеры вопросов:**\n"
                "• Как сбросить пароль VPN?\n"
                "• Как подключиться к корпоративной WiFi?\n"
                "• Где скачать Zoom?"
            )

            try:
                if query.message:
                    await query.message.edit_text(
                        help_text, parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logger.error(f"Failed to show help: {e}", exc_info=True)
                # Fallback without markdown
                if query.message:
                    await query.message.edit_text(
                        "📚 Помощь по использованию бота\n\n"
                        "Я помогаю отвечать на вопросы по IT поддержке.\n\n"
                        "Основные команды:\n"
                        "• /start — приветствие и настройки\n"
                        "• /help — эта инструкция\n"
                        "• /feedback — оценить качество ответа\n\n"
                        "Примеры вопросов:\n"
                        "• Как сбросить пароль VPN?\n"
                        "• Как подключиться к корпоративной WiFi?\n"
                        "• Где скачать Zoom?"
                    )

        # Handle mode:{mode_name}
        elif action == "mode" and value:
            new_mode = value.lower().strip()

            # Validate mode
            if new_mode not in self.config["modes"]:
                available_modes = ", ".join(self.config["modes"].keys())
                await query.answer(
                    text=f"❌ Неизвестный режим: {new_mode}\n\n"
                    f"Доступные режимы: {available_modes}",
                    show_alert=True,
                )
                return

            # Get current session
            try:
                session = await self.session_manager.get_session(user_id)
                if session is None:
                    session = {"mode": self.DEFAULT_MODE}
            except Exception as e:
                logger.warning(f"Session error in callback: {e}")
                session = {"mode": self.DEFAULT_MODE}

            current_mode = session.get("mode", self.DEFAULT_MODE)

            # Check if mode changed
            if new_mode == current_mode:
                await query.answer(
                    text="Вы уже используете этот режим", show_alert=False
                )
                return

            # Update session
            session["mode"] = new_mode
            session["last_active"] = datetime.now().isoformat()

            try:
                await self.session_manager.set_session(user_id, session)
            except Exception as e:
                logger.warning(f"Failed to update session in callback: {e}")

            # Show confirmation
            mode_display = self._get_mode_display(new_mode)
            await query.answer(
                text=f"✅ Режим изменён на: {mode_display}", show_alert=False
            )

            logger.info(f"User {user_id} switched to mode: {new_mode} via callback")
