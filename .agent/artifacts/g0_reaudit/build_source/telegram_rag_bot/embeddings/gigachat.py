"""
GigaChat Embeddings provider using Sber GigaChat API.

This provider uses GigaChat's cloud-based embeddings service.
Requires API key (OAuth2) and internet connection.
"""

import asyncio
import base64
import logging
import uuid
from typing import List, Optional

import httpx

from telegram_rag_bot.embeddings.base import EmbeddingsProvider

logger = logging.getLogger(__name__)


class GigaChatEmbeddingsProvider(EmbeddingsProvider):
    """
    GigaChat Embeddings provider (Sber AI).

    Uses GigaChat Embeddings API for vectorization.
    - Endpoint: https://gigachat.devices.sberbank.ru/api/v1/embeddings
    - Authentication: OAuth2 Basic auth (base64(api_key))
    - Dimension: 1024
    - Batch limit: Up to 100 texts (recommended: 16 for stability)

    Attributes:
        api_key: GigaChat API key (OAuth2 credentials).
        model: Model name (default: "Embeddings").
        batch_size: Batch size for processing (default: 16).
        timeout: Request timeout in seconds (default: 30).
    """

    def __init__(self, config: dict):
        """
        Initialize GigaChat embeddings provider.

        Args:
            config: Configuration dictionary with keys:
                - api_key: GigaChat API key (required)
                - model: Model name (default: "Embeddings")
                - batch_size: Batch size (default: 16)
                - timeout_seconds: Request timeout (default: 30)
                - scope: OAuth2 scope (default: "GIGACHAT_API_PERS")
                - verify_ssl_certs: SSL certificate verification (default: True)

        Raises:
            ValueError: If api_key is missing.
        """
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError(
                "❌ GIGACHAT_EMBEDDINGS_KEY not set in environment.\n"
                "💡 Set it or change embeddings.type to 'local' in config.yaml"
            )

        self.model = config.get("model", "Embeddings")
        self.batch_size = config.get("batch_size", 16)
        self.timeout = config.get("timeout_seconds", 30)
        self.scope = config.get("scope", "GIGACHAT_API_PERS")
        self.verify_ssl_certs = config.get("verify_ssl_certs", True)  # Дефолт: True

        # OAuth2 endpoints
        self.auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        self.embeddings_url = "https://gigachat.devices.sberbank.ru/api/v1/embeddings"

        # Access token cache (valid for ~30 minutes)
        self._access_token: Optional[str] = None

        self._client: Optional[httpx.AsyncClient] = None
        logger.info(
            f"GigaChatEmbeddingsProvider initialized (model: {self.model}, batch_size: {self.batch_size})"
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

    async def _get_access_token(self) -> str:
        """
        Get OAuth2 access token for GigaChat API.

        Implements OAuth2 flow:
        1. Use Bearer auth with api_key (as in Multi-LLM-Orchestrator)
        2. Request access token with scope
        3. Cache token for reuse

        Returns:
            Access token string.

        Raises:
            RuntimeError: If authentication fails.
        """
        if self._access_token:
            return self._access_token

        logger.info("Requesting GigaChat OAuth2 access token...")

        try:
            response = await (await self._get_client()).post(
                self.auth_url,
                headers={
                    "Authorization": f"Basic {base64.b64encode(self.api_key.encode()).decode()}",
                    "RqUID": str(uuid.uuid4()),  # Уникальный ID для каждого запроса
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": self.scope},
            )
            response.raise_for_status()

            token_data = response.json()
            self._access_token = token_data["access_token"]
            logger.info("✅ GigaChat access token obtained")
            return self._access_token

        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"❌ GigaChat authentication failed: {e.response.status_code}\n"
                f"💡 Check GIGACHAT_EMBEDDINGS_KEY validity"
            ) from e
        except Exception as e:
            raise RuntimeError(f"❌ GigaChat authentication error: {e}") from e

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts via GigaChat API.

        Args:
            texts: List of texts (up to 100, recommended 16).

        Returns:
            List of embedding vectors (1024-dimensional).

        Raises:
            RuntimeError: If API request fails after retries.
        """
        access_token = await self._get_access_token()

        # Retry logic for rate limiting
        max_retries = 3
        base_delay = 1  # seconds

        for attempt in range(max_retries):
            try:
                response = await (await self._get_client()).post(
                    self.embeddings_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": texts},
                )
                response.raise_for_status()

                data = response.json()
                # Extract embeddings in order (sorted by index)
                embeddings_data = sorted(data["data"], key=lambda x: x["index"])
                embeddings = [item["embedding"] for item in embeddings_data]

                return embeddings

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limit
                    if attempt < max_retries - 1:
                        delay = base_delay * (
                            2**attempt
                        )  # Exponential backoff: 1s, 2s, 4s
                        logger.warning(
                            f"⏳ GigaChat rate limit hit (429), retrying in {delay}s... (attempt {attempt+1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise RuntimeError(
                            "❌ GigaChat Embeddings rate limit exceeded after retries.\n"
                            "💡 Please try again later or reduce request frequency."
                        ) from e
                elif e.response.status_code == 401:  # Unauthorized (token expired)
                    logger.warning("🔄 Access token expired, refreshing...")
                    self._access_token = None  # Clear cached token
                    access_token = await self._get_access_token()
                    continue
                else:
                    raise RuntimeError(
                        f"❌ GigaChat API error: {e.response.status_code} - {e.response.text}"
                    ) from e

            except Exception as e:
                raise RuntimeError(f"❌ GigaChat embeddings request failed: {e}") from e

        raise RuntimeError("❌ GigaChat embeddings failed after all retries")

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents via GigaChat API.

        Processes texts in batches to respect API limits.
        Includes progress logging for large FAQ files.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (1024-dimensional).

        Raises:
            ValueError: If texts list is empty.
            RuntimeError: If API fails after retries.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        logger.info(
            f"Embedding {len(texts)} documents via GigaChat (batch_size={self.batch_size})"
        )

        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embeddings = await self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

            # Progress logging for large files
            if len(texts) > 100:
                logger.info(f"📊 Vectorizing: {i+len(batch)}/{len(texts)} chunks")

        logger.info(f"✅ Embedded {len(texts)} documents via GigaChat")
        return all_embeddings

    async def embed_query(self, text: str) -> List[float]:
        """
        Embed single query text via GigaChat API.

        Args:
            text: Single text string to embed.

        Returns:
            Embedding vector (1024-dimensional).

        Raises:
            ValueError: If text is empty.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        embeddings = await self._embed_batch([text])
        return embeddings[0]

    @property
    def dimension(self) -> int:
        """
        Vector dimension for GigaChat Embeddings.

        Returns:
            1024 (fixed for GigaChat Embeddings model).
        """
        return 1024

    async def close(self) -> None:
        """Close HTTP client connection."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
