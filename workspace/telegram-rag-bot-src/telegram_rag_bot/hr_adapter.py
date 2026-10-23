"""LocalFAISS-compatible score gate and atomic per-mode indexing adapter.

Configure retrieval.async_mode=False so RAGChainFactory uses this facade's
BaseRetriever. This module never replaces or mutates the factory implementation.
"""
import asyncio
from copy import deepcopy
from functools import lru_cache
import math
from pathlib import Path
import re
import shutil
import tempfile
from threading import RLock
from typing import Any
import uuid

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider


class LowScoreFallback(ValueError):
    def __init__(self, candidates, top_score=0.0):
        super().__init__('retrieval did not establish sufficient relevance')
        self.candidates = candidates
        self.top_score = top_score


def _mode(mode):
    if not isinstance(mode, str) or not re.fullmatch('[a-z0-9_-]+', mode):
        raise ValueError('invalid mode identifier')
    return mode


class _Retriever(BaseRetriever):
    store: Any
    threshold: float

    def _get_relevant_documents(self, query, *, run_manager=None):
        pairs = self.store.similarity_search_with_score(query, k=3)
        # FAISS L2 has metric_type=1. Other/missing metrics fail closed.
        if getattr(getattr(self.store, 'index', None), 'metric_type', None) != 1 or not pairs:
            raise LowScoreFallback([], 0.0)
        scored = []
        for doc, distance in pairs:
            try:
                distance = float(distance)
            except (ValueError, TypeError):
                raise LowScoreFallback([], 0.0) from None
            if not math.isfinite(distance) or distance < 0:
                raise LowScoreFallback([], 0.0)
            similarity = max(0.0, min(1.0, 1.0 / (1.0 + distance)))
            scored.append((doc, similarity))
        top = max(score for _, score in scored)
        if top < self.threshold:
            raise LowScoreFallback([], top)
        return [Document(page_content=doc.page_content,
                         metadata={**deepcopy(doc.metadata), 'score': score})
                for doc, score in scored]


class _Facade:
    def __init__(self, store, threshold):
        self.store, self.threshold = store, threshold

    def __getattr__(self, name):
        return getattr(self.store, name)

    def as_retriever(self, search_kwargs=None, **kwargs):
        if kwargs or (search_kwargs is not None and search_kwargs != {'k': 3}):
            raise ValueError('HR retrieval requires k=3')
        return _Retriever(store=self.store, threshold=self.threshold)


class HRFAISSProvider(LocalFAISSProvider):
    def __init__(self, config, embeddings_provider, *, rag_factory=None, score_threshold=None):
        super().__init__(config, embeddings_provider)
        threshold = config.get('score_threshold', 0.65) if score_threshold is None else score_threshold
        if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('invalid score threshold')
        self.score_threshold = float(threshold)
        self.rag_factory = rag_factory
        self._publication_lock = RLock()

    def load_index(self, mode):
        # Hold publication lock through BOTH functools cache insertions, not just
        # through the loader body. Otherwise a reader can reinsert an old facade
        # after a writer has invalidated the cache at publication.
        with self._publication_lock:
            return self._cached_load_index(_mode(mode))

    @lru_cache(maxsize=10)
    def _cached_load_index(self, mode):
        store = LocalFAISSProvider.load_index(self, mode)
        return _Facade(store, self.score_threshold)

    # Preserve the base provider's public cache invalidation interface.
    load_index.cache_clear = _cached_load_index.cache_clear

    def _invalidate(self):
        LocalFAISSProvider.load_index.cache_clear()
        self.load_index.cache_clear()
        if self.rag_factory is not None:
            self.rag_factory.chains.clear()

    def save_index(self, vectorstore, mode):
        """Stage fully before publication; roll back old on rename failure.

        Atomicity is process-local. Independent pods require a single reindex owner
        or shared distributed publication coordination, supplied by deployment.
        """
        mode = _mode(mode)
        stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.indices_dir))
        target = self.indices_dir / mode
        backup = self.indices_dir / ('.backup-' + uuid.uuid4().hex)
        try:
            vectorstore.save_local(str(stage))
            with self._publication_lock:
                had_old = target.exists()
                if had_old:
                    target.rename(backup)
                try:
                    stage.rename(target)
                except BaseException:
                    if had_old:
                        backup.rename(target)
                    raise
                self._invalidate()
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if backup.exists() and target.exists():
                shutil.rmtree(backup)

    async def delete_index(self, mode):
        def delete():
            with self._publication_lock:
                target = self.indices_dir / _mode(mode)
                if target.exists():
                    shutil.rmtree(target)
                self._invalidate()
        await asyncio.to_thread(delete)


class IndexCoordinator:
    """sources maps allowed file paths to mode identifiers, never to text.

    Build all indices before publishing any. Each mode publishes atomically; a
    multi-mode invocation rolls back all previously published mode indices on any
    publication failure under the same process lock. Sources are trusted admin-owned files; deployment
    must prohibit concurrent untrusted filesystem mutations (TOCTOU).
    """
    def __init__(self, provider: HRFAISSProvider, modes_directory: Path, *, chunk_size=1000, chunk_overlap=100):
        self.provider = provider
        self.root = Path(modes_directory).resolve(strict=True)
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    async def ingest(self, sources: dict[Path, str]):
        groups = {}
        for raw_path, mode in sources.items():
            mode = _mode(mode)
            raw_path = Path(raw_path)
            if '..' in raw_path.parts:
                raise ValueError('source traversal forbidden')
            path = raw_path.resolve(strict=True)
            bundle = (self.root / mode).resolve(strict=True)
            if bundle != self.root / mode or not path.is_relative_to(self.root) or path.relative_to(self.root).parts[0] != mode or not path.is_relative_to(bundle) or not path.is_file() or path.suffix != '.md':
                raise ValueError('source must be a markdown file inside its mode bundle')
            groups.setdefault(mode, []).append(Document(page_content=path.read_text(encoding='utf-8'), metadata={'source': str(path), 'mode': mode}))
        # Existing provider exposes async embeddings. Reuse its stable wrapper.
        from telegram_rag_bot.langchain_adapter.rag_chains import LangChainEmbeddingsWrapper
        embedding = getattr(self.provider.embeddings_provider, 'model', None)
        if not hasattr(embedding, 'embed_documents'):
            embedding = LangChainEmbeddingsWrapper(self.provider.embeddings_provider)
        built = {}
        for mode, documents in groups.items():
            chunks = self.splitter.split_documents(documents)
            if not chunks:
                raise ValueError('empty mode content')
            built[mode] = await asyncio.to_thread(FAISS.from_documents, chunks, embedding)
        def publish():
            provider = self.provider
            with provider._publication_lock:
                backup_root = Path(tempfile.mkdtemp(prefix='.transaction-', dir=provider.indices_dir))
                previous = {}
                try:
                    for mode in built:
                        target = provider.indices_dir / mode
                        previous[mode] = target.exists()
                        if previous[mode]:
                            shutil.copytree(target, backup_root / mode)
                    published = []
                    try:
                        for mode, store in built.items():
                            provider.save_index(store, mode)
                            published.append(mode)
                    except BaseException:
                        for mode in built:
                            target = provider.indices_dir / mode
                            if target.exists():
                                shutil.rmtree(target)
                            if previous[mode]:
                                (backup_root / mode).rename(target)
                        provider._invalidate()
                        raise
                finally:
                    shutil.rmtree(backup_root)
        await asyncio.to_thread(publish)
        return {mode: len(groups[mode]) for mode in groups}
