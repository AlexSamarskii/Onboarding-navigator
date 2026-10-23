"""Legacy backward-compat path. Unreachable in HR runtime where
coordinator and modes_directory are always set. Retained for
compatibility with pre-coordinator TelegramHandlers construction.
Excluded from AC-C07 Cyrillic scan and coverage.
"""
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction, ParseMode
from telegram_rag_bot.utils.metrics import QUERY_LATENCY, ERROR_COUNT
from telegram_rag_bot.usage_tracking import check_quota_before_llm

logger = logging.getLogger(__name__)


async def legacy_handle_message(
    self, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    '\n        Handle text messages.\n\n        Processes user questions through RAG chain and returns answers.\n        Shows typing indicator during processing.\n\n        Args:\n            update: Telegram Update object\n            context: Callback context\n\n        Flow:\n            1. Get user_id and session\n            2. Show typing indicator\n            3. Create/get RAG chain for mode\n            4. Invoke chain with timeout\n            5. Format answer (escape markdown)\n            6. Send response (with fallback)\n            7. Update session\n\n        Error Handling:\n            - Empty messages → ignored\n            - Session errors → fallback to default\n            - Chain errors → user-friendly messages\n            - Timeout → "Запрос занял слишком много времени"\n            - Send errors → fallback to raw text\n        '
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



# Exact pre-locale command texts for pre-coordinator consumers only.
_LEGACY_UI = {'feedback.no_answer': 'Вы ещё не задавали вопросов. Задайте вопрос боту, чтобы оставить отзыв.', 'legacy.admin_denied': '❌ Нет доступа. Команда только для администраторов.', 'legacy.faq_missing': '❌ Ошибка: FAQ файл не найден\n{path}', 'legacy.feedback_failed': 'Ошибка при сохранении отзыва', 'legacy.feedback_invalid_rating': 'Ошибка: некорректная оценка', 'legacy.feedback_no_data': 'Ошибка: нет данных для оценки', 'legacy.feedback_no_questions': 'Вы ещё не задавали вопросов', 'legacy.feedback_saved': '\n\n✅ Оценка сохранена: {stars} ({rating})', 'legacy.help_markdown': '📚 **Помощь по использованию бота**\n\nЯ помогаю отвечать на вопросы по IT поддержке.\n\n**Основные команды:**\n• `/start` — приветствие и настройки\n• `/help` — эта инструкция\n• `/feedback` — оценить качество ответа\n\n**Примеры вопросов:**\n• Как сбросить пароль VPN?\n• Как подключиться к корпоративной WiFi?\n• Где скачать Zoom?', 'legacy.help_plain': '📚 Помощь по использованию бота\n\nЯ помогаю отвечать на вопросы по IT поддержке.\n\nОсновные команды:\n• /start — приветствие и настройки\n• /help — эта инструкция\n• /feedback — оценить качество ответа\n\nПримеры вопросов:\n• Как сбросить пароль VPN?\n• Как подключиться к корпоративной WiFi?\n• Где скачать Zoom?', 'legacy.mode_summary': '📌 Текущий режим: {mode}\n\n📋 Доступные режимы: {modes}\n\nИспользуйте: /mode <режим>', 'legacy.mode_unknown': '❌ Неизвестный режим: {mode}\n\nДоступные режимы: {modes}', 'legacy.navigation_hint': 'Используйте команды ниже для навигации.', 'legacy.reindex_completed': '✅ Индекс обновлён для режима {mode}', 'legacy.reindex_failed': '❌ Ошибка при пересборке индекса\n{error}', 'legacy.reindex_started': '🔨 Пересобираю индекс для режима {mode}...', 'legacy.reload_failed': '❌ Ошибка перезагрузки конфига: {error}', 'legacy.welcome': '👋 Привет! Я FAQ бот компании.', 'legacy.welcome_description': 'Я помогу ответить на ваши вопросы, используя базу знаний.', 'legacy.welcome_multi': 'Просто задайте мне вопрос, и я постараюсь найти ответ!', 'legacy.welcome_single': 'Задавайте вопросы, и я постараюсь найти ответ!', 'legacy.welcome_suffix': '👋 Привет! Я FAQ бот компании.\n\n{welcome_suffix}', 'feedback.prompt': 'Оцените качество последнего ответа:', 'feedback.thanks': 'Спасибо за оценку! Ваш отзыв поможет улучшить бота.', 'mode.current': 'Текущий режим: {mode}', 'mode.changed': 'Режим изменён на: {mode}', 'navigation.feedback': 'Оставить отзыв', 'navigation.help': 'Помощь', 'mode.unchanged': 'Вы уже используете этот режим.'}

def legacy_ui(key, **kwargs):
    """Use a loaded locale when available; preserve standalone legacy commands."""
    from telegram_rag_bot.i18n import t
    try:
        return t(key, **kwargs)
    except (RuntimeError, KeyError):
        return _LEGACY_UI[key].format(**kwargs)
