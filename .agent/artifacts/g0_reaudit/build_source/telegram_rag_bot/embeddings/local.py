"""
Local embeddings provider using HuggingFace sentence-transformers.

Runs fully offline with pre-downloaded models. No API keys required.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from telegram_rag_bot.embeddings.base import EmbeddingsProvider

if TYPE_CHECKING:
    from langchain_community.embeddings import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)


class LocalEmbeddingsProvider(EmbeddingsProvider):
    """
    Local embeddings using HuggingFace sentence-transformers.

    Attributes:
        model_name: HF model identifier.
        batch_size: Batch size for embedding.
        device: Target device for model (default cpu).
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize local embeddings provider.

        Args:
            config: Configuration dictionary with optional keys:
                - model: HF model name.
                - batch_size: Batch size for embedding.
                - device: Target device (defaults to cpu).
                - encode_kwargs: Extra encode kwargs override.
                - model_kwargs: Extra model kwargs override.
        """
        self.model_name: str = config.get(
            "model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        if not self.model_name:
            raise ValueError("❌ Embeddings model name must be set in config")

        self.batch_size: int = int(config.get("batch_size", 32))
        self.device: str = config.get("device", "cpu")
        self.model_kwargs: Dict[str, Any] = config.get(
            "model_kwargs", {"device": self.device}
        )
        self.encode_kwargs: Dict[str, Any] = config.get(
            "encode_kwargs", {"normalize_embeddings": True}
        )

        self._model: Optional["HuggingFaceEmbeddings"] = None
        self._dimension: Optional[int] = None
        self._model_size_mb: Optional[int] = None

        logger.info(
            f"LocalEmbeddingsProvider initialized with model: {self.model_name}"
        )

    def _ensure_model_loaded(self) -> "HuggingFaceEmbeddings":
        """
        Lazily load embeddings model and detect dimension.

        Returns:
            HuggingFaceEmbeddings: Loaded embeddings model.

        Raises:
            RuntimeError: If model download/loading fails or optional dependencies missing.
        """
        if self._model is not None:
            return self._model

        # Lazy import: HuggingFaceEmbeddings requires sentence-transformers (optional dependency)
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
        except ImportError as e:
            error_msg = str(e).lower()
            if (
                "sentence" in error_msg
                or "transformers" in error_msg
                or "torch" in error_msg
            ):
                raise RuntimeError(
                    "❌ Local embeddings require optional dependencies.\n"
                    "💡 Install with: pip install telegram-rag-bot[local]\n"
                    "   Missing: sentence-transformers (and dependencies: torch, transformers)"
                ) from e
            raise

        logger.info(
            f"Loading embeddings model: {self.model_name} "
            f"(dimension=auto, device={self.device}, ~{self.model_size_mb} MB)"
        )
        try:
            self._model = HuggingFaceEmbeddings(
                model_name=self.model_name,
                model_kwargs={"device": self.device, **self.model_kwargs},
                encode_kwargs={"normalize_embeddings": True, **self.encode_kwargs},
            )
            self._dimension = self._detect_dimension(self._model)
            logger.info(
                f"✅ Model loaded: {self.model_name} "
                f"(dimension={self._dimension}, device={self.device}, ~{self.model_size_mb} MB)"
            )
            return self._model
        except Exception as exc:
            error_msg = str(exc).lower()

            # ⚠️ Different failure modes need actionable guidance
            if "timeout" in error_msg or "connection" in error_msg:
                logger.error(
                    f"❌ Network error loading embeddings model {self.model_name}: {exc}"
                )
                raise RuntimeError(
                    "Failed to download embeddings model (network timeout). "
                    "Check internet connection or use VPN if HuggingFace is blocked in your region."
                ) from exc
            if "memory" in error_msg or "oom" in error_msg:
                logger.error(
                    f"❌ OOM while loading embeddings model {self.model_name}: {exc}"
                )
                raise RuntimeError(
                    "Insufficient RAM to load embeddings model (~1.5 GB required). "
                    "Consider using a smaller model (e.g., cointegrated/rubert-tiny2)."
                ) from exc

            logger.error(f"❌ Failed to load embeddings model {self.model_name}: {exc}")
            raise RuntimeError(f"Failed to load embeddings model: {exc}") from exc

    def _detect_dimension(self, model: "HuggingFaceEmbeddings") -> int:
        """
        Detect embedding dimension from HF model.

        Args:
            model: Loaded HuggingFaceEmbeddings instance.

        Returns:
            int: Detected dimension size.
        """
        # ✅ Try zero-cost API first; falls back to embedding a tiny string if absent
        # Try zero-cost client API first.
        try:
            dim_value = model.client.get_sentence_embedding_dimension()
            if isinstance(dim_value, (int, float)):
                return int(dim_value)
        except Exception:
            pass

        # Fallback: embed a tiny string and infer len().
        try:
            test_vector = model.embed_query("test")
            return len(test_vector)
        except Exception as exc:
            raise RuntimeError(
                "Failed to detect embeddings dimension from model"
            ) from exc

    @property
    def model(self) -> "HuggingFaceEmbeddings":
        """
        Return loaded embeddings model (lazy).

        Returns:
            HuggingFaceEmbeddings: Loaded model instance.
        """
        return self._ensure_model_loaded()

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents using HuggingFace model.

        Args:
            texts: List of text strings to embed.

        Returns:
            List[List[float]]: Embedding vectors.

        Raises:
            ValueError: If texts list is empty.
            RuntimeError: If model loading fails.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        logger.info(
            f"Embedding {len(texts)} documents with batch_size={self.batch_size}"
        )

        embeddings = await asyncio.to_thread(self.model.embed_documents, texts)

        logger.info(f"✅ Embedded {len(texts)} documents → {len(embeddings)} vectors")
        return embeddings

    async def embed_query(self, text: str) -> List[float]:
        """
        Embed single query text.

        Args:
            text: Single text string to embed.

        Returns:
            List[float]: Embedding vector.

        Raises:
            ValueError: If text is empty.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        embedding = await asyncio.to_thread(self.model.embed_query, text)
        return embedding

    @property
    def dimension(self) -> int:
        """
        Get vector dimension for current embeddings model.

        Returns:
            int: Dimension size.
        """
        self._ensure_model_loaded()
        assert self._dimension is not None
        return self._dimension

    @property
    def model_size_mb(self) -> int:
        """
        Approximate model size in MB for logging.

        Returns:
            int: Approximate size in megabytes.
        """
        if self._model_size_mb is not None:
            return self._model_size_mb

        known_sizes = {
            "sberbank-ai/sbert_large_nlu_ru": 1100,
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 500,
        }
        self._model_size_mb = known_sizes.get(self.model_name, 700)
        return self._model_size_mb


# pyright: reportMissingImports=false
