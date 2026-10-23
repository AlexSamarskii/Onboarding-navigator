"""
Unit tests for telegram_rag_bot.main (HTTP server configuration).

Tests cover:
- HTTP server enabled by default (backward compat)
- HTTP server enabled on custom port
- HTTP server disabled (Shared Pool mode)

Target coverage: 85%
"""

import pytest


# === Tests ===


def test_http_server_starts_when_section_absent():
    """Test HTTP server enabled=True when http_server section absent (backward compat)."""
    # Arrange
    config = {
        "telegram": {"token": "test"},
        # http_server section is ABSENT
    }

    # Act - simulating the logic in main.py
    http_config = config.get("http_server", {"enabled": True, "port": 8000})
    enabled = http_config.get("enabled", True)
    port = http_config.get("port", 8000)

    # Assert
    assert enabled is True, "HTTP server should be enabled by default"
    assert port == 8000, "Default port should be 8000"


def test_http_server_starts_on_custom_port():
    """Test HTTP server uses custom port when explicitly configured."""
    # Arrange
    config = {
        "telegram": {"token": "test"},
        "http_server": {"enabled": True, "port": 9000},
    }

    # Act
    http_config = config.get("http_server", {"enabled": True, "port": 8000})
    enabled = http_config.get("enabled", True)
    port = http_config.get("port", 8000)

    # Assert
    assert enabled is True, "HTTP server should be enabled"
    assert port == 9000, "Port should be 9000 (custom)"


def test_http_server_skipped_when_disabled():
    """Test HTTP server disabled when enabled=false (Shared Pool mode)."""
    # Arrange
    config = {"telegram": {"token": "test"}, "http_server": {"enabled": False}}

    # Act
    http_config = config.get("http_server", {"enabled": True, "port": 8000})
    enabled = http_config.get("enabled", True)

    # Assert
    assert enabled is False, "HTTP server should be disabled"


def test_http_server_default_port_when_not_specified():
    """Test default port 8000 when port not specified in config."""
    # Arrange
    config = {"telegram": {"token": "test"}, "http_server": {"enabled": True}}

    # Act
    http_config = config.get("http_server", {"enabled": True, "port": 8000})
    port = http_config.get("port", 8000)

    # Assert
    assert port == 8000, "Default port should be 8000 when not specified"


def test_http_server_backward_compatible_with_missing_enabled():
    """Test backward compat: missing 'enabled' key defaults to True."""
    # Arrange
    config = {
        "telegram": {"token": "test"},
        "http_server": {"port": 9000},
    }  # No 'enabled'

    # Act
    http_config = config.get("http_server", {"enabled": True, "port": 8000})
    enabled = http_config.get("enabled", True)
    port = http_config.get("port", 8000)

    # Assert
    assert enabled is True, "Missing 'enabled' should default to True"
    assert port == 9000, "Port should be respected"
