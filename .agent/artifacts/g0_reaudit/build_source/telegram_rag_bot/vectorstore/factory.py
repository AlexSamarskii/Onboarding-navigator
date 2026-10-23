"""
Factory for creating vector store providers.

Selects and instantiates the appropriate vector store provider based on config.
"""

import logging
from typing import Dict

from telegram_rag_bot.vectorstore.base import VectorStoreProvider
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider
from telegram_rag_bot.vectorstore.cloud_opensearch import OpenSearchProvider

logger = logging.getLogger(__name__)


class VectorStoreFactory:
    """
    Factory for creating vector store providers.

    Selects provider based on config["type"]:
    - "faiss": LocalFAISSProvider (local disk storage)
    - "opensearch": OpenSearchProvider (cloud managed cluster)
    """

    @staticmethod
    def create(config: Dict, embeddings_provider) -> VectorStoreProvider:
        """
        Create vector store provider from configuration.

        Args:
            config: Configuration dictionary with structure:
                {
                    "type": "faiss" | "opensearch",
                    "faiss": {...},      # Config for LocalFAISSProvider
                    "opensearch": {...}  # Config for OpenSearchProvider
                }
            embeddings_provider: EmbeddingsProvider instance (for dimension compatibility).

        Returns:
            Instantiated VectorStoreProvider.

        Raises:
            ValueError: If type is unknown or provider config is invalid.

        Example:
            >>> config = {
            ...     "type": "faiss",
            ...     "faiss": {"indices_dir": ".faiss_indices"}
            ... }
            >>> provider = VectorStoreFactory.create(config, embeddings_provider)
            >>> isinstance(provider, LocalFAISSProvider)
            True
        """
        provider_type = config.get("type", "faiss")

        if provider_type == "faiss":
            provider_config = config.get("faiss", {})
            logger.info("Creating LocalFAISSProvider")
            return LocalFAISSProvider(provider_config, embeddings_provider)

        elif provider_type == "opensearch":
            provider_config = config.get("opensearch", {})
            logger.info("Creating OpenSearchProvider")
            return OpenSearchProvider(provider_config, embeddings_provider)

        else:
            raise ValueError(
                f"❌ Unknown vector store provider type: '{provider_type}'.\n"
                f"💡 Supported types: 'faiss', 'opensearch'.\n"
                f"   Check config.yaml → vectorstore.type"
            )
