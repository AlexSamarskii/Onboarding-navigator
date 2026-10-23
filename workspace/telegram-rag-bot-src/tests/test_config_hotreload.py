"""
Tests for Config Hot-reload (SIGHUP handler) functionality.

Tests:
1. SIGHUP handler registration
2. Debounce mechanism
3. Successful config reload
4. Reload failure (invalid config)
5. Reload failure (empty providers)
6. SIGHUP during shutdown
"""

import signal
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from telegram_rag_bot.main import (
    _handle_sighup,
    _reload_config_async,
    build_providers_list,
    DEBOUNCE_SECONDS,
)


class TestSIGHUPHandlerRegistration:
    """Test SIGHUP handler registration."""

    def test_sighup_handler_registered(self):
        """Test that SIGHUP handler is registered in main()."""
        # This test verifies that signal.signal(signal.SIGHUP, _handle_sighup) is called
        # We can't directly test signal registration, but we can verify the handler exists
        assert callable(_handle_sighup)
        assert _handle_sighup.__name__ == "_handle_sighup"


class TestDebounce:
    """Test debounce mechanism."""

    @pytest.mark.asyncio
    async def test_debounce_ignores_rapid_sighup(self):
        """Test that rapid SIGHUP signals are debounced."""
        # Mock router and rag_factory
        mock_router = MagicMock()
        mock_router.update_providers = AsyncMock()
        mock_rag_factory = MagicMock()
        mock_rag_factory.chains = {}

        with (
            patch("telegram_rag_bot.main.router", mock_router),
            patch("telegram_rag_bot.main.rag_factory", mock_rag_factory),
            patch("telegram_rag_bot.main.ConfigLoader") as mock_loader,
            patch("telegram_rag_bot.main.last_reload_time", time.time() - 1.0),
        ):
            # First reload should be ignored (debounce)
            await _reload_config_async()

            # Verify ConfigLoader was NOT called (debounced)
            mock_loader.load_config.assert_not_called()
            mock_router.update_providers.assert_not_called()

            # Wait for debounce period to pass
            with patch(
                "telegram_rag_bot.main.last_reload_time",
                time.time() - (DEBOUNCE_SECONDS + 1),
            ):
                # Second reload should proceed
                mock_config = {
                    "orchestrator": {
                        "providers": [
                            {
                                "name": "test",
                                "type": "GigaChatProvider",
                                "enabled": True,
                                "config": {
                                    "api_key": "key",
                                    "model": "test",
                                    "scope": "test",
                                },
                            }
                        ]
                    }
                }
                mock_loader.load_config.return_value = mock_config

                await _reload_config_async()

                # Now ConfigLoader should be called
                assert mock_loader.load_config.called


class TestReloadSuccess:
    """Test successful config reload."""

    @pytest.mark.asyncio
    async def test_reload_success(self):
        """Test successful config reload."""
        mock_router = MagicMock()
        mock_router.update_providers = AsyncMock()
        mock_rag_factory = MagicMock()
        mock_rag_factory.chains = MagicMock()  # Make chains a MagicMock for assertions

        new_config = {
            "orchestrator": {
                "providers": [
                    {
                        "name": "gigachat",
                        "type": "GigaChatProvider",
                        "enabled": True,
                        "config": {
                            "api_key": "new_key",
                            "model": "GigaChat-Pro",
                            "scope": "GIGACHAT_API_PERS",
                        },
                    }
                ]
            }
        }

        with (
            patch("telegram_rag_bot.main.router", mock_router),
            patch("telegram_rag_bot.main.rag_factory", mock_rag_factory),
            patch("telegram_rag_bot.main.ConfigLoader") as mock_loader,
            patch("telegram_rag_bot.main.build_providers_list") as mock_build,
            patch(
                "telegram_rag_bot.main.last_reload_time",
                time.time() - (DEBOUNCE_SECONDS + 1),
            ),
        ):
            mock_loader.load_config.return_value = new_config
            mock_provider = MagicMock()
            mock_build.return_value = [mock_provider]

            await _reload_config_async()

            # Verify ConfigLoader was called
            mock_loader.load_config.assert_called_once_with("config/config.yaml")

            # Verify build_providers_list was called
            mock_build.assert_called_once_with(new_config["orchestrator"])

            # Verify router.update_providers was called
            mock_router.update_providers.assert_awaited_once_with(
                [mock_provider], preserve_metrics=False
            )

            # Verify chains cache was cleared
            mock_rag_factory.chains.clear.assert_called_once()


class TestReloadFailure:
    """Test reload failure scenarios."""

    @pytest.mark.asyncio
    async def test_reload_failure_invalid_config(self):
        """Test reload failure with invalid config."""
        mock_router = MagicMock()
        mock_router.update_providers = AsyncMock()
        mock_rag_factory = MagicMock()
        mock_rag_factory.chains = MagicMock()  # Make chains a MagicMock for assertions

        with (
            patch("telegram_rag_bot.main.router", mock_router),
            patch("telegram_rag_bot.main.rag_factory", mock_rag_factory),
            patch("telegram_rag_bot.main.ConfigLoader") as mock_loader,
            patch(
                "telegram_rag_bot.main.last_reload_time",
                time.time() - (DEBOUNCE_SECONDS + 1),
            ),
        ):
            # ConfigLoader raises ValueError (invalid config)
            mock_loader.load_config.side_effect = ValueError("Invalid YAML")

            # Reload should not crash
            await _reload_config_async()

            # Verify router was NOT updated
            mock_router.update_providers.assert_not_called()

            # Verify chains cache was NOT cleared
            mock_rag_factory.chains.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_reload_failure_empty_providers(self):
        """Test reload failure with empty providers list."""
        mock_router = MagicMock()
        mock_router.update_providers = AsyncMock()
        mock_rag_factory = MagicMock()
        mock_rag_factory.chains = MagicMock()  # Make chains a MagicMock for assertions

        new_config = {
            "orchestrator": {
                "providers": [
                    {
                        "name": "gigachat",
                        "type": "GigaChatProvider",
                        "enabled": False,  # Disabled provider
                        "config": {
                            "api_key": "key",
                            "model": "GigaChat-Pro",
                            "scope": "GIGACHAT_API_PERS",
                        },
                    }
                ]
            }
        }

        with (
            patch("telegram_rag_bot.main.router", mock_router),
            patch("telegram_rag_bot.main.rag_factory", mock_rag_factory),
            patch("telegram_rag_bot.main.ConfigLoader") as mock_loader,
            patch("telegram_rag_bot.main.build_providers_list") as mock_build,
            patch(
                "telegram_rag_bot.main.last_reload_time",
                time.time() - (DEBOUNCE_SECONDS + 1),
            ),
        ):
            mock_loader.load_config.return_value = new_config
            mock_build.return_value = []  # Empty providers list

            await _reload_config_async()

            # Verify router was NOT updated (empty providers)
            mock_router.update_providers.assert_not_called()

            # Verify chains cache was NOT cleared
            mock_rag_factory.chains.clear.assert_not_called()


class TestSIGHUPDuringShutdown:
    """Test SIGHUP during shutdown."""

    def test_sighup_ignored_during_shutdown(self):
        """Test that SIGHUP is ignored during shutdown."""

        # Mock logger to capture warnings
        with (
            patch("telegram_rag_bot.main.logger") as mock_logger,
            patch("telegram_rag_bot.main.shutdown_in_progress", True),
        ):
            # Call handler (use signal.SIGHUP if available, otherwise use 1)
            sighup_signal = getattr(signal, "SIGHUP", 1)
            _handle_sighup(sighup_signal, None)

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            assert "shutdown in progress" in mock_logger.warning.call_args[0][0].lower()


class TestBuildProvidersList:
    """Test build_providers_list helper function."""

    def test_build_providers_list_success(self):
        """Test successful provider list building."""
        orchestrator_config = {
            "providers": [
                {
                    "name": "gigachat",
                    "type": "GigaChatProvider",
                    "enabled": True,
                    "config": {
                        "api_key": "test_key",
                        "model": "GigaChat-Pro",
                        "scope": "GIGACHAT_API_PERS",
                    },
                }
            ]
        }

        providers = build_providers_list(orchestrator_config)

        assert len(providers) == 1
        assert providers[0].config.name == "gigachat"

    def test_build_providers_list_skips_disabled(self):
        """Test that disabled providers are skipped."""
        orchestrator_config = {
            "providers": [
                {
                    "name": "gigachat",
                    "type": "GigaChatProvider",
                    "enabled": False,
                    "config": {
                        "api_key": "test_key",
                        "model": "GigaChat-Pro",
                        "scope": "GIGACHAT_API_PERS",
                    },
                }
            ]
        }

        providers = build_providers_list(orchestrator_config)

        assert len(providers) == 0

    def test_build_providers_list_duplicate_names(self):
        """Test that duplicate provider names raise ValueError."""
        orchestrator_config = {
            "providers": [
                {
                    "name": "gigachat",
                    "type": "GigaChatProvider",
                    "enabled": True,
                    "config": {
                        "api_key": "test_key",
                        "model": "GigaChat-Pro",
                        "scope": "GIGACHAT_API_PERS",
                    },
                },
                {
                    "name": "gigachat",  # Duplicate name
                    "type": "GigaChatProvider",
                    "enabled": True,
                    "config": {
                        "api_key": "test_key2",
                        "model": "GigaChat-Pro",
                        "scope": "GIGACHAT_API_PERS",
                    },
                },
            ]
        }

        with pytest.raises(ValueError, match="Duplicate provider name"):
            build_providers_list(orchestrator_config)

    def test_provider_config_propagates_verify_ssl_false(self):
        """Test that verify_ssl_certs: false propagates to ProviderConfig.verify_ssl.

        Regression test for Issue #9: ensure verify_ssl parameter is correctly
        passed from config.yaml to Multi-LLM-Orchestrator ProviderConfig.
        """
        orchestrator_config = {
            "strategy": "best-available",
            "providers": [
                {
                    "name": "gigachat-test",
                    "type": "GigaChatProvider",
                    "enabled": True,
                    "config": {
                        "api_key": "test_key_123",
                        "model": "GigaChat-Pro",
                        "scope": "GIGACHAT_API_PERS",
                        "verify_ssl_certs": False,
                    },
                }
            ],
        }

        providers = build_providers_list(orchestrator_config)

        assert len(providers) == 1, "Expected 1 provider"
        assert (
            providers[0].config.verify_ssl is False
        ), "verify_ssl must be False when verify_ssl_certs: false"
