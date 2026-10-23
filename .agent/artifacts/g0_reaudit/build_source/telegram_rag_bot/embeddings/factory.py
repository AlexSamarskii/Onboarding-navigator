"""
Factory for creating embeddings providers.

Selects and instantiates the appropriate embeddings provider based on config.
"""

import logging
from typing import Dict

from telegram_rag_bot.embeddings.base import EmbeddingsProvider
from telegram_rag_bot.embeddings.gigachat import GigaChatEmbeddingsProvider
from telegram_rag_bot.embeddings.yandex import YandexEmbeddingsProvider

logger = logging.getLogger(__name__)


class EmbeddingsFactory:
    """
    Factory for creating embeddings providers.

    Selects provider based on config["type"]:
    - "local": LocalEmbeddingsProvider (HuggingFace)
    - "gigachat": GigaChatEmbeddingsProvider (Sber GigaChat API)
    - "yandex": YandexEmbeddingsProvider (Yandex AI Studio API)
    """

    @staticmethod
    def create(config: Dict) -> EmbeddingsProvider:
        """
        Create embeddings provider from configuration.

        Args:
            config: Configuration dictionary with structure:
                {
                    "type": "local" | "gigachat" | "yandex",
                    "local": {...},      # Config for LocalEmbeddingsProvider
                    "gigachat": {...},   # Config for GigaChatEmbeddingsProvider
                    "yandex": {...}      # Config for YandexEmbeddingsProvider
                }

        Returns:
            Instantiated EmbeddingsProvider.

        Raises:
            ValueError: If type is unknown or provider config is invalid.

        Example:
            >>> config = {
            ...     "type": "local",
            ...     "local": {
            ...         "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ...         "batch_size": 32
            ...     }
            ... }
            >>> provider = EmbeddingsFactory.create(config)
            >>> isinstance(provider, LocalEmbeddingsProvider)
            True
        """
        provider_type = config.get("type", "local")

        if provider_type == "local":
            try:
                from telegram_rag_bot.embeddings.local import LocalEmbeddingsProvider
            except ImportError as e:
                raise RuntimeError(
                    "❌ Local embeddings require optional dependencies.\n"
                    "💡 Install with: pip install telegram-rag-bot[local]\n"
                    "   Or use API embeddings: embeddings.type = 'gigachat' or 'yandex'"
                ) from e
            provider_config = config.get("local", {})
            logger.info("Creating LocalEmbeddingsProvider")
            return LocalEmbeddingsProvider(provider_config)

        elif provider_type == "gigachat":
            provider_config = config.get("gigachat", {})
            logger.info("Creating GigaChatEmbeddingsProvider")
            return GigaChatEmbeddingsProvider(provider_config)

        elif provider_type == "yandex":
            provider_config = config.get("yandex", {})
            logger.info("Creating YandexEmbeddingsProvider")
            return YandexEmbeddingsProvider(provider_config)

        else:
            raise ValueError(
                f"❌ Unknown embeddings provider type: '{provider_type}'.\n"
                f"💡 Supported types: 'local', 'gigachat', 'yandex'.\n"
                f"   Check config.yaml → embeddings.type"
            )
