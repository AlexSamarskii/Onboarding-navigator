"""
Base interface for embeddings providers.

Defines the abstract interface that all embeddings providers must implement.
"""

from abc import ABC, abstractmethod
from typing import List


class EmbeddingsProvider(ABC):
    """
    Abstract base class for embeddings providers.

    All embeddings providers (local, GigaChat, Yandex) must implement this interface.
    Provides consistent async API for vectorizing text.
    """

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents into vectors.

        This method is used during index building (FAQ vectorization).
        Implementations should support batch processing for efficiency.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, where each vector is a list of floats.
            Length of returned list must equal length of input texts.

        Raises:
            RuntimeError: If API fails after retries (for cloud providers).
            ValueError: If texts list is empty.

        Example:
            >>> texts = ["document 1", "document 2"]
            >>> embeddings = await provider.embed_documents(texts)
            >>> len(embeddings) == len(texts)
            True
            >>> len(embeddings[0]) == provider.dimension
            True
        """
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """
        Embed single query text into vector.

        This method is used during retrieval (user query vectorization).
        Optimized for single text processing.

        Args:
            text: Single text string to embed.

        Returns:
            Embedding vector as list of floats.
            Length equals provider.dimension.

        Raises:
            RuntimeError: If API fails after retries (for cloud providers).
            ValueError: If text is empty.

        Example:
            >>> query = "What is the password reset procedure?"
            >>> embedding = await provider.embed_query(query)
            >>> len(embedding) == provider.dimension
            True
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """
        Vector dimension for this embeddings provider.

        Returns:
            Integer dimension size (e.g., 384 for MiniLM, 1024 for GigaChat).

        Note:
            This is used for:
            - OpenSearch index mapping (knn_vector dimension)
            - Dimension compatibility checks when switching providers
        """
        pass
