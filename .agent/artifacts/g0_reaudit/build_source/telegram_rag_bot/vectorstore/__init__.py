"""
Vector store providers abstraction layer.

This module provides a unified interface for different vector store backends:
- LocalFAISSProvider: FAISS local disk storage (offline)
- OpenSearchProvider: OpenSearch managed cluster (cloud)

Usage:
    from telegram_rag_bot.vectorstore import VectorStoreFactory

    provider = VectorStoreFactory.create(
        config={
            "type": "faiss",
            "faiss": {"indices_dir": ".faiss_indices"}
        },
        embeddings_provider=embeddings_provider
    )

    await provider.add_documents(texts, embeddings, metadatas)
"""

from telegram_rag_bot.vectorstore.base import VectorStoreProvider
from telegram_rag_bot.vectorstore.factory import VectorStoreFactory

__all__ = ["VectorStoreProvider", "VectorStoreFactory"]
