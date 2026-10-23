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
from contextlib import nullcontext
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
import re
from datetime import datetime, timezone
from langchain_core.callbacks import BaseCallbackHandler
from telegram_rag_bot.i18n import t
from telegram_rag_bot.handlers_legacy import legacy_handle_message, legacy_ui
from telegram_rag_bot.citations import extract_citation
from telegram_rag_bot.hr_adapter import LowScoreFallback
from telegram_rag_bot.utils.metrics import FALLBACK_TOTAL, RAG_SCORE
from integrations.ticketing import Ticket
from analytics.writer import UnansweredEntry
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
        *, coordinator=None, ticket_client=None, unanswered_writer=None,
        diagnostics_graph=None, health_cache=None, runtime_state=None,
        modes_directory=None, request_scope=None, generation_scope=None, started_at=None,
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
        self.coordinator = coordinator
        self.ticket_client = ticket_client
        self.unanswered_writer = unanswered_writer
        self.diagnostics_graph = diagnostics_graph
        self.health_cache = health_cache if health_cache is not None else {}
        self.runtime_state = runtime_state if runtime_state is not None else {
            "started_at": started_at if started_at is not None else time.monotonic(),
            "last_reindex": "never",
        }
        self.modes_directory = Path(modes_directory).resolve() if modes_directory else None
        self.request_scope = request_scope or generation_scope or nullcontext
        self._ticket_locks = {}

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
        admin_ids = self.config.get("ADMIN_IDS", self.config.get("telegram", {}).get("admin_ids", []))
        return isinstance(admin_ids, list) and user_id in admin_ids

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
        return self._ui(display)

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
            _LEGACY_SUFFIX_SINGLE = self._translate('legacy.welcome_single')
            welcome_suffix = mode_config.get("welcome_suffix", _LEGACY_SUFFIX_SINGLE)

            if welcome_suffix:
                if greeting:
                    welcome_text = f"{greeting}\n\n{welcome_suffix}"
                else:
                    welcome_text = self._translate('legacy.welcome_suffix', welcome_suffix=welcome_suffix)
            else:
                if greeting:
                    welcome_text = greeting
                else:
                    welcome_text = self._translate('legacy.welcome')
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
        _LEGACY_SUFFIX_MULTI = self._translate('legacy.welcome_multi')
        welcome_suffix = mode_config.get("welcome_suffix", _LEGACY_SUFFIX_MULTI)

        sections = []
        if greeting:
            sections.append(greeting)
        else:
            sections.extend(
                [
                    self._translate('legacy.welcome'),
                    self._translate('legacy.welcome_description'),
                ]
            )
        if welcome_suffix:
            sections.append(welcome_suffix)
        sections.extend(
            [
                self._translate('legacy.navigation_hint'),
                '📌 ' + self._translate('mode.current', mode=mode_display),
            ]
        )
        welcome_text = "\n\n".join(sections)

        # Create inline keyboard with mode buttons
        keyboard = []
        for mode_key, mode_config in modes.items():
            display_name = self._get_mode_display(mode_key)
            keyboard.append(
                [InlineKeyboardButton(display_name, callback_data=f"mode:{mode_key}")]
            )

        # Add feedback and help buttons
        keyboard.append(
            [InlineKeyboardButton('💬 ' + self._translate('navigation.feedback'), callback_data="action:feedback")]
        )
        keyboard.append(
            [InlineKeyboardButton('❓ ' + self._translate('navigation.help'), callback_data="action:help")]
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
                self._translate('legacy.mode_summary', mode=current_mode_display, modes=available_modes)
            )
            return

        # With argument → switch mode
        new_mode = context.args[0].lower().strip()

        # Validate mode exists
        if new_mode not in self.config["modes"]:
            available_modes = ", ".join(self.config["modes"].keys())
            await update.message.reply_text(
                self._translate('legacy.mode_unknown', mode=new_mode, modes=available_modes)
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
        await update.message.reply_text('✅ ' + self._translate('mode.changed', mode=mode_display))

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
        if self.coordinator is not None:
            return await self.cmd_reindex(update, context)
        if not update.message:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Admin check
        if not self._is_admin(user_id):
            await update.message.reply_text(
                self._translate('legacy.admin_denied')
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
                self._translate('legacy.mode_unknown', mode=mode, modes=available_modes)
            )
            return

        # Show progress message
        mode_display = self._get_mode_display(mode)
        await update.message.reply_text(
            self._translate('legacy.reindex_started', mode=mode_display)
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
            await update.message.reply_text(self._translate('legacy.reload_failed', error=e))
            return

        # Get FAQ file path (defensive .get() for reliability after config reload)
        faq_file = self.config["modes"].get(mode, {}).get("faq_file", "")

        # Rebuild index (async operation)
        try:
            await self.rag_factory.rebuild_index(mode, faq_file)
        except FileNotFoundError:
            await update.message.reply_text(
                self._translate('legacy.faq_missing', path=faq_file)
            )
            logger.error(f"FAQ file not found: {faq_file}", exc_info=True)
            return
        except Exception as e:
            logger.error(f"Failed to rebuild index for {mode}: {e}", exc_info=True)
            await update.message.reply_text(
                self._translate('legacy.reindex_failed', error=str(e))
            )
            return

        # Send success message
        await update.message.reply_text(self._translate('legacy.reindex_completed', mode=mode_display))

        logger.info(f"Admin {user_id} reloaded FAQ index for mode: {mode}")

    async def _legacy_handle_message(self, update, context):
        return await legacy_handle_message(self, update, context)

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
            self._translate('legacy.help_markdown')
        )

        try:
            await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Failed to send help message: {e}", exc_info=True)
            # Fallback: send without markdown
            await update.message.reply_text(
                self._translate('legacy.help_plain')
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
                self._translate('feedback.no_answer')
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

        text = '⭐️ ' + self._translate('feedback.prompt')

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

        if query.data.startswith("diag:") or query.data == "ticket:explicit":
            await self._hr_callback(update, context)
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
                        text=self._translate('legacy.feedback_no_data'), show_alert=False
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
                        text=self._translate('legacy.feedback_invalid_rating'), show_alert=False
                    )
                    return
                except Exception as e:
                    logger.error(f"Failed to save feedback: {e}", exc_info=True)
                    await query.answer(
                        text=self._translate('legacy.feedback_failed'), show_alert=False
                    )
                    return

                # Show confirmation
                await query.answer(
                    text='✅ ' + self._translate('feedback.thanks'),
                    show_alert=False,
                )

                # Update message with confirmation
                rating_stars = "⭐️" * rating
                confirmation_text = (
                    self._translate('legacy.feedback_saved', stars=rating_stars, rating=rating)
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
                await query.answer(text=self._translate('legacy.feedback_invalid_rating'), show_alert=False)

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
                await query.answer(text=self._translate('legacy.feedback_no_questions'), show_alert=False)
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

            text = '⭐️ ' + self._translate('feedback.prompt')

            try:
                if query.message:
                    await query.message.edit_text(text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Failed to show feedback keyboard: {e}", exc_info=True)

        # Handle action:help
        elif action == "action" and value == "help":
            help_text = (
                self._translate('legacy.help_markdown')
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
                        self._translate('legacy.help_plain')
                    )

        # Handle mode:{mode_name}
        elif action == "mode" and value:
            new_mode = value.lower().strip()

            # Validate mode
            if new_mode not in self.config["modes"]:
                available_modes = ", ".join(self.config["modes"].keys())
                await query.answer(
                    text=self._translate('legacy.mode_unknown', mode=new_mode, modes=available_modes),
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
                    text=self._translate('mode.unchanged').removesuffix('.'), show_alert=False
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
                text='✅ ' + self._translate('mode.changed', mode=mode_display), show_alert=False
            )

            logger.info(f"User {user_id} switched to mode: {new_mode} via callback")


    def _translate(self, key, **kwargs):
        """Translate command UI; fallback is limited to legacy construction."""
        if self.coordinator is None and self.modes_directory is None:
            return legacy_ui(key, **kwargs)
        return t(key, **kwargs)

    @staticmethod
    def _ui(key, **kwargs):
        try:
            return t(key, **kwargs)
        except (KeyError, RuntimeError, ValueError):
            return key

    async def _send(self, message, text, **kwargs):
        # Chunk the raw text before escaping: a full verbatim citation is never
        # silently truncated and no Markdown escape pair is split across messages.
        for offset in range(0, len(text) or 1, 900):
            part = text[offset:offset + 900]
            try:
                await message.reply_text(self._escape_markdown_v2(part),
                                         parse_mode=ParseMode.MARKDOWN_V2, **kwargs)
            except Exception:
                await message.reply_text(part, **kwargs)

    @staticmethod
    def collect_sources(root, modes):
        root = Path(root).resolve()
        result = {}
        for mode in modes:
            bundle = root / mode
            if bundle.is_dir():
                for path in bundle.rglob("*.md"):
                    if path.is_file():
                        result[path] = mode
        return result

    async def cmd_reindex(self, update, context):
        message = update.effective_message
        if not self._is_admin(update.effective_user.id):
            await self._send(message, t("admin.denied"))
            return
        try:
            counts = await self.coordinator.ingest(
                self.collect_sources(self.modes_directory, self.config["modes"]))
            self.runtime_state["last_reindex"] = datetime.now(timezone.utc).isoformat()
            await self._send(message, t("reindex.completed", documents=sum(counts.values())))
        except Exception:
            logger.error("reindex failed")
            await self._send(message, t("reindex.failed"))

    async def cmd_status(self, update, context):
        message = update.effective_message
        if not self._is_admin(update.effective_user.id):
            await self._send(message, t("admin.denied"))
            return
        try:
            session = await self.session_manager.get_session(update.effective_user.id)
            mode = session.get("mode", self.DEFAULT_MODE)
            try:
                package_version = version("telegram-rag-bot")
            except PackageNotFoundError:
                package_version = "unknown"
            try:
                documents = int(self.rag_factory.vectorstore_provider.load_index(mode).index.ntotal)
            except FileNotFoundError:
                documents = 0
            await self._send(message, t("status.summary", mode=mode, version=package_version,
                gigachat=self.health_cache.get("gigachat", "fail"),
                yandexgpt=self.health_cache.get("yandexgpt", "fail"), documents=documents,
                uptime_seconds=max(0, int(time.monotonic() - self.runtime_state["started_at"])),
                last_reindex=self.runtime_state.get("last_reindex", "never")))
        except Exception:
            logger.error("status unavailable")
            await self._send(message, t("status.unavailable"))

    async def _escalate(self, update, reason="explicit", query=None, top_score=None):
        user_id = update.effective_user.id
        message = update.effective_message
        # Process-local serialization; the client provides no cross-pod guarantee.
        async with self._ticket_locks.setdefault(user_id, asyncio.Lock()):
            session = await self.session_manager.get_session(user_id)
            operation = {"mode": session.get("mode", self.DEFAULT_MODE),
                         "query": query if query is not None else session.get("last_query", "")}
            if session.get("active_ticket_uuid") and session.get("ticket_operation") == operation:
                await self._send(message, t("ticket.created", ticket_id=session["active_ticket_uuid"]))
                return
            if session.get("active_ticket_uuid"):
                session["active_ticket_uuid"] = None
                session.pop("ticket_operation", None)
                await self.session_manager.set_session(user_id, session)
            if self.ticket_client is None:
                await self._send(message, t("ticket.failed"))
                return
            ticket = Ticket(user_id=user_id, mode=session.get("mode", self.DEFAULT_MODE),
                query=query if query is not None else session.get("last_query", ""),
                reason=reason, top_score=top_score)
            try:
                result = await self.ticket_client.create(ticket, session=session)
            except Exception:
                logger.error("ticket creation failed")
                await self._send(message, t("ticket.failed"))
                return
            if result.success:
                # The stable session API clears active UUID on successful creation.
                # Persist the confirmed UUID afterwards to deduplicate later clicks.
                await self.session_manager.record_ticket_created(user_id)
                latest = await self.session_manager.get_session(user_id)
                latest["active_ticket_uuid"] = result.ticket_id
                latest["ticket_operation"] = operation
                await self.session_manager.set_session(user_id, latest)
                await self._send(message, t("ticket.created", ticket_id=result.ticket_id))
            else:
                await self._send(message, t("ticket.failed"))

    def _escalation_keyboard(self):
        return InlineKeyboardMarkup([[InlineKeyboardButton(t("ticket.escalation"),
                                                           callback_data="ticket:explicit")]])

    async def _analytics(self, mode, reason, query, score=None):
        if self.unanswered_writer is not None:
            try:
                await asyncio.to_thread(self.unanswered_writer.write,
                    UnansweredEntry(mode, reason, query, score))
            except Exception:
                logger.error("unanswered analytics write failed")

    async def _low_score(self, update, query, mode, failure, *, observed=False):
        if not observed:
            RAG_SCORE.observe(failure.top_score or 0.0)
        FALLBACK_TOTAL.labels(type="rag").inc()
        session = await self.session_manager.record_rag_fallback(update.effective_user.id)
        session["last_query"] = query
        await self.session_manager.set_session(update.effective_user.id, session)
        await self._analytics(mode, "low_score", query, failure.top_score)
        text = t("fallback.no_answer")
        # Presentation-only suggestions: never use candidates as answer context.
        # Stable ordering and deduplication keep the optional top-three UI honest.
        suggestions_by_text = {}
        for item in failure.candidates:
            text_value = getattr(item, "page_content", str(item))
            raw_score = getattr(item, "metadata", {}).get("score", 0.0)
            value = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
            if value != value or value in (float("inf"), float("-inf")):
                value = 0.0
            suggestions_by_text[text_value] = max(value, suggestions_by_text.get(text_value, value))
        suggestions = sorted(suggestions_by_text, key=lambda value: (-suggestions_by_text[value], value))[:3]
        if suggestions:
            text += "\n" + t("fallback.suggestions_header") + "\n" + "\n".join(suggestions)
        text += "\n" + t("fallback.escalation_offer")
        await self._send(update.effective_message, text, reply_markup=self._escalation_keyboard())
        if session.get("rag_fallback_streak", 0) >= 2:
            await self._escalate(update, "fallback_x2", query, failure.top_score)

    async def handle_message(self, update, context):
        if self.coordinator is None and self.modes_directory is None:
            return await self._legacy_handle_message(update, context)
        if not update.effective_user or not update.message or not update.message.text:
            return
        query = update.message.text.strip()
        if not query:
            return
        user_id = update.effective_user.id
        session = await self.session_manager.get_session(user_id)
        mode = session.get("mode", self.DEFAULT_MODE)
        if mode not in self.config["modes"]:
            mode = self.DEFAULT_MODE
        if query == t("ticket.escalation"):
            return await self._escalate(update, query=query)
        if mode == "onboarding_plan":
            session["last_query"] = query
            await self.session_manager.set_session(user_id, session)
            return await self._onboarding(update, query, session)
        if session.get("last_query") != query:
            session["active_ticket_uuid"] = None
        session["mode"] = mode
        session["last_query"] = query
        await self.session_manager.set_session(user_id, session)
        class RetrievalScore(BaseCallbackHandler):
            observed = False
            def on_retriever_end(self, documents, **kwargs):
                if not self.observed:
                    RAG_SCORE.observe(max((d.metadata.get("score", 0.0) for d in documents), default=0.0))
                    self.observed = True
            def on_retriever_error(self, error, **kwargs):
                if isinstance(error, LowScoreFallback) and not self.observed:
                    RAG_SCORE.observe(error.top_score or 0.0)
                    self.observed = True
        score = RetrievalScore()
        start = time.monotonic()
        try:
            platform = self.config.get("platform", {})
            if platform.get("tenant_id") and platform.get("callback_url"):
                allowed, block_message = await check_quota_before_llm(
                    platform["tenant_id"], platform["callback_url"])
                if not allowed:
                    await self._send(update.message, block_message or t("errors.access_limited"))
                    return
            chain = self.rag_factory.create_chain(mode)
            with self.request_scope():
                response = await asyncio.wait_for(asyncio.to_thread(chain.invoke,
                    {"input": query}, config={"callbacks": [score]}),
                    timeout=self.config["modes"][mode].get("timeout_seconds", 30))
            docs = response.get("context", [])
            if not score.observed:
                score.on_retriever_end(docs)
            answer = str(response["answer"])
            titles = {}
            bundle = self.modes_directory / mode
            for path, title in self.config["modes"][mode].get("source_titles", {}).items():
                titles[str((bundle / path).resolve())] = self._ui(title)
                titles[path] = self._ui(title)
            citation = extract_citation(docs, titles)
            if citation:
                answer += "\n\n" + t("citation.reference", source=citation.source_display, quote=citation.quote)
            else:
                answer += "\n\n" + t("citation.unavailable")
            await self.session_manager.record_rag_success(user_id)
            latest = await self.session_manager.get_session(user_id)
            latest.update(mode=mode, last_query=query, last_answer=answer)
            await self.session_manager.set_session(user_id, latest)
            await self._send(update.message, answer, reply_markup=self._escalation_keyboard())
        except LowScoreFallback as failure:
            await self._low_score(update, query, mode, failure, observed=score.observed)
        except asyncio.TimeoutError:
            ERROR_COUNT.labels(error_type="timeout").inc()
            await self._send(update.message, t("errors.timeout"))
        except Exception:
            ERROR_COUNT.labels(error_type="unknown").inc()
            logger.error("HR answer failed")
            await self._send(update.message, t("errors.general"))
        finally:
            QUERY_LATENCY.labels(mode=mode).observe(time.monotonic() - start)

    async def _onboarding(self, update, query, session):
        user_id = update.effective_user.id
        profile = session.get("profile")
        if not profile:
            role = session.get("profile_pending_role")
            if role is None:
                if not session.get("profile_pending"):
                    session["profile_pending"] = True
                    await self.session_manager.set_session(user_id, session)
                    await self._send(update.message, t("profile.ask_role"))
                    return
                if not re.fullmatch(r"[a-z0-9_-]+", query):
                    await self._send(update.message, t("profile.invalid"))
                    return
                session["profile_pending_role"] = query
                await self.session_manager.set_session(user_id, session)
                await self._send(update.message, t("profile.ask_department"))
                return
            if not re.fullmatch(r"[a-z0-9_-]+", query):
                await self._send(update.message, t("profile.invalid"))
                return
            session = await self.session_manager.set_profile(user_id, role, query)
            session.pop("profile_pending", None)
            session.pop("profile_pending_role", None)
            await self.session_manager.set_session(user_id, session)
            profile = session["profile"]
        role, department = profile["role"], profile["department"]
        if not all(isinstance(x, str) and re.fullmatch(r"[a-z0-9_-]+", x) for x in (role, department)):
            await self._send(update.message, t("profile.invalid"))
            return
        bundle = (self.modes_directory / "onboarding_plan").resolve()
        directory = (bundle / self.config["modes"]["onboarding_plan"].get("plans_directory", "plans")).resolve()
        if not directory.is_relative_to(bundle):
            await self._send(update.message, t("errors.configuration"))
            return
        def read(name):
            path = (directory / name).resolve()
            if path.is_relative_to(directory) and path.is_relative_to(bundle) and path.is_file():
                return path.read_text(encoding="utf-8")
            return None
        plan = read(f"{role}__{department}.md") or read(f"{role}.md")
        if plan:
            await self._send(update.message, t("plan.title", role=role, department=department) + "\n" + plan)
            return
        session = await self.session_manager.get_session(user_id)
        session["mode"] = "onboarding_plan"
        session["last_query"] = f"onboarding_plan:{role}/{department}"
        await self.session_manager.set_session(user_id, session)
        await self._analytics("onboarding_plan", "missing_plan", f"{role}/{department}")
        text = t("plan.not_configured")
        default = read("default.md")
        if default:
            text += "\n" + t("plan.default") + "\n" + default
        text += "\n" + t("plan.escalation_offer")
        await self._send(update.message, text, reply_markup=self._escalation_keyboard())

    async def _hr_callback(self, update, context):
        data = update.callback_query.data
        if data in {"diag:escalate", "ticket:explicit"}:
            return await self._escalate(update)
        graph = self.diagnostics_graph
        if graph is None:
            await self._send(update.effective_message, t("diagnostics.unavailable"))
            return
        user_id = update.effective_user.id
        session = await self.session_manager.get_session(user_id)
        try:
            if data.startswith("diag:start:"):
                scenario = data.split(":", 2)[2]
                node = graph.scenarios[scenario]["start"]
                state = dict(scenario=scenario, node=node,
                             started_at=datetime.now(timezone.utc).isoformat())
            else:
                state = dict(session["diagnostics_state"])
                scenario = state["scenario"]
                node = graph.step(scenario, state["node"], int(data.split(":")[2]))
                state["node"] = node if isinstance(node, str) else state["node"]
            current = graph.scenarios[scenario]["nodes"][node] if isinstance(node, str) else node
            buttons = []
            if current["type"] == "terminal":
                ref = current["faq_ref"]
                filename, anchor = ref.split("#", 1)
                if filename != "faq.md" or not re.fullmatch(r"[a-z0-9_-]+", anchor):
                    raise ValueError("invalid FAQ reference")
                root = (self.modes_directory / "it_support").resolve()
                path = (root / filename).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("unsafe FAQ path")
                faq = path.read_text(encoding="utf-8")
                match = re.search(r'<a\s+(?:id|name)=["\']' + re.escape(anchor) + r'["\'][^>]*>.*?</a>(.*?)(?=<a\s+(?:id|name)=|\Z)', faq, re.S)
                if not match:
                    raise ValueError("missing FAQ anchor")
                text = self._ui(current["label_key"]) + "\n" + match.group(1).strip()
                session["diagnostics_state"] = None
            else:
                text = self._ui(current["question_key"])
                for index, choice in enumerate(current["choices"]):
                    buttons.append([InlineKeyboardButton(self._ui(choice["label_key"]), callback_data=f"diag:choice:{index}")])
                session["diagnostics_state"] = state
            buttons.append([InlineKeyboardButton(self._ui(current["escalation"]["label_key"]), callback_data="diag:escalate")])
            session["mode"] = "it_support"
            session["last_query"] = "diagnostics:" + scenario
            await self.session_manager.set_session(user_id, session)
            await self._send(update.effective_message, text, reply_markup=InlineKeyboardMarkup(buttons))
        except (KeyError, ValueError, TypeError, OSError):
            await self._send(update.effective_message, t("diagnostics.invalid_choice"))


    async def cmd_escalate(self, update, context):
        await self._escalate(update)

    async def cmd_diagnostics(self, update, context):
        session = await self.session_manager.get_session(update.effective_user.id)
        session["mode"] = "it_support"
        session["last_query"] = "diagnostics"
        await self.session_manager.set_session(update.effective_user.id, session)
        keyboard = [[InlineKeyboardButton(t("diagnostics.vpn.title"), callback_data="diag:start:vpn")],
                    [InlineKeyboardButton(t("diagnostics.mail.title"), callback_data="diag:start:mail")],
                    [InlineKeyboardButton(t("ticket.escalation"), callback_data="diag:escalate")]]
        await self._send(update.effective_message, t("diagnostics.choose"),
                         reply_markup=InlineKeyboardMarkup(keyboard))
