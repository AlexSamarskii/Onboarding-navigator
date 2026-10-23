"""
Yandex AI Studio Embeddings provider.

This provider uses Yandex Cloud AI Studio embeddings service.
Requires API key and folder_id. Internet connection required.
"""

import logging
from typing import List, Optional

import httpx

from telegram_rag_bot.embeddings.base import EmbeddingsProvider

logger = logging.getLogger(__name__)


class YandexEmbeddingsProvider(EmbeddingsProvider):
    """
    Yandex AI Studio Embeddings provider.

    Uses Yandex Cloud AI Studio API for vectorization.
    - Endpoint: https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding
    - Authentication: API key (Bearer token)
    - Dimension: 256 (for text-search-doc model)
    - Batch: API accepts only 1 text per request (batch via loop)

    Attributes:
        api_key: Yandex API key (IAM token).
        folder_id: Yandex Cloud folder ID.
        model_uri: Full model URI (e.g., emb://<folder_id>/text-search-doc/latest).
        batch_size: Always 1 (API limitation).
        timeout: Request timeout in seconds (default: 10).
    """

    def __init__(self, config: dict):
        """
        Initialize Yandex embeddings provider.

        Args:
            config: Configuration dictionary with keys:
                - api_key: Yandex API key (required)
                - folder_id: Yandex Cloud folder ID (required)
                - model_uri: Full model URI (optional, auto-constructed if not provided)
                - timeout_seconds: Request timeout (default: 10)
                - verify_ssl_certs: SSL certificate verification (default: True)

        Raises:
            ValueError: If api_key or folder_id is missing.
        """
        self.api_key = config.get("api_key")
        self.folder_id = config.get("folder_id")

        if not self.api_key:
            raise ValueError(
                "❌ YANDEX_EMBEDDINGS_KEY not set in environment.\n"
                "💡 Set it or change embeddings.type to 'local' in config.yaml"
            )

        if not self.folder_id:
            raise ValueError(
                "❌ YANDEX_FOLDER_ID not set in environment.\n"
                "💡 Set it or change embeddings.type to 'local' in config.yaml"
            )

        # Model URI: emb://<folder_id>/text-search-doc/latest
        self.model_uri = config.get("model_uri")
        if not self.model_uri:
            self.model_uri = f"emb://{self.folder_id}/text-search-doc/latest"
        # Replace ${YANDEX_FOLDER_ID} placeholder if present
        elif "${YANDEX_FOLDER_ID}" in self.model_uri:
            self.model_uri = self.model_uri.replace(
                "${YANDEX_FOLDER_ID}", self.folder_id
            )

        self.timeout = config.get("timeout_seconds", 10)
        self.verify_ssl_certs = config.get("verify_ssl_certs", True)  # Дефолт: True
        self.batch_size = 1  # Yandex API accepts only 1 text per request

        self.embeddings_url = (
            "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
        )
        self._client: Optional[httpx.AsyncClient] = None

        logger.info(
            f"YandexEmbeddingsProvider initialized (model: {self.model_uri}, timeout: {self.timeout}s)"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialize httpx.AsyncClient within the running event loop.

        Creates a new client if none exists or the current one is closed.
        Avoids 'Event loop is closed' errors when the provider is
        initialized before asyncio.run() starts the main event loop.

        Returns:
            Active httpx.AsyncClient instance.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                verify=self.verify_ssl_certs,
            )
        return self._client

    async def _embed_single(self, text: str) -> List[float]:
        """
        Embed a single text via Yandex API.

        Yandex API accepts only one text per request.

        Args:
            text: Single text string to embed.

        Returns:
            Embedding vector (256-dimensional).

        Raises:
            RuntimeError: If API request fails.
        """
        try:
            response = await (await self._get_client()).post(
                self.embeddings_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"modelUri": self.model_uri, "text": text},
            )
            response.raise_for_status()

            data = response.json()
            embedding = data["embedding"]
            return embedding

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError(
                    "❌ Yandex API authentication failed (401).\n"
                    "💡 Check YANDEX_EMBEDDINGS_KEY validity (IAM token may be expired)"
                ) from e
            elif e.response.status_code == 429:
                raise RuntimeError(
                    "❌ Yandex API rate limit exceeded (429).\n"
                    "💡 Please try again later or reduce request frequency."
                ) from e
            else:
                raise RuntimeError(
                    f"❌ Yandex API error: {e.response.status_code} - {e.response.text}"
                ) from e

        except Exception as e:
            raise RuntimeError(f"❌ Yandex embeddings request failed: {e}") from e

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents via Yandex API.

        Since Yandex API accepts only 1 text per request, this method
        processes texts sequentially (could be parallelized with asyncio.gather
        but respect rate limits).

        Includes progress logging for large FAQ files.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (256-dimensional).

        Raises:
            ValueError: If texts list is empty.
            RuntimeError: If API fails.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        logger.info(
            f"Embedding {len(texts)} documents via Yandex AI Studio (sequential processing)"
        )

        all_embeddings = []
        for i, text in enumerate(texts):
            embedding = await self._embed_single(text)
            all_embeddings.append(embedding)

            # Progress logging for large files (every 50 chunks)
            if len(texts) > 100 and (i + 1) % 50 == 0:
                logger.info(f"📊 Vectorizing: {i+1}/{len(texts)} chunks")

        logger.info(f"✅ Embedded {len(texts)} documents via Yandex AI Studio")
        return all_embeddings

    async def embed_query(self, text: str) -> List[float]:
        """
        Embed single query text via Yandex API.

        Args:
            text: Single text string to embed.

        Returns:
            Embedding vector (256-dimensional).

        Raises:
            ValueError: If text is empty.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        return await self._embed_single(text)

    @property
    def dimension(self) -> int:
        """
        Vector dimension for Yandex text-search-doc model.

        Returns:
            256 (fixed for text-search-doc model).
        """
        return 256

    async def close(self) -> None:
        """Close HTTP client connection."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
