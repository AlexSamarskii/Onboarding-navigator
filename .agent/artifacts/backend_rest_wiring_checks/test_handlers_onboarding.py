from unittest.mock import Mock
import pytest
from _handlers_support import setup,set_mode,texts

@pytest.mark.asyncio
async def test_collect_profile_then_specific_plan():
    h,u=setup("onboarding_plan");await set_mode(h,"onboarding_plan")
    await h.handle_message(u,None);assert "Укажите вашу роль" in texts(u)
    u.message.text="developer";await h.handle_message(u,None)
    assert "Укажите ваш отдел" in texts(u)
    u.message.text="engineering";await h.handle_message(u,None)
    assert (await h.session_manager.get_session(11))["profile"]["department"]=="engineering"
    assert "engineering" in texts(u)

@pytest.mark.asyncio
async def test_missing_specific_plan_writes_and_offers_default():
    h,u=setup("onboarding_plan");await set_mode(h,"onboarding_plan")
    await h.session_manager.set_profile(11,"unknown","unknown")
    h.unanswered_writer=Mock()
    await h.handle_message(u,None)
    assert h.unanswered_writer.write.call_args.args[0].reason=="missing_plan"
    assert "план для вашей роли пока не настроен" in texts(u)
    assert "Доступен общий план" in texts(u)
