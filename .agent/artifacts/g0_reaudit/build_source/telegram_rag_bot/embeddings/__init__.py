"""
Embeddings providers abstraction layer.

This module provides a unified interface for different embeddings providers:
- LocalEmbeddingsProvider: HuggingFace sentence-transformers (offline)
- GigaChatEmbeddingsProvider: Sber GigaChat Embeddings API
- YandexEmbeddingsProvider: Yandex AI Studio Embeddings API

Usage:
    from telegram_rag_bot.embeddings import EmbeddingsFactory

    provider = EmbeddingsFactory.create({
        "type": "local",
        "local": {"model": "sentence-transformers/..."}
    })

    embeddings = await provider.embed_documents(["text1", "text2"])
"""

from telegram_rag_bot.embeddings.base import EmbeddingsProvider
from telegram_rag_bot.embeddings.factory import EmbeddingsFactory

__all__ = ["EmbeddingsProvider", "EmbeddingsFactory"]
