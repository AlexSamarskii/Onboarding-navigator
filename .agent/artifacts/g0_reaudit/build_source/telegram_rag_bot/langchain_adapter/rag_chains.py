"""
RAG Chain Factory - creates and manages LangChain RAG chains.

Handles:
- Vector store abstraction (FAISS/OpenSearch)
- Embeddings abstraction (Local/GigaChat/Yandex)
- Document chunking
- Retrieval-augmented generation chains
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.embeddings import Embeddings
from langchain_classic.chains.retrieval import (
    create_retrieval_chain,
)  # LangChain 1.x: using langchain-classic package
from langchain_classic.chains.combine_documents.stuff import (
    create_stuff_documents_chain,
)  # LangChain 1.x: using langchain-classic package

from telegram_rag_bot.embeddings.base import EmbeddingsProvider
from telegram_rag_bot.embeddings.factory import EmbeddingsFactory
from telegram_rag_bot.vectorstore.factory import VectorStoreFactory
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider
from telegram_rag_bot.vectorstore.cloud_opensearch import (
    OpenSearchProvider,
    OpenSearchRetriever,
)

# Try to import AsyncFAISSRetriever for async retrieval support (v0.9.0+)
try:
    from orchestrator.retrieval import AsyncFAISSRetriever
except ImportError:
    AsyncFAISSRetriever = None  # Requires multi-llm-orchestrator[retrieval]>=0.9.0

logger = logging.getLogger(__name__)


class LangChainEmbeddingsWrapper(Embeddings):
    """
    LangChain-совместимый wrapper для EmbeddingsProvider.

    Позволяет использовать async embeddings provider (GigaChat/Yandex)
    с синхронным FAISS API. Наследуется от langchain_core.embeddings.Embeddings
    для полной совместимости с LangChain FAISS.
    """

    def __init__(self, embeddings_provider: EmbeddingsProvider):
        """
        Args:
            embeddings_provider: Async embeddings provider (GigaChat/Yandex/Local)
        """
        self.provider = embeddings_provider

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents (sync wrapper для async provider).

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        # Используем asyncio.run() для создания нового event loop
        # Это гарантирует, что все async операции выполняются в изолированном контексте
        return asyncio.run(self.provider.embed_documents(texts))

    def embed_query(self, text: str) -> List[float]:
        """
        Embed single query text (sync wrapper для async provider).

        Args:
            text: Query text to embed

        Returns:
            Embedding vector
        """
        # Используем asyncio.run() для создания нового event loop
        # Если возникает RuntimeError (event loop уже запущен), используем fallback
        try:
            return asyncio.run(self.provider.embed_query(text))
        except RuntimeError:
            # Fallback: если event loop уже запущен, используем ThreadPoolExecutor
            import concurrent.futures

            def _run_in_new_loop():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self.provider.embed_query(text))
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_run_in_new_loop)
                return future.result()


class RAGChainFactory:
    """
    Factory for creating RAG chains with flexible vector stores.

    Handles:
    - Vector store abstraction (FAISS/OpenSearch)
    - Embeddings abstraction (Local/GigaChat/Yandex)
    - Document chunking
    - Retrieval-augmented generation chains
    """

    def __init__(
        self,
        llm: Any,  # LangChain LLM instance (MultiLLMOrchestrator or any BaseLLM)
        vectorstore_config: Dict[str, Any],  # vectorstore section from config.yaml
        chunk_config: Dict[str, Any],  # chunk_size, chunk_overlap from config.yaml
        modes: Dict[str, Any],  # modes section from config.yaml
        embeddings_config: Optional[
            Dict[str, Any]
        ] = None,  # Optional: create embeddings from config
        embeddings_instance: Optional[
            "EmbeddingsProvider"
        ] = None,  # Optional: use pre-initialized embeddings
        retrieval_config: Optional[
            Dict[str, Any]
        ] = None,  # Optional: retrieval settings (async_mode, etc.)
    ):
        """
        Initialize RAG factory.

        Args:
            llm: LangChain LLM instance (MultiLLMOrchestrator or any BaseLLM)
            vectorstore_config: vectorstore section from config.yaml
            chunk_config: dict with chunk_size, chunk_overlap
            modes: modes section from config.yaml
            embeddings_config: Optional embeddings config (backward compat mode).
                If None, embeddings_instance must be provided.
            embeddings_instance: Optional pre-initialized embeddings provider
                (Shared Pool mode - 10x memory reduction).
                If None, embeddings_config must be provided.
            retrieval_config: Optional retrieval settings (v0.11.0+).
                Supports {"async_mode": bool} for async FAISS retrieval.
                Defaults to {"async_mode": False}.

        Raises:
            ValueError: If both embeddings_config and embeddings_instance are None.

        Example (Backward Compatible Mode):
            >>> rag_factory = RAGChainFactory(
            ...     llm=llm,
            ...     embeddings_config={"type": "gigachat", "gigachat": {"api_key": "..."}},
            ...     vectorstore_config={...},
            ...     chunk_config={...},
            ...     modes={...}
            ... )

        Example (Shared Pool Mode - 10x Memory Reduction):
            >>> import os
            >>> from telegram_rag_bot.embeddings.factory import EmbeddingsFactory
            >>>
            >>> # Create embeddings ONCE for all bots (200MB RAM)
            >>> shared_embeddings = EmbeddingsFactory.create({
            ...     "type": "gigachat",
            ...     "gigachat": {"api_key": os.getenv("GIGACHAT_KEY"), "model": "Embeddings"}
            ... })
            >>>
            >>> # Each bot uses shared embeddings (200MB × 1 = 200MB total)
            >>> rag_factory = RAGChainFactory(
            ...     llm=llm,
            ...     embeddings_instance=shared_embeddings,  # Shared!
            ...     vectorstore_config={...},
            ...     chunk_config={...},
            ...     modes={...}
            ... )
            >>> # Total memory: 200MB (not 20GB for 100 bots!)
        """
        self.llm = llm
        self.chunk_size = chunk_config["chunk_size"]
        self.chunk_overlap = chunk_config["chunk_overlap"]
        self.modes = modes
        self.chains = {}  # Cache for RAG chains
        self.mode_locks = {}  # Concurrency locks per mode
        self.retrieval_config = (
            retrieval_config or {}
        )  # Retrieval settings (async_mode, etc.)

        # PRIORITY-BASED LOGIC: embeddings_instance → embeddings_config → error
        # (Issue #4: graceful degradation for production)
        if embeddings_instance:
            # PRIORITY 1: Shared Pool mode (performance-critical)
            self.embeddings_provider = embeddings_instance
            logger.info("✅ Using shared embeddings instance")

            # WARNING if both provided (but continue working!)
            if embeddings_config:
                logger.warning(
                    "Both embeddings_instance and embeddings_config provided. "
                    "Using embeddings_instance (Shared Pool mode takes priority)."
                )

        elif embeddings_config:
            # PRIORITY 2: Backward compatible mode
            logger.info("Creating embeddings provider from config...")
            try:
                self.embeddings_provider = EmbeddingsFactory.create(embeddings_config)
                logger.info(
                    f"✅ Embeddings provider created: {type(self.embeddings_provider).__name__}"
                )
            except Exception as e:
                logger.error(f"Failed to create embeddings provider: {e}")
                raise

        else:
            # ERROR: Neither provided
            raise ValueError(
                "Either embeddings_config or embeddings_instance must be provided"
            )

        # Create vector store provider
        logger.info("Creating vector store provider...")
        try:
            self.vectorstore_provider = VectorStoreFactory.create(
                vectorstore_config, self.embeddings_provider
            )
            logger.info(
                f"✅ Vector store provider created: {type(self.vectorstore_provider).__name__}"
            )
        except Exception as e:
            logger.error(f"Failed to create vector store provider: {e}")
            raise

    async def rebuild_index(self, mode: str, faq_file: str) -> None:
        """
        Rebuild vector index from FAQ file (async).

        Works with any vector store provider (FAISS, OpenSearch).
        Includes concurrency lock to prevent race conditions.

        Args:
            mode: Mode name (for index identification)
            faq_file: Path to FAQ markdown file

        Raises:
            FileNotFoundError: If FAQ file doesn't exist.
            ValueError: If documents list is empty.
            RuntimeError: If vectorization or storage fails.
        """
        # Validate FAQ file exists
        if not Path(faq_file).exists():
            raise FileNotFoundError(f"FAQ file not found: {faq_file}")

        # Concurrency lock per mode (prevent concurrent /reload_faq)
        if mode not in self.mode_locks:
            self.mode_locks[mode] = asyncio.Lock()

        async with self.mode_locks[mode]:
            logger.info(f"🔨 Building index for mode '{mode}' from {faq_file}")

            # Create text splitter
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", " ", ""],
            )

            # Load documents (sync I/O → async thread)
            loader = TextLoader(faq_file, encoding="utf-8")
            documents = await asyncio.to_thread(loader.load)
            logger.info(f"Loaded {len(documents)} document(s)")

            # Validate documents not empty
            if not documents:
                raise ValueError(f"FAQ file is empty: {faq_file}")

            # Split into chunks
            chunks = text_splitter.split_documents(documents)
            logger.info(f"Split into {len(chunks)} chunks")

            # Validate chunks not empty
            if not chunks:
                raise ValueError(f"No chunks created from FAQ file: {faq_file}")

            # Extract texts and metadatas
            texts = [doc.page_content for doc in chunks]
            metadatas = [
                {"source": faq_file, "mode": mode, **doc.metadata} for doc in chunks
            ]

            # Vectorize documents (batch processing with progress)
            logger.info(f"Vectorizing {len(texts)} chunks...")
            batch_size = getattr(self.embeddings_provider, "batch_size", 32)
            all_embeddings = []

            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                batch_embeddings = await self.embeddings_provider.embed_documents(batch)
                all_embeddings.extend(batch_embeddings)

                # Progress logging for large FAQ files
                if len(texts) > 100:
                    logger.info(f"📊 Vectorizing: {i+len(batch)}/{len(texts)} chunks")

            logger.info(f"✅ Vectorized {len(texts)} chunks")

            # Store in vector store
            if isinstance(self.vectorstore_provider, LocalFAISSProvider):
                # FAISS: Use pre-computed embeddings to avoid event loop conflicts
                from langchain_community.vectorstores import FAISS

                # Проверяем, есть ли у provider свойство model (как у LocalEmbeddingsProvider)
                # Если есть и это LangChain-совместимый объект - используем его
                # Иначе используем готовые embeddings (all_embeddings) для создания индекса
                if hasattr(self.embeddings_provider, "model"):
                    embeddings_model = self.embeddings_provider.model
                    # Проверяем, что это объект с методом embed_documents (не строка)
                    if hasattr(embeddings_model, "embed_documents"):
                        # LocalEmbeddingsProvider - используем напрямую
                        vectorstore = await asyncio.to_thread(
                            FAISS.from_documents, chunks, embeddings_model
                        )
                    else:
                        # GigaChat/Yandex - используем готовые embeddings через from_embeddings
                        # Создаём LangChain-совместимый wrapper для embed_query при поиске
                        embeddings_wrapper = LangChainEmbeddingsWrapper(
                            self.embeddings_provider
                        )

                        # Используем FAISS.from_embeddings с готовыми embeddings
                        # Формат: [(text, embedding), ...]
                        text_embeddings = list(zip(texts, all_embeddings))
                        vectorstore = await asyncio.to_thread(
                            FAISS.from_embeddings,
                            text_embeddings,
                            embeddings_wrapper,  # Для embed_query при поиске
                            metadatas=metadatas,
                        )
                else:
                    # Provider не имеет свойства model, используем готовые embeddings
                    embeddings_wrapper = LangChainEmbeddingsWrapper(
                        self.embeddings_provider
                    )

                    # Формат: [(text, embedding), ...]
                    text_embeddings = list(zip(texts, all_embeddings))
                    vectorstore = await asyncio.to_thread(
                        FAISS.from_embeddings,
                        text_embeddings,
                        embeddings_wrapper,
                        metadatas=metadatas,
                    )

                # Save to disk
                await asyncio.to_thread(
                    self.vectorstore_provider.save_index, vectorstore, mode
                )
                logger.info(f"✅ FAISS index saved for mode '{mode}'")

            elif isinstance(self.vectorstore_provider, OpenSearchProvider):
                # OpenSearch: Use new abstraction
                # First delete old index (if exists)
                await self.vectorstore_provider.delete_index(mode)

                # Add documents to OpenSearch
                await self.vectorstore_provider.add_documents(
                    texts, all_embeddings, metadatas, mode=mode
                )
                logger.info(f"✅ OpenSearch index created for mode '{mode}'")

            else:
                raise RuntimeError(
                    f"Unknown vector store provider: {type(self.vectorstore_provider)}"
                )

            # Clear cached chain for this mode
            if mode in self.chains:
                del self.chains[mode]
                logger.debug(f"Cleared cached chain for mode '{mode}'")

    def create_chain(self, mode: str) -> Any:
        """
        Create RAG chain for specific mode.

        Loads vector store index (FAISS or OpenSearch), creates retriever,
        and assembles retrieval chain with document chain.

        Supports both:
        - Local FAISS: Native LangChain retriever (optimized)
        - Cloud OpenSearch: Custom retriever (flexible)

        Args:
            mode: Mode name (e.g., "it_support")

        Returns:
            LangChain retrieval chain ready for queries

        Raises:
            ValueError: If mode not found in config or dimension mismatch.
            FileNotFoundError: If FAISS index not found.
            RuntimeError: If index loading fails.

        Example:
            >>> chain = factory.create_chain("it_support")
            >>> response = await chain.ainvoke({"input": "Как сбросить пароль VPN?"})
            >>> print(response["answer"])
        """
        # Check cache first (lazy loading)
        if mode in self.chains:
            logger.debug(f"Using cached chain for mode '{mode}'")
            return self.chains[mode]

        # Validate mode exists
        if mode not in self.modes:
            raise ValueError(
                f"Unknown mode: {mode}. Available: {list(self.modes.keys())}"
            )

        # Get mode config
        mode_config = self.modes[mode]
        system_prompt = mode_config["system_prompt"]
        faq_file = mode_config["faq_file"]

        # Create retriever based on vector store type
        if isinstance(self.vectorstore_provider, LocalFAISSProvider):
            # FAISS path: Use native LangChain retriever
            logger.info(f"Creating FAISS retriever for mode '{mode}'")

            try:
                vectorstore = self.vectorstore_provider.load_index(mode)

                # Check if async retrieval is enabled (Issue #5)
                async_mode = self.retrieval_config.get("async_mode", False)

                if async_mode and AsyncFAISSRetriever is not None:
                    # Use async FAISS retriever (GIL mitigation for high concurrency)
                    retriever = AsyncFAISSRetriever(vectorstore, search_kwargs={"k": 3})
                    logger.info(
                        f"✅ Loaded FAISS index for mode '{mode}' (async retrieval)"
                    )
                else:
                    # Fallback to sync retriever
                    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                    logger.info(f"✅ Loaded FAISS index for mode '{mode}'")

            except FileNotFoundError as e:
                # Index not found → clear error message
                raise FileNotFoundError(
                    f"❌ FAISS index not found for mode '{mode}'.\n"
                    f"💡 Run /reload_faq to create index."
                ) from e

            except Exception as e:
                # Corrupted index → auto-rebuild (backward compatibility)
                logger.warning(
                    f"Index corrupted for mode '{mode}': {e}. "
                    f"Auto-rebuilding from {faq_file}..."
                )
                # Note: rebuild_index is now async, need to call from async context
                # For now, raise error and let user trigger /reload_faq
                raise RuntimeError(
                    f"❌ FAISS index corrupted for mode '{mode}'.\n"
                    f"💡 Run /reload_faq to rebuild index."
                ) from e

        elif isinstance(self.vectorstore_provider, OpenSearchProvider):
            # OpenSearch path: Use custom retriever
            logger.info(f"Creating OpenSearch retriever for mode '{mode}'")

            try:
                retriever = OpenSearchRetriever(
                    vectorstore_provider=self.vectorstore_provider,
                    embeddings_provider=self.embeddings_provider,
                    mode=mode,
                    k=3,
                )
                logger.info(f"✅ Created OpenSearch retriever for mode '{mode}'")

            except ValueError as e:
                # Dimension mismatch
                raise ValueError(
                    f"❌ Dimension mismatch for mode '{mode}'.\n"
                    f"{str(e)}\n"
                    f"💡 Run /reload_faq to rebuild index with correct dimension."
                ) from e

        else:
            raise RuntimeError(
                f"❌ Unknown vector store provider: {type(self.vectorstore_provider).__name__}"
            )

        # Create prompt template with {context} for RAG
        # LangChain requires {context} variable for create_stuff_documents_chain
        # create_stuff_documents_chain automatically formats retrieved documents into {context}
        # If no documents found, {context} will be empty string (LLM handles gracefully)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "Контекст из базы знаний:\n\n{context}\n\n"
                    "Вопрос пользователя: {input}\n\n"
                    "Ответь на основе контекста выше.",
                ),
            ]
        )
        logger.debug(f"Created prompt template for mode '{mode}' with context support")

        # Create RAG chain
        document_chain = create_stuff_documents_chain(self.llm, prompt)
        chain = create_retrieval_chain(retriever, document_chain)

        # Cache chain
        self.chains[mode] = chain
        logger.info(f"✅ RAG chain created for mode '{mode}'")

        return chain
