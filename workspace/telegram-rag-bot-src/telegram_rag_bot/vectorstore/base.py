"""
Base interface for vector store providers.

Defines the abstract interface that all vector store providers must implement.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class VectorStoreProvider(ABC):
    """
    Abstract base class for vector store providers.

    All vector store providers (FAISS, OpenSearch) must implement this interface.
    Provides consistent async API for storing and retrieving vectorized documents.
    """

    @abstractmethod
    async def add_documents(
        self,
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """
        Add documents with their embeddings to vector store.

        This method is used during index building (FAQ vectorization).
        Should handle batch insertion efficiently.

        Args:
            texts: List of document texts.
            embeddings: List of embedding vectors (must match texts length).
            metadatas: List of metadata dicts (must match texts length).
                Each metadata should contain at least {"source": "faq_file_path"}.

        Raises:
            ValueError: If lengths don't match or inputs are invalid.
            RuntimeError: If storage operation fails.

        Example:
            >>> texts = ["doc1", "doc2"]
            >>> embeddings = [[0.1, 0.2, ...], [0.3, 0.4, ...]]
            >>> metadatas = [{"source": "faq.md"}, {"source": "faq.md"}]
            >>> await provider.add_documents(texts, embeddings, metadatas)
        """
        pass

    @abstractmethod
    async def similarity_search(
        self, query_embedding: List[float], k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents by query embedding.

        This method is used during retrieval (user query processing).
        Returns top-k most similar documents.

        Args:
            query_embedding: Query vector (dimension must match stored vectors).
            k: Number of results to return (default: 3).

        Returns:
            List of dicts with keys:
                - "text": Document text
                - "metadata": Document metadata
                - "score": Similarity score (optional, provider-dependent)

        Raises:
            ValueError: If query_embedding dimension doesn't match.
            RuntimeError: If search operation fails.

        Example:
            >>> query_emb = [0.5, 0.6, ...]
            >>> results = await provider.similarity_search(query_emb, k=3)
            >>> len(results) <= 3
            True
            >>> "text" in results[0] and "metadata" in results[0]
            True
        """
        pass

    @abstractmethod
    async def delete_index(self, mode: str) -> None:
        """
        Delete index for specific mode.

        This method is used when rebuilding index (/reload_faq).
        Should cleanly remove all documents for given mode.

        Args:
            mode: Mode name (e.g., "it_support").

        Raises:
            RuntimeError: If deletion fails.

        Example:
            >>> await provider.delete_index("it_support")
            # Index for "it_support" mode is removed
        """
        pass
