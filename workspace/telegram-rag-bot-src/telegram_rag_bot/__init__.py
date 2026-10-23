"""
Telegram RAG Bot - Production-ready FAQ bot with Russian LLMs.

A configurable Telegram chatbot powered by:
- Multi-LLM Orchestrator (GigaChat, YandexGPT)
- LangChain RAG chains
- FAISS/OpenSearch vector stores
- Flexible embeddings (Local, GigaChat, Yandex)
"""

__version__ = "0.14.6"
__author__ = "Mikhail Malorod"
__license__ = "MIT"

from telegram_rag_bot.main import main
from telegram_rag_bot.usage_tracking import create_track_usage_callback

__all__ = ["main", "create_track_usage_callback", "__version__"]
