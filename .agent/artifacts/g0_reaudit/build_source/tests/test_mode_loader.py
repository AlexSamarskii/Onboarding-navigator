"""
Unit tests for telegram_rag_bot.mode_loader.ModeLoader.

Tests cover:
- load_all_modes: Loading all modes from directory
- _load_mode: Loading single mode configuration
- get_mode: Getting mode by name
- Error handling: Missing files, invalid YAML, disabled modes
"""

import pytest
from pathlib import Path

from telegram_rag_bot.mode_loader import ModeLoader


@pytest.fixture
def test_modes_dir(tmp_path):
    """Create temporary modes directory with test files."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()

    # Create test_mode
    test_mode_dir = modes_dir / "test_mode"
    test_mode_dir.mkdir()

    # mode.yaml
    mode_yaml = test_mode_dir / "mode.yaml"
    mode_yaml.write_text(
        """
name: test_mode
display_name: "Test Mode"
description: "Test mode for unit tests"
enabled: true
ui:
  icon: "🧪"
  category: "test"
  priority: 1
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
  examples: "examples.yaml"
timeout_seconds: 30
""",
        encoding="utf-8",
    )

    # system_prompt.md
    (test_mode_dir / "system_prompt.md").write_text(
        "You are a test assistant.\nThis is a test system prompt.",
        encoding="utf-8",
    )

    # faq.md
    (test_mode_dir / "faq.md").write_text(
        "# Test FAQ\n\n## Test Section\n\n### Test Question?\n\nTest answer.",
        encoding="utf-8",
    )

    # examples.yaml
    (test_mode_dir / "examples.yaml").write_text(
        "- question: 'Test question 1'\n  answer: 'Test answer 1'",
        encoding="utf-8",
    )

    # Create disabled_mode
    disabled_mode_dir = modes_dir / "disabled_mode"
    disabled_mode_dir.mkdir()
    (disabled_mode_dir / "mode.yaml").write_text(
        """
name: disabled_mode
display_name: "Disabled Mode"
enabled: false
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )
    (disabled_mode_dir / "system_prompt.md").write_text(
        "Disabled mode prompt", encoding="utf-8"
    )
    (disabled_mode_dir / "faq.md").write_text("# Disabled FAQ", encoding="utf-8")

    return modes_dir


@pytest.fixture
def broken_mode_dir(tmp_path):
    """Create mode directory without required files."""
    broken_dir = tmp_path / "broken_mode"
    broken_dir.mkdir()
    (broken_dir / "mode.yaml").write_text(
        """
name: broken_mode
display_name: "Broken Mode"
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )
    # Missing system_prompt.md and faq.md
    return broken_dir


def test_load_all_modes(test_modes_dir):
    """Test loading all modes from directory."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    assert len(modes) == 1  # Only test_mode (disabled_mode is skipped)
    assert "test_mode" in modes
    assert "disabled_mode" not in modes


def test_mode_structure(test_modes_dir):
    """Test that loaded mode has required fields."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]

    # Required fields
    assert "name" in mode
    assert "display_name" in mode
    assert "system_prompt" in mode
    assert "faq_file" in mode

    # Check types
    assert isinstance(mode["system_prompt"], str)
    assert isinstance(mode["faq_file"], str)
    assert mode["name"] == "test_mode"
    assert mode["display_name"] == "Test Mode"


def test_system_prompt_loaded(test_modes_dir):
    """Test that system_prompt is loaded as string."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]
    system_prompt = mode["system_prompt"]

    assert isinstance(system_prompt, str)
    assert len(system_prompt) > 0
    assert "test assistant" in system_prompt.lower()


def test_faq_file_path(test_modes_dir):
    """Test that faq_file is absolute path."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]
    faq_file = mode["faq_file"]

    assert isinstance(faq_file, str)
    assert Path(faq_file).is_absolute()
    assert Path(faq_file).exists()


def test_missing_system_prompt(broken_mode_dir):
    """Test that missing system_prompt.md raises FileNotFoundError."""
    loader = ModeLoader(broken_mode_dir.parent)

    with pytest.raises(FileNotFoundError, match="Missing required file"):
        loader._load_mode(broken_mode_dir)


def test_missing_faq(tmp_path):
    """Test that missing faq.md raises FileNotFoundError."""
    mode_dir = tmp_path / "test_mode"
    mode_dir.mkdir()
    (mode_dir / "mode.yaml").write_text(
        """
name: test_mode
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )
    (mode_dir / "system_prompt.md").write_text("Test prompt", encoding="utf-8")
    # Missing faq.md

    loader = ModeLoader(tmp_path)

    with pytest.raises(FileNotFoundError, match="Missing required file"):
        loader._load_mode(mode_dir)


def test_disabled_mode(test_modes_dir):
    """Test that disabled mode is not loaded."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    assert "disabled_mode" not in modes
    assert "test_mode" in modes


def test_optional_examples(test_modes_dir):
    """Test that examples.yaml is optional."""
    loader = ModeLoader(test_modes_dir)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]

    # examples.yaml should be loaded if exists
    assert "few_shot_examples" in mode
    assert isinstance(mode["few_shot_examples"], list)
    assert len(mode["few_shot_examples"]) > 0


def test_optional_examples_missing(tmp_path):
    """Test mode without examples.yaml loads successfully."""
    mode_dir = tmp_path / "test_mode"
    mode_dir.mkdir()
    (mode_dir / "mode.yaml").write_text(
        """
name: test_mode
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )
    (mode_dir / "system_prompt.md").write_text("Test prompt", encoding="utf-8")
    (mode_dir / "faq.md").write_text("# Test FAQ", encoding="utf-8")
    # No examples.yaml

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]
    # few_shot_examples should not be present if examples.yaml doesn't exist
    assert "few_shot_examples" not in mode


def test_invalid_yaml(tmp_path):
    """Test that invalid YAML in mode.yaml is handled gracefully."""
    mode_dir = tmp_path / "invalid_mode"
    mode_dir.mkdir()
    (mode_dir / "mode.yaml").write_text("invalid: yaml: syntax: {", encoding="utf-8")

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()

    # Invalid mode should be skipped
    assert "invalid_mode" not in modes
    assert len(modes) == 0


def test_get_mode(test_modes_dir):
    """Test getting mode by name."""
    loader = ModeLoader(test_modes_dir)
    mode = loader.get_mode("test_mode")

    assert mode is not None
    assert mode["name"] == "test_mode"
    assert mode["display_name"] == "Test Mode"

    # Non-existent mode
    assert loader.get_mode("nonexistent_mode") is None


def test_mode_without_mode_yaml(tmp_path):
    """Test that directory without mode.yaml is skipped."""
    mode_dir = tmp_path / "no_yaml_mode"
    mode_dir.mkdir()
    # No mode.yaml

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()

    assert "no_yaml_mode" not in modes
    assert len(modes) == 0


def test_mode_directory_not_exists():
    """Test that ModeLoader raises FileNotFoundError for non-existent directory."""
    with pytest.raises(FileNotFoundError):
        ModeLoader(Path("/nonexistent/directory"))


def test_empty_modes_directory(tmp_path):
    """Test loading from empty modes directory."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()

    loader = ModeLoader(modes_dir)
    modes = loader.load_all_modes()

    assert len(modes) == 0
    assert isinstance(modes, dict)


def test_mode_loader_parses_greeting(tmp_path):
    """Test that greeting is extracted from system_prompt.md."""
    mode_dir = tmp_path / "test_mode"
    mode_dir.mkdir()

    # mode.yaml
    (mode_dir / "mode.yaml").write_text(
        """
name: test_mode
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )

    # system_prompt.md с greeting
    (mode_dir / "system_prompt.md").write_text(
        """# ПРИВЕТСТВИЕ

Привет, я ваш помогайка, шеф!

Используйте это приветствие, если пользователь спрашивает 'Кто ты?' или 'Привет'.

---

# РОЛЬ И ПОВЕДЕНИЕ

Ты дружелюбный AI-помощник...""",
        encoding="utf-8",
    )

    # faq.md
    (mode_dir / "faq.md").write_text("# Test FAQ", encoding="utf-8")

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]
    assert mode["greeting"] == "Привет, я ваш помогайка, шеф!"
    # system_prompt should contain content after "# РОЛЬ И ПОВЕДЕНИЕ" (without the header itself)
    assert "Ты дружелюбный AI-помощник" in mode["system_prompt"]
    assert "# ПРИВЕТСТВИЕ" not in mode["system_prompt"]
    assert "# РОЛЬ И ПОВЕДЕНИЕ" not in mode["system_prompt"]  # Header removed


def test_mode_loader_no_greeting(tmp_path):
    """Test that mode without greeting works (backward compat)."""
    mode_dir = tmp_path / "test_mode"
    mode_dir.mkdir()

    (mode_dir / "mode.yaml").write_text(
        """
name: test_mode
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )

    # system_prompt.md БЕЗ greeting
    (mode_dir / "system_prompt.md").write_text(
        "Ты дружелюбный AI-помощник.",
        encoding="utf-8",
    )

    (mode_dir / "faq.md").write_text("# Test FAQ", encoding="utf-8")

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()

    mode = modes["test_mode"]
    assert "greeting" not in mode  # Или mode.get("greeting") is None
    assert mode["system_prompt"] == "Ты дружелюбный AI-помощник."


def test_mode_loader_preserves_multiline_greeting_newlines(tmp_path):
    """Greeting keeps \\n between non-empty lines and has no outer empty lines."""
    mode_dir = tmp_path / "test_mode"
    mode_dir.mkdir()

    (mode_dir / "mode.yaml").write_text(
        """
name: test_mode
enabled: true
files:
  system_prompt: "system_prompt.md"
  faq: "faq.md"
""",
        encoding="utf-8",
    )

    (mode_dir / "system_prompt.md").write_text(
        """# ПРИВЕТСТВИЕ

Первая строка приветствия.

Вторая строка приветствия.
Третья строка приветствия.

Используйте это приветствие, если пользователь спрашивает 'Кто ты?' или 'Привет'.

---

# РОЛЬ И ПОВЕДЕНИЕ

Ты дружелюбный AI-помощник...""",
        encoding="utf-8",
    )

    (mode_dir / "faq.md").write_text("# Test FAQ", encoding="utf-8")

    loader = ModeLoader(tmp_path)
    modes = loader.load_all_modes()
    greeting = modes["test_mode"]["greeting"]

    assert greeting == (
        "Первая строка приветствия.\n"
        "Вторая строка приветствия.\n"
        "Третья строка приветствия."
    )
    assert not greeting.startswith("\n")
    assert not greeting.endswith("\n")
