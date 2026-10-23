"""
Mode loader for Self-Contained Bundle Architecture.

This module provides ModeLoader class for loading mode configurations
from directory-based bundles. Each mode bundle contains:
- mode.yaml: configuration
- system_prompt.md: LLM system prompt
- faq.md: FAQ content for RAG
- examples.yaml: few-shot examples (optional)
"""

import logging
import re
from pathlib import PureWindowsPath
from telegram_rag_bot.i18n import t
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

logger = logging.getLogger(__name__)


class ModeValidationError(ValueError):
    """An enabled mandatory bundle cannot be loaded safely."""


MANDATORY_MODES = frozenset({"it_support", "benefits", "learning", "culture", "onboarding_plan"})


def _bundle_path(bundle: Path, value: str) -> Path:
    """Resolve only bundle-contained relative paths, without opening them."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModeValidationError("bundle path must be a nonempty relative string")
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts:
        raise ModeValidationError("bundle path must not escape its directory")
    if any(part in {".idea", ".env"} or part.startswith(".env.") for part in path.parts):
        raise ModeValidationError("restricted bundle path")
    target = (bundle / path).resolve()
    if not target.is_relative_to(bundle.resolve()):
        raise ModeValidationError("bundle symlink escapes its directory")
    if any(part in {".idea", ".env"} or part.startswith(".env.") for part in target.parts):
        raise ModeValidationError("restricted bundle target")
    return target


def _marker(key: str, fallback: str, content: str) -> str:
    try:
        translated = t(key)
        return translated if translated and translated in content else fallback
    except (RuntimeError, KeyError, ValueError):
        return fallback


class ModeLoader:
    """Load mode configurations from Self-Contained Bundles.

    Each mode is stored in a directory with the following structure:
    config/modes/
    └── mode_name/
        ├── mode.yaml          (required)
        ├── system_prompt.md   (required)
        ├── faq.md             (required)
        └── examples.yaml      (optional)

    Attributes:
        modes_dir: Path to directory containing mode bundles
    """

    def __init__(self, modes_dir: Path) -> None:
        """Initialize ModeLoader.

        Args:
            modes_dir: Path to directory containing mode bundles

        Raises:
            FileNotFoundError: If modes_dir doesn't exist
        """
        self.modes_dir = Path(modes_dir)
        if not self.modes_dir.exists():
            raise FileNotFoundError(f"Modes directory not found: {self.modes_dir}")
        logger.info(f"Initialized ModeLoader with directory: {self.modes_dir}")

    def load_all_modes(self) -> Dict[str, Dict[str, Any]]:
        """Load all modes from directory.

        Iterates through all subdirectories in modes_dir and loads
        mode configurations. Skips directories without mode.yaml
        or with disabled modes.

        Returns:
            Dictionary mapping mode names to mode configurations

        Example:
            >>> loader = ModeLoader(Path("config/modes"))
            >>> modes = loader.load_all_modes()
            >>> print(modes["it_support"]["display_name"])
            '🛠️ IT Support'
        """
        modes: Dict[str, Dict[str, Any]] = {}

        if not self.modes_dir.exists():
            logger.warning(f"Modes directory does not exist: {self.modes_dir}")
            return modes

        # Iterate through all subdirectories
        for mode_dir in self.modes_dir.iterdir():
            if not mode_dir.is_dir():
                continue  # Skip files

            try:
                mode = self._load_mode(mode_dir)
                if mode is None:
                    if mode_dir.name in MANDATORY_MODES:
                        raise ModeValidationError("mandatory mode configuration missing")
                    continue

                # Disabled entries are intentionally skipped before validating identity.
                if mode.get("enabled", True) is False:
                    continue
                mode_name = mode.get("name")
                if not mode_name:
                    if mode_dir.name in MANDATORY_MODES:
                        raise ModeValidationError("mandatory mode name is required")
                    logger.warning("Optional mode has no name, skipping")
                    continue

                # Check if mode is enabled
                if not mode.get("enabled", True):
                    logger.info(f"Skipped disabled mode: {mode_name}")
                    continue

                modes[mode_name] = mode
                logger.info("Loaded mode: %s", mode_name)

            except Exception as exc:
                if mode_dir.name in MANDATORY_MODES or getattr(exc, "mandatory", False):
                    raise ModeValidationError("mandatory mode failed validation") from exc
                logger.error("Optional mode failed validation")
                continue

        logger.info(f"✅ Loaded {len(modes)} mode(s) from {self.modes_dir}")
        return modes

    def _load_mode(self, mode_dir: Path) -> Optional[Dict[str, Any]]:
        # Track parsed mandatory identity even when the directory is renamed.
        identity = None
        path = _bundle_path(mode_dir, "mode.yaml")
        if path.is_file():
            try:
                identity = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                pass
        try:
            return self._load_mode_content(mode_dir)
        except Exception as exc:
            if isinstance(identity, dict) and identity.get("name") in MANDATORY_MODES:
                exc.mandatory = identity.get("enabled", True) is not False
            raise

    def _load_mode_content(self, mode_dir: Path) -> Optional[Dict[str, Any]]:
        """Load mode configuration from directory.

        Loads mode.yaml, system_prompt.md, faq.md, and optionally examples.yaml.
        Validates that required files exist.

        Args:
            mode_dir: Path to mode directory containing mode.yaml

        Returns:
            Dictionary with mode configuration or None if mode disabled/error

        Raises:
            FileNotFoundError: If system_prompt.md or faq.md missing
            yaml.YAMLError: If mode.yaml has syntax errors
        """
        mode_yaml_path = mode_dir / "mode.yaml"

        # Check if mode.yaml exists
        if not mode_yaml_path.exists():
            logger.warning(f"⏭️ Skipped mode: mode.yaml not found in {mode_dir}")
            return None

        # Validate additive fields without resolving labels or changing baseline values.
        try:
            mode = yaml.safe_load(_bundle_path(mode_dir, "mode.yaml").read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ModeValidationError("invalid bundle YAML") from exc
        if not isinstance(mode, dict):
            raise ModeValidationError("mode must be a mapping")
        if mode.get("enabled", True) is False:
            return mode  # Disabled bundles do not require their data files.
        try:
            self._validate_fields(mode_dir, mode)
        except ModeValidationError as exc:
            exc.mandatory = mode.get("name") in MANDATORY_MODES
            raise
        files = mode.get("files", {})

        # 1. Load system_prompt.md (required)
        system_prompt_file = files.get("system_prompt")
        if not system_prompt_file:
            logger.error(f"Missing 'files.system_prompt' in {mode_dir}/mode.yaml")
            return None

        system_prompt_path = _bundle_path(mode_dir, system_prompt_file)
        if not system_prompt_path.exists():
            raise FileNotFoundError(f"Missing required file: {system_prompt_path}")

        # Load system_prompt content
        system_prompt_content = system_prompt_path.read_text(encoding="utf-8")

        # Three literal fallbacks explicitly preserve old bundles without a loaded locale.
        greeting_header = _marker("loader.greeting_header", "# ПРИВЕТСТВИЕ", system_prompt_content)  # noqa: i18n — baseline legacy marker fallback, required for backward compat
        greeting_instruction = _marker("loader.greeting_instruction", "Используйте это приветствие", system_prompt_content)  # noqa: i18n — baseline legacy marker fallback, required for backward compat
        role_header = _marker("loader.role_header", "# РОЛЬ И ПОВЕДЕНИЕ", system_prompt_content)  # noqa: i18n — baseline legacy marker fallback, required for backward compat

        # Step 1: Split by "---" separator (first occurrence only)
        parts = system_prompt_content.split("---", 1)

        # Step 2: Check if greeting section exists
        if len(parts) >= 2 and greeting_header in parts[0]:
            greeting_section = parts[0]
            system_prompt_section = parts[1]

            # Step 3: Extract greeting text (between header and instructions)
            lines = greeting_section.split("\n")
            greeting_lines = []
            found_header = False

            for line in lines:
                # Skip until we find the header
                if greeting_header in line:
                    found_header = True
                    continue

                # After header, collect non-empty lines
                if found_header and line.strip():
                    # Stop at instruction line (Platform SaaS adds this)
                    if greeting_instruction in line:
                        break
                    greeting_lines.append(line.strip())

            # Step 4: Store greeting if found (preserve newlines between non-empty lines)
            greeting = (
                "\n".join(line for line in greeting_lines if line.strip()).strip()
                if greeting_lines
                else None
            )

            if greeting:
                mode["greeting"] = greeting

                # Step 5: Extract system_prompt (after ---, skip to # РОЛЬ И ПОВЕДЕНИЕ)
                system_prompt_cleaned = system_prompt_section.strip()

                # Check if "# РОЛЬ И ПОВЕДЕНИЕ" header exists
                if role_header in system_prompt_cleaned:
                    # Split by header and take everything after it
                    role_parts = system_prompt_cleaned.split(role_header, 1)
                    if len(role_parts) == 2:
                        mode["system_prompt"] = role_parts[1].strip()
                    else:
                        # Fallback: use full content after ---
                        mode["system_prompt"] = system_prompt_cleaned
                else:
                    # No "# РОЛЬ И ПОВЕДЕНИЕ" header → use full content after ---
                    mode["system_prompt"] = system_prompt_cleaned
                    logger.warning(
                        f"Greeting found but no role header in {system_prompt_path}. "
                        "Using content after '---' as system_prompt."
                    )
            else:
                # Empty greeting → ignore, use full content
                logger.debug(
                    f"Empty greeting section found in {system_prompt_path}, ignoring."
                )
                mode["system_prompt"] = system_prompt_content.strip()
        else:
            # No greeting section → use full content (backward compatibility)
            mode["system_prompt"] = system_prompt_content.strip()

        # 2. Load faq.md (required)
        faq_file = files.get("faq")
        if not faq_file:
            logger.error(f"Missing 'files.faq' in {mode_dir}/mode.yaml")
            return None

        faq_path = _bundle_path(mode_dir, faq_file)
        if not faq_path.exists():
            raise FileNotFoundError(f"Missing required file: {faq_path}")

        # ВАЖНО: Не загружаем содержимое faq.md, только путь
        # handlers.py и rag_chains.py используют faq_file для rebuild_index
        mode["faq_file"] = str(faq_path.absolute())

        # 3. Load examples.yaml (optional)
        examples_file = files.get("examples")
        if examples_file:
            examples_path = _bundle_path(mode_dir, examples_file)
            if examples_path.exists():
                try:
                    examples_content = yaml.safe_load(
                        examples_path.read_text(encoding="utf-8")
                    )
                    mode["few_shot_examples"] = examples_content
                    logger.debug(f"Loaded examples.yaml for mode {mode.get('name')}")
                except yaml.YAMLError as e:
                    logger.warning(
                        f"Invalid YAML in {examples_path}: {e}, skipping examples"
                    )
            else:
                logger.info(f"No examples.yaml for mode {mode.get('name')}, skipping")

        return mode

    @staticmethod
    def _validate_fields(mode_dir: Path, mode: dict) -> None:
        for field in ("name", "display_name", "description"):
            if field in mode and not isinstance(mode[field], str):
                raise ModeValidationError(f"{field} must be a string")
        if "enabled" in mode and type(mode["enabled"]) is not bool:
            raise ModeValidationError("enabled must be a bool")
        if "timeout_seconds" in mode and (
            type(mode["timeout_seconds"]) not in (int, float)
            or mode["timeout_seconds"] < 0
        ):
            raise ModeValidationError("timeout_seconds must be nonnegative")
        files = mode.get("files")
        if not isinstance(files, dict) or not files.get("system_prompt") or not files.get("faq"):
            raise ModeValidationError("files.system_prompt and files.faq are required")
        for key in ("system_prompt", "faq", "examples"):
            if key in files:
                _bundle_path(mode_dir, files[key])
        if "source_titles" in mode:
            titles = mode["source_titles"]
            if not isinstance(titles, dict):
                raise ModeValidationError("source_titles must be a mapping")
            for source, title in titles.items():
                _bundle_path(mode_dir, source)
                if not isinstance(title, str):
                    raise ModeValidationError("source title must be a string")
        if "diagnostics_file" in mode:
            target = _bundle_path(mode_dir, mode["diagnostics_file"])
            if not target.is_file():
                raise ModeValidationError("diagnostics_file must exist")
        if "plans_directory" in mode:
            name = mode["plans_directory"]
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]+", name):
                raise ModeValidationError("plans_directory must be a lowercase single component")
            if not _bundle_path(mode_dir, name).is_dir():
                raise ModeValidationError("plans_directory must exist")

    def get_mode(self, mode_name: str) -> Optional[Dict[str, Any]]:
        """Get mode configuration by name.

        Args:
            mode_name: Name of the mode to retrieve

        Returns:
            Mode configuration dictionary or None if not found

        Example:
            >>> loader = ModeLoader(Path("config/modes"))
            >>> mode = loader.get_mode("it_support")
            >>> print(mode["display_name"])
            '🛠️ IT Support'
        """
        modes = self.load_all_modes()
        return modes.get(mode_name)
