"""Reproduce a permitted reader/writer scheduling at lock release."""
from functools import lru_cache
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace
from telegram_rag_bot.hr_adapter import HRFAISSProvider
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider


def test_concurrent_save_cannot_recache_old_facade(tmp_path, monkeypatch):
    class Store:
        def __init__(self, value): self.value = value
        def save_local(self, path):
            Path(path).mkdir(exist_ok=True)
            (Path(path) / 'content').write_text(self.value)
    @lru_cache(maxsize=10)
    def load(self, mode):
        return Store((self.indices_dir / mode / 'content').read_text())
    monkeypatch.setattr(LocalFAISSProvider, 'load_index', load)
    provider = HRFAISSProvider({'indices_dir': str(tmp_path)}, SimpleNamespace())
    provider.save_index(Store('old'), 'it_support')
    released = Event(); published = Event()
    underlying = RLock()
    # An OS may deschedule a reader just after it releases its body lock.
    class ScheduledLock:
        def __enter__(self): underlying.acquire(); return self
        def __exit__(self, *args):
            underlying.release()
            if current_thread().name == 'scheduled-reader':
                released.set()
                assert published.wait(3)
    provider._publication_lock = ScheduledLock()
    errors = []
    def reader():
        try: provider.load_index('it_support')
        except BaseException as error: errors.append(error)
    thread = Thread(target=reader, name='scheduled-reader')
    thread.start()
    assert released.wait(3)
    try: provider.save_index(Store('new'), 'it_support')
    finally: published.set()
    thread.join(3)
    assert not errors and not thread.is_alive()
    assert provider.load_index('it_support').store.value == 'new'
