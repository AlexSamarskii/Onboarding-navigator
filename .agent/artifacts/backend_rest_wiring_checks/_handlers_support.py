from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from telegram_rag_bot.handlers import TelegramHandlers
from telegram_rag_bot.i18n import load_locale
from telegram_rag_bot.utils.session_manager import SessionManager

ROOT=Path(__file__).resolve().parents[3]
def setup(mode="it_support", *, user_id=11):
    load_locale(ROOT/"config/i18n/ru.yaml")
    msg=SimpleNamespace(text="query", reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
    update=SimpleNamespace(message=msg,effective_message=msg,effective_user=SimpleNamespace(id=user_id),callback_query=None)
    factory=SimpleNamespace(create_chain=Mock(),vectorstore_provider=SimpleNamespace(load_index=Mock(return_value=SimpleNamespace(index=SimpleNamespace(ntotal=7)))))
    config={"modes":{mode:{"display_name":"mode."+mode,"timeout_seconds":1,"source_titles":{"faq.md":"mode."+mode}}},"ADMIN_IDS":[11]}
    handler=TelegramHandlers(factory,SessionManager(),config,Mock(),modes_directory=ROOT/"config/modes",coordinator=SimpleNamespace(ingest=AsyncMock(return_value={mode:3})))
    return handler,update
async def set_mode(h,mode):
    session=await h.session_manager.get_session(11);session["mode"]=mode
    await h.session_manager.set_session(11,session)
def texts(update):return "\n".join(call.args[0] for call in update.effective_message.reply_text.call_args_list).replace("\\", "")
