"""
OpenSearch cloud vector store provider.

This provider uses OpenSearch managed cluster for vector storage.
Requires OpenSearch connection and credentials.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional

from opensearchpy import AsyncOpenSearch
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from telegram_rag_bot.vectorstore.base import VectorStoreProvider

logger = logging.getLogger(__name__)


class OpenSearchProvider(VectorStoreProvider):
    """
    OpenSearch cloud vector store provider.

    Uses OpenSearch for distributed vector storage and kNN search.
    - Storage: OpenSearch managed cluster
    - Requires: host, port, credentials
    - Features: Horizontal scaling, managed service

    Attributes:
        client: AsyncOpenSearch client instance.
        base_index_name: Base name for indices (mode-specific suffix added).
        dimension: Vector dimension (from embeddings_provider).
    """

    def __init__(self, config: dict, embeddings_provider):
        """
        Initialize OpenSearch provider.

        Args:
            config: Configuration dictionary with keys:
                - host: OpenSearch host (required)
                - port: OpenSearch port (default: 9200)
                - index_name: Base index name (default: "telegram-bot-faq")
                - username: Auth username (optional)
                - password: Auth password (optional)
            embeddings_provider: EmbeddingsProvider instance (for dimension).

        Raises:
            ValueError: If host is missing.
        """
        host = config.get("host")
        if not host:
            raise ValueError(
                "❌ OPENSEARCH_HOST not set in environment.\n"
                "💡 Set it or change vectorstore.type to 'faiss' in config.yaml"
            )

        port = config.get("port", 9200)
        self.base_index_name = config.get("index_name", "telegram-bot-faq")
        username = config.get("username")
        password = config.get("password")

        # Create OpenSearch client
        client_config = {
            "hosts": [{"host": host, "port": port}],
            "timeout": 30,
            "max_retries": 2,
            "retry_on_timeout": True,
        }

        if username and password:
            client_config["http_auth"] = (username, password)

        self.client = AsyncOpenSearch(**client_config)
        self.embeddings_provider = embeddings_provider
        self.dimension = embeddings_provider.dimension

        logger.info(
            f"OpenSearchProvider initialized (host: {host}:{port}, dimension: {self.dimension})"
        )

    def _get_index_name(self, mode: str) -> str:
        """
        Get full index name for mode.

        Pattern: {base_name}-{mode}
        Example: telegram-bot-faq-it_support

        Args:
            mode: Mode name.

        Returns:
            Full index name.
        """
        return f"{self.base_index_name}-{mode}"

    async def _ensure_index_exists(self, mode: str) -> None:
        """
        Ensure index exists with correct mapping.

        Creates index if not exists. Validates dimension if exists.

        Args:
            mode: Mode name.

        Raises:
            ValueError: If dimension mismatch.
            RuntimeError: If index creation fails.
        """
        index_name = self._get_index_name(mode)

        exists = await self.client.indices.exists(index=index_name)

        if exists:
            # Check dimension compatibility
            mapping = await self.client.indices.get_mapping(index=index_name)
            actual_dim = mapping[index_name]["mappings"]["properties"]["embedding"][
                "dimension"
            ]

            if actual_dim != self.dimension:
                raise ValueError(
                    f"❌ Dimension mismatch for mode '{mode}'!\n"
                    f"   Index: {actual_dim}-dim\n"
                    f"   Current embeddings: {self.dimension}-dim\n"
                    f"💡 Run /reload_faq to rebuild index with correct dimension."
                )

            logger.info(
                f"✅ OpenSearch index '{index_name}' exists with dimension {actual_dim}"
            )
        else:
            # Create new index with kNN mapping
            mapping = {
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": self.dimension,
                        },
                        "metadata": {"type": "object", "enabled": False},
                        "mode": {"type": "keyword"},  # For filtering
                    }
                },
                "settings": {"index.knn": True},
            }

            await self.client.indices.create(index=index_name, body=mapping)
            logger.info(
                f"✅ Created OpenSearch index '{index_name}' with dimension {self.dimension}"
            )

    async def add_documents(
        self,
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        mode: Optional[str] = None,
    ) -> None:
        """
        Add documents to OpenSearch index.

        Uses bulk API for efficient batch insertion.

        Args:
            texts: List of document texts.
            embeddings: List of embedding vectors.
            metadatas: List of metadata dicts.
            mode: Mode name (extracted from metadata if not provided).

        Raises:
            ValueError: If lengths don't match or mode missing.
            RuntimeError: If bulk insert fails.
        """
        if not (len(texts) == len(embeddings) == len(metadatas)):
            raise ValueError(
                f"Length mismatch: texts({len(texts)}), embeddings({len(embeddings)}), "
                f"metadatas({len(metadatas)})"
            )

        # Extract mode from metadata if not provided
        if mode is None:
            if metadatas and "mode" in metadatas[0]:
                mode = metadatas[0]["mode"]
            else:
                raise ValueError("Mode not provided and not found in metadata")

        # Ensure index exists
        await self._ensure_index_exists(mode)

        index_name = self._get_index_name(mode)

        # Prepare bulk request
        bulk_data = []
        for text, embedding, metadata in zip(texts, embeddings, metadatas):
            # Add mode to metadata for filtering
            metadata_with_mode = {**metadata, "mode": mode}

            bulk_data.append({"index": {"_index": index_name}})
            bulk_data.append(
                {"text": text, "embedding": embedding, "metadata": metadata_with_mode}
            )

        logger.info(
            f"Indexing {len(texts)} documents to OpenSearch index '{index_name}'"
        )

        # Bulk insert with retry
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = await self.client.bulk(body=bulk_data, refresh=True)

                # Check for errors
                if response.get("errors"):
                    failed_items = [
                        item
                        for item in response["items"]
                        if "error" in item.get("index", {})
                    ]
                    logger.error(
                        f"Bulk insert had errors: {failed_items[:5]}"
                    )  # Log first 5
                    raise RuntimeError(
                        f"Bulk insert failed for {len(failed_items)} items"
                    )

                logger.info(f"✅ Indexed {len(texts)} documents to OpenSearch")
                return

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Bulk insert attempt {attempt+1} failed, retrying: {e}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    raise RuntimeError(
                        f"❌ OpenSearch bulk insert failed after retries: {e}"
                    ) from e

    async def similarity_search(
        self, query_embedding: List[float], mode: str, k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents by query embedding.

        Uses OpenSearch kNN query DSL.

        Args:
            query_embedding: Query vector.
            mode: Mode name (for index selection).
            k: Number of results.

        Returns:
            List of result dicts with keys: "text", "metadata".

        Raises:
            ValueError: If dimension mismatch.
            RuntimeError: If search fails.
        """
        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Query embedding dimension ({len(query_embedding)}) "
                f"doesn't match expected ({self.dimension})"
            )

        index_name = self._get_index_name(mode)

        # kNN query
        query = {
            "size": k,
            "query": {"knn": {"embedding": {"vector": query_embedding, "k": k}}},
        }

        # Retry logic
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = await asyncio.wait_for(
                    self.client.search(index=index_name, body=query), timeout=5.0
                )

                # Extract results
                hits = response["hits"]["hits"]
                results = []
                for hit in hits:
                    source = hit["_source"]
                    results.append(
                        {"text": source["text"], "metadata": source["metadata"]}
                    )

                return results

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"OpenSearch search timeout, retry {attempt+1}/{max_retries}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    raise RuntimeError(
                        "❌ OpenSearch search timeout after retries.\n"
                        "💡 Check OpenSearch cluster health."
                    )

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"OpenSearch search failed, retry {attempt+1}/{max_retries}: {e}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    raise RuntimeError(
                        f"❌ OpenSearch similarity search failed: {e}"
                    ) from e

    async def delete_index(self, mode: str) -> None:
        """
        Delete OpenSearch index for specific mode.

        Args:
            mode: Mode name.
        """
        index_name = self._get_index_name(mode)

        exists = await self.client.indices.exists(index=index_name)
        if exists:
            await self.client.indices.delete(index=index_name)
            logger.info(f"🗑️ Deleted OpenSearch index '{index_name}'")
        else:
            logger.warning(
                f"⚠️ OpenSearch index '{index_name}' not found (already deleted?)"
            )

    async def close(self):
        """Close OpenSearch client connection."""
        await self.client.close()


class OpenSearchRetriever(BaseRetriever):
    """
    Custom LangChain retriever for OpenSearch.

    Integrates OpenSearchProvider with LangChain RAG chains.
    Implements BaseRetriever interface for compatibility with create_retrieval_chain().
    """

    vectorstore_provider: OpenSearchProvider
    embeddings_provider: Any
    mode: str
    k: int = 3

    def __init__(
        self, vectorstore_provider, embeddings_provider, mode: str, k: int = 3
    ):
        """
        Initialize OpenSearch retriever.

        Args:
            vectorstore_provider: OpenSearchProvider instance.
            embeddings_provider: EmbeddingsProvider instance.
            mode: Mode name.
            k: Number of results to return.
        """
        super().__init__()
        self.vectorstore_provider = vectorstore_provider
        self.embeddings_provider = embeddings_provider
        self.mode = mode
        self.k = k

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        """
        Retrieve relevant documents for query (async).

        Workflow:
        1. Embed query via embeddings_provider
        2. Search via vectorstore_provider
        3. Convert results to LangChain Documents

        Args:
            query: User query string.
            run_manager: LangChain callback manager (optional).

        Returns:
            List of LangChain Document objects.
        """
        # 1. Vectorize query
        query_embedding = await self.embeddings_provider.embed_query(query)

        # 2. Search in OpenSearch
        results = await self.vectorstore_provider.similarity_search(
            query_embedding, mode=self.mode, k=self.k
        )

        # 3. Convert to LangChain Documents
        documents = [
            Document(page_content=result["text"], metadata=result["metadata"])
            for result in results
        ]

        return documents

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        """
        Synchronous retrieval (not implemented).

        This project is fully async. Use _aget_relevant_documents() instead.

        Raises:
            NotImplementedError: Always (sync not supported).
        """
        raise NotImplementedError(
            "❌ Sync retrieval not supported in this async project.\n"
            "💡 Use: await retriever.aget_relevant_documents(query)"
        )
