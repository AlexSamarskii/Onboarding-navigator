from types import SimpleNamespace
import pytest
from _handlers_support import setup,texts

@pytest.mark.asyncio
async def test_reindex_admin_and_denied():
    h,u=setup();await h.cmd_reindex(u,SimpleNamespace(args=[]))
    assert h.coordinator.ingest.await_count==1
    assert h.runtime_state["last_reindex"]!="never"
    u.effective_user.id=99
    await h.cmd_reindex(u,None)
    assert h.coordinator.ingest.await_count==1
    assert "недостаточно прав" in texts(u)

@pytest.mark.asyncio
async def test_status_fields_and_denied():
    h,u=setup();h.health_cache.update(gigachat="ok",yandexgpt="fail")
    await h.cmd_status(u,None)
    for expected in ["it_support","GigaChat: ok","YandexGPT: fail","FAISS: 7","never"]:assert expected in texts(u)
    u.effective_user.id=99;await h.cmd_status(u,None)
    assert "недостаточно прав" in texts(u)

@pytest.mark.asyncio
async def test_reload_alias():
    h,u=setup();await h.cmd_reload_faq(u,SimpleNamespace(args=[]))
    h.coordinator.ingest.assert_awaited_once()

@pytest.mark.asyncio
async def test_status_empty_index_and_unresolved_admin_fail_closed():
    h,u=setup();h.rag_factory.vectorstore_provider.load_index.side_effect=FileNotFoundError()
    await h.cmd_status(u,None)
    assert "FAISS: 0" in texts(u)
    h.config["ADMIN_IDS"]="${ADMIN_IDS}"
    await h.cmd_status(u,None)
    assert "недостаточно прав" in texts(u)
