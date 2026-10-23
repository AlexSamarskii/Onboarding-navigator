"""
Unit tests for embeddings providers.

Tests LocalEmbeddingsProvider, GigaChatEmbeddingsProvider, YandexEmbeddingsProvider,
and EmbeddingsFactory.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from telegram_rag_bot.embeddings.factory import EmbeddingsFactory
from telegram_rag_bot.embeddings.local import LocalEmbeddingsProvider
from telegram_rag_bot.embeddings.gigachat import GigaChatEmbeddingsProvider
from telegram_rag_bot.embeddings.yandex import YandexEmbeddingsProvider


@pytest.fixture(params=[384, 1024])
def embeddings_dimension(request):
    """Parameterize embedding dimension for local provider tests."""
    return request.param


class TestEmbeddingsFactory:
    """Tests for EmbeddingsFactory."""

    def test_create_local_provider(self):
        """Test creating LocalEmbeddingsProvider."""
        config = {
            "type": "local",
            "local": {
                "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                "batch_size": 32,
            },
        }

        provider = EmbeddingsFactory.create(config)
        assert isinstance(provider, LocalEmbeddingsProvider)
        assert (
            provider.model_name
            == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        assert provider.batch_size == 32

    def test_create_gigachat_provider(self):
        """Test creating GigaChatEmbeddingsProvider."""
        config = {
            "type": "gigachat",
            "gigachat": {
                "api_key": "test-key",
                "model": "Embeddings",
                "batch_size": 16,
            },
        }

        provider = EmbeddingsFactory.create(config)
        assert isinstance(provider, GigaChatEmbeddingsProvider)
        assert provider.api_key == "test-key"
        assert provider.batch_size == 16

    def test_create_yandex_provider(self):
        """Test creating YandexEmbeddingsProvider."""
        config = {
            "type": "yandex",
            "yandex": {
                "api_key": "test-key",
                "folder_id": "test-folder",
                "batch_size": 1,
            },
        }

        provider = EmbeddingsFactory.create(config)
        assert isinstance(provider, YandexEmbeddingsProvider)
        assert provider.api_key == "test-key"
        assert provider.folder_id == "test-folder"

    def test_unknown_type_raises_error(self):
        """Test that unknown provider type raises ValueError."""
        config = {"type": "unknown"}

        with pytest.raises(ValueError, match="Unknown embeddings provider type"):
            EmbeddingsFactory.create(config)


class TestLocalEmbeddingsProvider:
    """Tests for LocalEmbeddingsProvider."""

    def test_initialization(self):
        """Test provider initialization."""
        config = {
            "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "batch_size": 32,
        }

        provider = LocalEmbeddingsProvider(config)
        assert (
            provider.model_name
            == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        assert provider.batch_size == 32

    @pytest.mark.asyncio
    @patch("langchain_community.embeddings.HuggingFaceEmbeddings")
    @patch("telegram_rag_bot.embeddings.local.asyncio.to_thread")
    async def test_embed_documents(self, mock_to_thread, mock_hf_embeddings):
        """Test embedding multiple documents."""
        config = {"model": "test-model"}

        # Mock HuggingFaceEmbeddings initialization
        mock_model = Mock()
        mock_model.embed_documents.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_model.client = Mock()
        mock_model.client.get_sentence_embedding_dimension.return_value = 3
        mock_hf_embeddings.return_value = mock_model

        provider = LocalEmbeddingsProvider(config)

        # Mock embed_documents result
        mock_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_to_thread.return_value = mock_embeddings

        texts = ["text1", "text2"]
        result = await provider.embed_documents(texts)

        assert result == mock_embeddings
        mock_to_thread.assert_called_once()
        assert provider.dimension == 3

    @pytest.mark.asyncio
    @patch("langchain_community.embeddings.HuggingFaceEmbeddings")
    async def test_embed_empty_list_raises_error(self, mock_hf_embeddings):
        """Test that embedding empty list raises ValueError."""
        config = {"model": "test-model"}

        # Mock HuggingFaceEmbeddings initialization
        mock_model = Mock()
        mock_model.client = Mock()
        mock_model.client.get_sentence_embedding_dimension.return_value = 3
        mock_hf_embeddings.return_value = mock_model

        provider = LocalEmbeddingsProvider(config)

        with pytest.raises(ValueError, match="Cannot embed empty list"):
            await provider.embed_documents([])

    @pytest.mark.asyncio
    @patch("langchain_community.embeddings.HuggingFaceEmbeddings")
    async def test_dimension_detected_via_embed_fallback(self, mock_hf_embeddings):
        """Dimension falls back to embed_query when client API is unavailable."""
        config = {"model": "test-model"}

        mock_model = Mock()
        mock_model.client = Mock()
        mock_model.client.get_sentence_embedding_dimension.side_effect = (
            AttributeError()
        )
        mock_model.embed_query.return_value = [0.1, 0.2, 0.3, 0.4]
        mock_hf_embeddings.return_value = mock_model

        provider = LocalEmbeddingsProvider(config)

        assert provider.dimension == 4


class TestGigaChatEmbeddingsProvider:
    """Tests for GigaChatEmbeddingsProvider."""

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises ValueError."""
        config = {}

        with pytest.raises(ValueError, match="GIGACHAT_EMBEDDINGS_KEY not set"):
            GigaChatEmbeddingsProvider(config)

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_embed_documents(self, mock_client_class):
        """Test embedding documents via GigaChat API."""
        config = {"api_key": "test-key", "model": "Embeddings", "batch_size": 2}

        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
                {"embedding": [0.3, 0.4], "index": 1},
            ]
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = GigaChatEmbeddingsProvider(config)
        provider._access_token = "test-token"  # Skip auth

        texts = ["text1", "text2"]
        result = await provider.embed_documents(texts)

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    def test_dimension(self):
        """Test dimension property."""
        config = {"api_key": "test-key"}
        provider = GigaChatEmbeddingsProvider(config)
        assert provider.dimension == 1024

    def test_gigachat_provider_verify_ssl_false(self):
        """Test that verify_ssl_certs=False is stored in provider attribute."""
        config = {"api_key": "test_key", "verify_ssl_certs": False}
        provider = GigaChatEmbeddingsProvider(config)

        # Проверяем только атрибут (простой тест)
        assert provider.verify_ssl_certs is False

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_gigachat_provider_lazy_init_passes_verify_to_httpx(
        self, mock_async_client
    ):
        """Test lazy init: client not created in __init__, created on first _get_client() with correct params."""
        config = {"api_key": "test_key", "verify_ssl_certs": False}

        # После __init__ клиент НЕ создан
        provider = GigaChatEmbeddingsProvider(config)
        mock_async_client.assert_not_called()
        assert provider._client is None

        # При первом _get_client() создаётся с правильными параметрами
        mock_client_instance = AsyncMock()
        mock_client_instance.is_closed = False
        mock_async_client.return_value = mock_client_instance

        client = await provider._get_client()
        mock_async_client.assert_called_once_with(timeout=30, verify=False)
        assert client is mock_client_instance

    def test_gigachat_lazy_init_client_none_before_async(self):
        """Провайдер создан в sync-контексте — клиент None до первого async вызова."""
        config = {"api_key": "test-key"}
        provider = GigaChatEmbeddingsProvider(config)
        assert provider._client is None

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_gigachat_get_client_recreates_if_closed(self, mock_client_class):
        """_get_client() создаёт новый клиент, если текущий is_closed=True."""
        config = {"api_key": "test-key"}
        provider = GigaChatEmbeddingsProvider(config)

        # Первый клиент — уже "закрытый"
        closed_client = AsyncMock()
        closed_client.is_closed = True
        provider._client = closed_client

        fresh_client = AsyncMock()
        fresh_client.is_closed = False
        mock_client_class.return_value = fresh_client

        result = await provider._get_client()
        mock_client_class.assert_called_once()
        assert result is fresh_client
        assert provider._client is fresh_client

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_gigachat_basic_auth_header(self, mock_client_class):
        """_get_access_token() использует Basic auth с base64-encoded api_key."""
        import base64

        config = {"api_key": "my-secret-key"}

        mock_response = Mock()
        mock_response.json.return_value = {"access_token": "token123"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = GigaChatEmbeddingsProvider(config)
        token = await provider._get_access_token()

        assert token == "token123"
        call_kwargs = mock_client.post.call_args
        auth_header = call_kwargs.kwargs["headers"]["Authorization"]
        expected_b64 = base64.b64encode("my-secret-key".encode()).decode()
        assert auth_header == f"Basic {expected_b64}"


class TestYandexEmbeddingsProvider:
    """Tests for YandexEmbeddingsProvider."""

    def test_missing_credentials_raise_error(self):
        """Test that missing credentials raise ValueError."""
        with pytest.raises(ValueError, match="YANDEX_EMBEDDINGS_KEY not set"):
            YandexEmbeddingsProvider({"folder_id": "test"})

        with pytest.raises(ValueError, match="YANDEX_FOLDER_ID not set"):
            YandexEmbeddingsProvider({"api_key": "test"})

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.yandex.httpx.AsyncClient")
    async def test_embed_documents(self, mock_client_class):
        """Test embedding documents via Yandex API."""
        config = {"api_key": "test-key", "folder_id": "test-folder"}

        # Mock API responses (Yandex API accepts 1 text at a time)
        mock_response1 = Mock()
        mock_response1.json.return_value = {"embedding": [0.1, 0.2]}
        mock_response1.raise_for_status = Mock()

        mock_response2 = Mock()
        mock_response2.json.return_value = {"embedding": [0.3, 0.4]}
        mock_response2.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post.side_effect = [mock_response1, mock_response2]
        mock_client_class.return_value = mock_client

        provider = YandexEmbeddingsProvider(config)

        texts = ["text1", "text2"]
        result = await provider.embed_documents(texts)

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]
        assert mock_client.post.call_count == 2

    def test_dimension(self):
        """Test dimension property."""
        config = {"api_key": "test-key", "folder_id": "test"}
        provider = YandexEmbeddingsProvider(config)
        assert provider.dimension == 256

    def test_yandex_provider_verify_ssl_false(self):
        """Test that verify_ssl_certs=False is stored in provider attribute."""
        config = {
            "api_key": "test_key",
            "folder_id": "test_folder",
            "verify_ssl_certs": False,
        }
        provider = YandexEmbeddingsProvider(config)

        assert provider.verify_ssl_certs is False

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.yandex.httpx.AsyncClient")
    async def test_yandex_provider_lazy_init_passes_verify_to_httpx(
        self, mock_async_client
    ):
        """Test lazy init: client not created in __init__, created on first _get_client() with correct params."""
        config = {
            "api_key": "test_key",
            "folder_id": "test_folder",
            "verify_ssl_certs": False,
        }

        # После __init__ клиент НЕ создан
        provider = YandexEmbeddingsProvider(config)
        mock_async_client.assert_not_called()
        assert provider._client is None

        # При первом _get_client() создаётся с правильными параметрами
        mock_client_instance = AsyncMock()
        mock_client_instance.is_closed = False
        mock_async_client.return_value = mock_client_instance

        client = await provider._get_client()
        mock_async_client.assert_called_once_with(timeout=10, verify=False)
        assert client is mock_client_instance

    def test_yandex_lazy_init_client_none_before_async(self):
        """Провайдер создан в sync-контексте — клиент None до первого async вызова."""
        config = {"api_key": "test-key", "folder_id": "test-folder"}
        provider = YandexEmbeddingsProvider(config)
        assert provider._client is None

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.yandex.httpx.AsyncClient")
    async def test_yandex_get_client_recreates_if_closed(self, mock_client_class):
        """_get_client() создаёт новый клиент, если текущий is_closed=True."""
        config = {"api_key": "test-key", "folder_id": "test-folder"}
        provider = YandexEmbeddingsProvider(config)

        closed_client = AsyncMock()
        closed_client.is_closed = True
        provider._client = closed_client

        fresh_client = AsyncMock()
        fresh_client.is_closed = False
        mock_client_class.return_value = fresh_client

        result = await provider._get_client()
        mock_client_class.assert_called_once()
        assert result is fresh_client
        assert provider._client is fresh_client


# === Additional edge case tests (Step 8) ===


class TestEmbeddingsEdgeCases:
    """Additional tests for edge cases and error scenarios."""

    @pytest.mark.asyncio
    @patch("langchain_community.embeddings.HuggingFaceEmbeddings")
    async def test_local_provider_batch_processing(self, mock_hf_embeddings):
        """Test LocalProvider handles large batches correctly."""
        config = {"model": "test-model", "batch_size": 32}

        mock_model = Mock()
        mock_model.client = Mock()
        mock_model.client.get_sentence_embedding_dimension.return_value = 2
        mock_model.embed_query.return_value = [0.1, 0.2]
        mock_hf_embeddings.return_value = mock_model

        provider = LocalEmbeddingsProvider(config)

        # Mock asyncio.to_thread to simulate embedding
        with patch(
            "telegram_rag_bot.embeddings.local.asyncio.to_thread"
        ) as mock_thread:
            # Single batch returns all embeddings
            mock_thread.return_value = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

            texts = ["text1", "text2", "text3"]
            result = await provider.embed_documents(texts)

            # Assert: 3 embeddings returned
            assert len(result) == 3
            mock_thread.assert_called_once()

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_gigachat_api_timeout(self, mock_client_class):
        """Test GigaChatProvider wraps timeout in RuntimeError."""
        import httpx

        config = {"api_key": "test-key"}

        # Mock timeout error
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post.side_effect = httpx.TimeoutException("Request timeout")
        mock_client_class.return_value = mock_client

        provider = GigaChatEmbeddingsProvider(config)
        provider._access_token = "test-token"

        # Act & Assert: Timeout wrapped in RuntimeError
        with pytest.raises(RuntimeError, match="GigaChat embeddings request failed"):
            await provider.embed_documents(["test"])

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.yandex.httpx.AsyncClient")
    async def test_yandex_batch_processing_sequential(self, mock_client_class):
        """Test YandexProvider processes texts sequentially (batch_size=1)."""
        config = {"api_key": "test-key", "folder_id": "test-folder"}

        # Mock multiple API calls
        mock_response1 = Mock()
        mock_response1.json.return_value = {"embedding": [0.1, 0.2]}
        mock_response1.raise_for_status = Mock()

        mock_response2 = Mock()
        mock_response2.json.return_value = {"embedding": [0.3, 0.4]}
        mock_response2.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post.side_effect = [mock_response1, mock_response2]
        mock_client_class.return_value = mock_client

        provider = YandexEmbeddingsProvider(config)

        # Act
        texts = ["text1", "text2"]
        result = await provider.embed_documents(texts)

        # Assert: 2 API calls made (sequential)
        assert mock_client.post.call_count == 2
        assert len(result) == 2

    def test_embeddings_dimension_check(self, embeddings_dimension):
        """Test providers return correct dimension values."""
        # Local provider
        local_config = {"model": "test-model"}
        with patch("langchain_community.embeddings.HuggingFaceEmbeddings") as mock_hf:
            mock_model = Mock()
            mock_model.client = Mock()
            mock_model.client.get_sentence_embedding_dimension.return_value = (
                embeddings_dimension
            )
            mock_hf.return_value = mock_model

            local_provider = LocalEmbeddingsProvider(local_config)
            assert local_provider.dimension == embeddings_dimension

        # GigaChat provider
        gigachat_config = {"api_key": "test-key"}
        gigachat_provider = GigaChatEmbeddingsProvider(gigachat_config)
        assert gigachat_provider.dimension == 1024

        # Yandex provider
        yandex_config = {"api_key": "test-key", "folder_id": "test-folder"}
        yandex_provider = YandexEmbeddingsProvider(yandex_config)
        assert yandex_provider.dimension == 256

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.embeddings.gigachat.httpx.AsyncClient")
    async def test_gigachat_empty_batch_error(self, mock_client_class):
        """Test GigaChatProvider handles empty batch gracefully."""
        config = {"api_key": "test-key"}

        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        provider = GigaChatEmbeddingsProvider(config)
        provider._access_token = "test-token"

        # Act & Assert: Empty list validation
        with pytest.raises(ValueError, match="Cannot embed empty list"):
            await provider.embed_documents([])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
