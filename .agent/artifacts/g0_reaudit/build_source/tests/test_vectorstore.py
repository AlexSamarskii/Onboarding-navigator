"""
Unit tests for vector store providers.

Tests LocalFAISSProvider, OpenSearchProvider, and VectorStoreFactory.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path

TEST_DIM = 1024
from telegram_rag_bot.vectorstore.factory import VectorStoreFactory
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider
from telegram_rag_bot.vectorstore.cloud_opensearch import OpenSearchProvider


class TestVectorStoreFactory:
    """Tests for VectorStoreFactory."""

    def test_create_faiss_provider(self):
        """Test creating LocalFAISSProvider."""
        config = {"type": "faiss", "faiss": {"indices_dir": ".faiss_indices"}}
        mock_embeddings = Mock()

        provider = VectorStoreFactory.create(config, mock_embeddings)
        assert isinstance(provider, LocalFAISSProvider)

    def test_create_opensearch_provider(self):
        """Test creating OpenSearchProvider."""
        config = {
            "type": "opensearch",
            "opensearch": {
                "host": "localhost",
                "port": 9200,
                "index_name": "test-index",
            },
        }
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        provider = VectorStoreFactory.create(config, mock_embeddings)
        assert isinstance(provider, OpenSearchProvider)

    def test_unknown_type_raises_error(self):
        """Test that unknown provider type raises ValueError."""
        config = {"type": "unknown"}
        mock_embeddings = Mock()

        with pytest.raises(ValueError, match="Unknown vector store provider type"):
            VectorStoreFactory.create(config, mock_embeddings)


class TestLocalFAISSProvider:
    """Tests for LocalFAISSProvider."""

    def test_initialization(self):
        """Test provider initialization."""
        config = {"indices_dir": ".faiss_indices"}
        mock_embeddings = Mock()

        provider = LocalFAISSProvider(config, mock_embeddings)
        assert provider.indices_dir == Path(".faiss_indices")

    @patch("telegram_rag_bot.vectorstore.local_faiss.FAISS.load_local")
    @patch("telegram_rag_bot.vectorstore.local_faiss.Path.exists")
    def test_load_index_success(self, mock_exists, mock_load):
        """Test loading FAISS index."""
        config = {"indices_dir": ".faiss_indices"}
        mock_embeddings = Mock()
        mock_embeddings.model = Mock()
        mock_embeddings.dimension = TEST_DIM

        # Mock path exists
        mock_exists.return_value = True

        mock_vectorstore = Mock()
        mock_vectorstore.index = Mock()
        mock_vectorstore.index.d = TEST_DIM
        mock_vectorstore.index.ntotal = 5
        mock_load.return_value = mock_vectorstore

        provider = LocalFAISSProvider(config, mock_embeddings)
        result = provider.load_index("it_support")

        assert result == mock_vectorstore
        mock_load.assert_called_once()

    def test_load_index_not_found(self):
        """Test loading non-existent index raises FileNotFoundError."""
        config = {"indices_dir": ".faiss_indices"}
        mock_embeddings = Mock()
        mock_embeddings.model = Mock()
        mock_embeddings.dimension = TEST_DIM

        provider = LocalFAISSProvider(config, mock_embeddings)

        with pytest.raises(FileNotFoundError, match="FAISS index not found"):
            provider.load_index("nonexistent_mode")

    @patch("telegram_rag_bot.vectorstore.local_faiss.FAISS.load_local")
    @patch("telegram_rag_bot.vectorstore.local_faiss.Path.exists")
    def test_load_index_dimension_mismatch(self, mock_exists, mock_load):
        """Test dimension mismatch raises ValueError with guidance."""
        config = {"indices_dir": ".faiss_indices"}
        mock_embeddings = Mock()
        mock_embeddings.model = Mock()
        mock_embeddings.dimension = TEST_DIM

        mock_exists.return_value = True
        mock_vectorstore = Mock()
        mock_vectorstore.index = Mock()
        mock_vectorstore.index.d = TEST_DIM - 1
        mock_vectorstore.index.ntotal = 3
        mock_load.return_value = mock_vectorstore

        provider = LocalFAISSProvider(config, mock_embeddings)

        with pytest.raises(ValueError, match="dimension mismatch"):
            provider.load_index("it_support")

    @pytest.mark.asyncio
    async def test_delete_index(self):
        """Test deleting FAISS index."""
        config = {"indices_dir": ".faiss_indices"}
        mock_embeddings = Mock()

        provider = LocalFAISSProvider(config, mock_embeddings)

        # Mock directory existence
        with patch(
            "telegram_rag_bot.vectorstore.local_faiss.Path.exists", return_value=True
        ):
            with patch(
                "telegram_rag_bot.vectorstore.local_faiss.asyncio.to_thread"
            ) as mock_thread:
                await provider.delete_index("it_support")
                mock_thread.assert_called_once()


class TestOpenSearchProvider:
    """Tests for OpenSearchProvider."""

    def test_missing_host_raises_error(self):
        """Test that missing host raises ValueError."""
        config = {}
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        with pytest.raises(ValueError, match="OPENSEARCH_HOST not set"):
            OpenSearchProvider(config, mock_embeddings)

    @patch("telegram_rag_bot.vectorstore.cloud_opensearch.AsyncOpenSearch")
    def test_initialization(self, mock_client_class):
        """Test provider initialization."""
        config = {"host": "localhost", "port": 9200, "index_name": "test-index"}
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        provider = OpenSearchProvider(config, mock_embeddings)
        assert provider.base_index_name == "test-index"
        assert provider.dimension == TEST_DIM

    def test_get_index_name(self):
        """Test index name generation."""
        config = {"host": "localhost", "index_name": "telegram-bot-faq"}
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        with patch("telegram_rag_bot.vectorstore.cloud_opensearch.AsyncOpenSearch"):
            provider = OpenSearchProvider(config, mock_embeddings)
            index_name = provider._get_index_name("it_support")
            assert index_name == "telegram-bot-faq-it_support"

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.vectorstore.cloud_opensearch.AsyncOpenSearch")
    async def test_add_documents(self, mock_client_class):
        """Test adding documents to OpenSearch."""
        config = {"host": "localhost", "index_name": "test-index"}
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        # Mock client
        mock_client = AsyncMock()
        mock_client.indices.exists.return_value = False
        mock_client.indices.create.return_value = None
        mock_client.bulk.return_value = {"errors": False}
        mock_client_class.return_value = mock_client

        provider = OpenSearchProvider(config, mock_embeddings)

        texts = ["text1", "text2"]
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        metadatas = [{"source": "faq.md"}, {"source": "faq.md"}]

        await provider.add_documents(texts, embeddings, metadatas, mode="it_support")

        # Verify bulk insert was called
        mock_client.bulk.assert_called_once()

    @pytest.mark.asyncio
    @patch("telegram_rag_bot.vectorstore.cloud_opensearch.AsyncOpenSearch")
    async def test_similarity_search(self, mock_client_class):
        """Test similarity search in OpenSearch."""
        config = {"host": "localhost", "index_name": "test-index"}
        mock_embeddings = Mock()
        mock_embeddings.dimension = TEST_DIM

        # Mock search response
        mock_response = {
            "hits": {
                "hits": [
                    {"_source": {"text": "result1", "metadata": {"source": "faq.md"}}},
                    {"_source": {"text": "result2", "metadata": {"source": "faq.md"}}},
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.search.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OpenSearchProvider(config, mock_embeddings)

        query_embedding = [0.5] * TEST_DIM
        results = await provider.similarity_search(
            query_embedding, mode="it_support", k=3
        )

        assert len(results) == 2
        assert results[0]["text"] == "result1"
        assert results[1]["text"] == "result2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
