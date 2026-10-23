"""
Unit tests for telegram_rag_bot.config_loader.ConfigLoader.

Tests cover:
- load_config: YAML loading and validation (4 tests)
- _substitute_env_vars: Environment variable substitution (6 tests)
- _validate_config: Config validation (2 tests)

Target coverage: 95%
"""

import pytest
import os
import yaml
from pathlib import Path
from unittest.mock import patch, mock_open

from telegram_rag_bot.config_loader import ConfigLoader


# === load_config tests ===


def test_load_config_valid_yaml(tmp_path):
    """Test load_config loads valid YAML successfully."""
    # Arrange: Create config directory structure (как в реальном проекте)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create modes directory (относительно config/)
    modes_dir = config_dir / "modes"
    modes_dir.mkdir()

    # Create it_support mode
    it_support_dir = modes_dir / "it_support"
    it_support_dir.mkdir()

    # mode.yaml
    (it_support_dir / "mode.yaml").write_text(
        """
name: it_support
display_name: "IT Support"
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
timeout_seconds: 30
""",
        encoding="utf-8",
    )

    # system_prompt.md
    (it_support_dir / "system_prompt.md").write_text(
        "Test system prompt", encoding="utf-8"
    )

    # faq.md
    (it_support_dir / "faq.md").write_text("# Test FAQ", encoding="utf-8")

    # Create valid config file (в config/ директории, как в реальном проекте)
    config_file = config_dir / "config.yaml"
    config_data = {
        "telegram": {"token": "test_token", "admin_ids": [123]},
        "orchestrator": {"default_model": "gigachat"},
        "modes": {
            "directory": "modes"
        },  # New format (relative to config.yaml location)
    }

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    # Mock env vars
    with patch.dict(
        os.environ,
        {
            "TELEGRAM_TOKEN": "actual_token",
            "GIGACHAT_KEY": "test_key",
            "YANDEX_API_KEY": "test_key",
            "YANDEX_FOLDER_ID": "test_folder",
        },
    ):
        # Act
        config = ConfigLoader.load_config(str(config_file))

        # Assert: modes loaded from bundles
        assert "telegram" in config
        assert "orchestrator" in config
        assert "modes" in config
        assert "it_support" in config["modes"]
        assert config["modes"]["it_support"]["name"] == "it_support"
        assert "system_prompt" in config["modes"]["it_support"]
        assert "faq_file" in config["modes"]["it_support"]


def test_load_config_file_not_found():
    """Test load_config raises FileNotFoundError for missing file."""
    # Act & Assert
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        ConfigLoader.load_config("nonexistent.yaml")


def test_load_config_invalid_yaml(tmp_path):
    """Test load_config handles invalid YAML syntax."""
    # Arrange: Create file with invalid YAML
    config_file = tmp_path / "invalid.yaml"
    with open(config_file, "w") as f:
        f.write("invalid: yaml: syntax: {")

    # Act & Assert
    with pytest.raises(yaml.YAMLError):
        ConfigLoader.load_config(str(config_file))


def test_load_config_empty_file(tmp_path):
    """Test load_config raises ValueError for empty file."""
    # Arrange: Create empty file
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("")

    # Act & Assert
    with pytest.raises(ValueError, match="Config file is empty"):
        ConfigLoader.load_config(str(config_file))


# === _substitute_env_vars tests ===


def test_substitute_env_vars_simple():
    """Test simple environment variable substitution."""
    # Arrange
    config = {"token": "${TEST_VAR}"}

    with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["token"] == "test_value"


def test_substitute_env_vars_nested():
    """Test nested environment variable substitution."""
    # Arrange
    config = {"path": "${VAR1}/${VAR2}/file.txt"}

    with patch.dict(os.environ, {"VAR1": "home", "VAR2": "user"}):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["path"] == "home/user/file.txt"


def test_substitute_env_vars_missing_required():
    """Test missing required env var raises ValueError."""
    # Arrange: TELEGRAM_TOKEN is required
    config = {"token": "${TELEGRAM_TOKEN}"}

    with patch.dict(os.environ, {}, clear=True):
        # Act & Assert
        with pytest.raises(
            ValueError, match="Missing required environment variable: TELEGRAM_TOKEN"
        ):
            ConfigLoader._substitute_env_vars(config)


def test_substitute_env_vars_missing_optional():
    """Test missing optional env var returns empty string."""
    # Arrange: REDIS_URL is optional
    config = {"redis_url": "${REDIS_URL}"}

    with patch.dict(os.environ, {}, clear=True):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["redis_url"] == ""


def test_substitute_env_vars_no_placeholders():
    """Test config without placeholders remains unchanged."""
    # Arrange
    config = {"static_value": "no_placeholder"}

    # Act
    result = ConfigLoader._substitute_env_vars(config)

    # Assert
    assert result["static_value"] == "no_placeholder"


def test_substitute_env_vars_multiple_vars():
    """Test multiple variables in one string."""
    # Arrange
    config = {"url": "https://${HOST}:${PORT}/api"}

    with patch.dict(os.environ, {"HOST": "localhost", "PORT": "8000"}):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["url"] == "https://localhost:8000/api"


def test_substitute_env_vars_recursive_dict():
    """Test substitution works recursively in nested dicts."""
    # Arrange
    config = {"level1": {"level2": {"token": "${TEST_TOKEN}"}}}

    with patch.dict(os.environ, {"TEST_TOKEN": "secret"}):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["level1"]["level2"]["token"] == "secret"


def test_substitute_env_vars_list():
    """Test substitution works in lists."""
    # Arrange
    config = {"items": ["${VAR1}", "${VAR2}", "static"]}

    with patch.dict(os.environ, {"VAR1": "value1", "VAR2": "value2"}):
        # Act
        result = ConfigLoader._substitute_env_vars(config)

        # Assert
        assert result["items"] == ["value1", "value2", "static"]


# === _validate_config tests ===


def test_validate_config_missing_telegram_section():
    """Test validation fails for missing telegram section."""
    # Arrange
    config = {"orchestrator": {}, "modes": {"directory": "config/modes"}}

    # Act & Assert
    with pytest.raises(
        ValueError, match="config.yaml missing required section: telegram"
    ):
        ConfigLoader._validate_config(config)


def test_validate_config_all_sections_present():
    """Test validation passes with all required sections."""
    # Arrange
    config = {
        "telegram": {},
        "orchestrator": {},
        "modes": {"directory": "config/modes"},  # New format
    }

    # Act (should not raise)
    ConfigLoader._validate_config(config)

    # Assert: No exception raised
