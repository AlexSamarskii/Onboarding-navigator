"""
Load and validate bot configuration from YAML.

Supports environment variable substitution via ${VAR_NAME}.
"""

import os
import json
import math
from urllib.parse import urlsplit
from pathlib import PureWindowsPath
import re
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, TypedDict
from telegram_rag_bot.mode_loader import ModeLoader

logger = logging.getLogger(__name__)


class ProviderConfig(TypedDict, total=False):
    """
    Unified provider configuration for all LLM providers.

    Used in orchestrator.providers section of config.yaml.
    Different providers use different subsets of fields:
    - GigaChat: api_key, model, scope, timeout_seconds
    - YandexGPT: api_key, folder_id, model, timeout_seconds

    Example:
        >>> provider_cfg: ProviderConfig = {
        ...     "api_key": "your_api_key",
        ...     "model": "GigaChat-Pro",
        ...     "scope": "GIGACHAT_API_PERS"
        ... }
    """

    api_key: str
    folder_id: str  # YandexGPT only
    model: str
    scope: str  # GigaChat only
    timeout_seconds: int
    max_tokens: int


class ConfigLoader:
    """
    YAML configuration loader with environment variable substitution.

    Supports ${VAR_NAME} syntax for env vars. Validates required sections.
    """

    # Required environment variables (must be set)
    REQUIRED_ENV_VARS = [
        "TELEGRAM_TOKEN",
        "GIGACHAT_KEY",
        "YANDEX_API_KEY",
        "YANDEX_FOLDER_ID",
    ]

    @staticmethod
    def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
        """
        Load YAML configuration with environment variable substitution.

        Args:
            config_path: Path to config YAML file (default: "config.yaml")

        Returns:
            Dictionary with parsed configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If required env var is missing or required section is missing

        Example:
            >>> config = ConfigLoader.load_config("config.yaml")
            >>> config["telegram"]["token"]
            "123456:ABC-DEF..."
        """
        # Check if config file exists
        if not Path(config_path).exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        logger.info(f"Loading config from: {config_path}")

        # Load YAML
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if config is None:
            raise ValueError("Config file is empty or invalid YAML")

        # Substitute environment variables
        product = isinstance(config, dict) and not ("telegram" in config or "orchestrator" in config)
        config = ConfigLoader._substitute_env_vars(config, preserve_missing=product)
        if product and isinstance(config.get("ADMIN_IDS"), str):
            config["ADMIN_IDS"] = ConfigLoader._parse_admin_ids(config["ADMIN_IDS"])

        # Validate required sections
        ConfigLoader._validate_config(config)

        # Загрузить modes через ModeLoader
        modes_dir_str = config.get("modes", {}).get("directory")
        if not modes_dir_str:
            raise ValueError(
                "config.yaml must have 'modes.directory' field. "
                "Old format (modes in config.yaml) is not supported."
            )

        # Разрешить путь относительно config.yaml
        config_file = Path(config_path)
        config_dir = (
            config_file.parent
        )  # Директория, где лежит config.yaml (например, config/)

        # Если путь относительный — добавить config_dir
        if not Path(modes_dir_str).is_absolute():
            modes_dir = (config_dir / modes_dir_str).resolve()
        else:
            modes_dir = Path(modes_dir_str).resolve()

        if not modes_dir.exists():
            raise FileNotFoundError(
                f"Modes directory not found: {modes_dir}. "
                f"Expected path: {modes_dir.absolute()}"
            )

        # Загрузить modes через ModeLoader (уже импортирован в начале файла)
        mode_loader = ModeLoader(modes_dir)
        config["modes_directory"] = str(modes_dir)
        config["modes"] = mode_loader.load_all_modes()

        logger.info(f"✅ Loaded {len(config['modes'])} mode(s) from {modes_dir}")

        return config

    @staticmethod
    def _substitute_env_vars(obj: Any, preserve_missing: bool = False) -> Any:
        """
        Recursively substitute environment variables in config.

        Syntax: ${VAR_NAME} → os.getenv("VAR_NAME")

        Args:
            obj: Config object (dict, list, str, or primitive)

        Returns:
            Object with substituted values

        Raises:
            ValueError: If required env var is missing
        """
        if isinstance(obj, dict):
            # Recursively process dict values
            return {k: ConfigLoader._substitute_env_vars(v, preserve_missing) for k, v in obj.items()}

        elif isinstance(obj, list):
            # Recursively process list items
            return [ConfigLoader._substitute_env_vars(item, preserve_missing) for item in obj]

        elif isinstance(obj, str):
            # Find all ${VAR_NAME} patterns
            pattern = r"\$\{([^}]+)\}"

            def replace_var(match):
                var_name = match.group(1)

                # Check if required var is missing
                if var_name in ConfigLoader.REQUIRED_ENV_VARS:
                    if var_name not in os.environ:
                        raise ValueError(
                            f"Missing required environment variable: {var_name}"
                        )
                    return os.environ[var_name]

                # Optional var (e.g., REDIS_URL)
                value = os.getenv(var_name)
                if value is not None:
                    return value
                else:
                    # Optional var not set → return empty string
                    # This handles both cases: entire string is placeholder or part of larger string
                    return match.group(0) if preserve_missing else ""

            # Replace all occurrences
            result = re.sub(pattern, replace_var, obj)
            return result

        else:
            # Primitive type (int, bool, etc.) → return as is
            return obj

    @staticmethod
    def _validate_config(config: Dict[str, Any]) -> None:
        """
        Validate that required config sections exist.

        Args:
            config: Parsed configuration dictionary

        Raises:
            ValueError: If required section is missing
        """
        if not isinstance(config, dict):
            raise ValueError("config must be a mapping")
        if "telegram" not in config and "orchestrator" not in config:
            ConfigLoader._validate_product(config)
            return
        # Legacy requires both sections, preserving platform validation below.
        required_sections = ["telegram", "orchestrator"]

        for section in required_sections:
            if section not in config:
                raise ValueError(f"config.yaml missing required section: {section}")

        # Проверить modes.directory (новый формат)
        if "modes" not in config or "directory" not in config.get("modes", {}):
            raise ValueError(
                "config.yaml must have 'modes.directory' field. "
                "Old format (modes in config.yaml) is not supported."
            )

        # Валидация platform секции (опциональна, но если есть callback_url → tenant_id обязателен)
        if "platform" in config:
            platform = config["platform"]
            callback_url = platform.get("callback_url")
            tenant_id = platform.get("tenant_id")

            # Если callback_url указан → tenant_id обязателен
            if callback_url and not tenant_id:
                raise ValueError(
                    "platform.tenant_id is required when platform.callback_url is set"
                )

            # Если callback_url указан → валидировать формат URL
            if callback_url:
                if not callback_url.startswith(("http://", "https://")):
                    raise ValueError(
                        f"platform.callback_url must start with http:// or https://, got: {callback_url}"
                    )

        logger.info("✅ Config validation passed")

    @staticmethod
    def _parse_admin_ids(value: str) -> Any:
        """Product environment IDs accept JSON integer arrays or comma-separated ints.

        An unset full placeholder is preserved for offline config validation;
        an explicitly empty env value means no administrators (fail closed).
        """
        if re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value):
            return value
        if not value.strip():
            return []
        try:
            if value.strip().startswith("["):
                result = json.loads(value)
            else:
                parts = value.split(",")
                if any(not re.fullmatch(r"[0-9]+", part.strip()) for part in parts):
                    raise ValueError
                result = [int(part) for part in parts]
        except (ValueError, TypeError) as exc:
            raise ValueError("ADMIN_IDS must be an integer list or placeholder") from exc
        if not isinstance(result, list) or any(type(item) is not int for item in result):
            raise ValueError("ADMIN_IDS must contain integers")
        return result

    @staticmethod
    def _validate_product(config: dict) -> None:
        def section(name: str) -> dict:
            value = config.get(name)
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be a mapping")
            return value

        directory = section("modes").get("directory")
        if (not isinstance(directory, str) or not directory
                or Path(directory).is_absolute() or PureWindowsPath(directory).drive
                or "\\" in directory or ".." in Path(directory).parts):
            raise ValueError("modes.directory must be a relative path")
        score = section("rag").get("score_threshold")
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("rag.score_threshold must be a finite number in [0,1]")
        integrations = section("integrations")
        ticketing = integrations.get("ticketing")
        if not isinstance(ticketing, dict):
            raise ValueError("integrations.ticketing must be a mapping")
        url = ticketing.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("ticketing.url must be an HTTP URL or placeholder")
        placeholder = re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", url)
        if not placeholder:
            try:
                parsed = urlsplit(url)
                valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                         and not parsed.username and not parsed.password and not parsed.fragment
                         and not any(char.isspace() for char in url))
                parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("ticketing.url must be an HTTP URL without credentials")
        if "hr_chat_id" in ticketing and not isinstance(ticketing["hr_chat_id"], str):
            raise ValueError("ticketing.hr_chat_id must be a string")
        locale = section("i18n").get("default_locale")
        if not isinstance(locale, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", locale):
            raise ValueError("i18n.default_locale must be a locale string")
        admins = config.get("ADMIN_IDS")
        if isinstance(admins, str):
            admins = ConfigLoader._parse_admin_ids(admins)
        if not (isinstance(admins, str) or isinstance(admins, list)
                and all(type(item) is int for item in admins)):
            raise ValueError("ADMIN_IDS must be an integer list or placeholder")
        ttl = section("session").get("ttl_seconds")
        if type(ttl) is not int or ttl < 0:
            raise ValueError("session.ttl_seconds must be a nonnegative integer")
        if type(section("retrieval").get("async_mode")) is not bool:
            raise ValueError("retrieval.async_mode must be a boolean")
        providers = section("llm").get("providers")
        if not isinstance(providers, list) or not providers or any(
                not isinstance(item, str) or not item.strip() for item in providers):
            raise ValueError("llm.providers must be an ordered nonempty string list")


def reload_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """
    Reload configuration (for hot reload).

    Alias for ConfigLoader.load_config().
    Used in handlers when FAQ is reloaded.

    Args:
        config_path: Path to config YAML file

    Returns:
        Dictionary with parsed configuration (modes reloaded from bundles)

    Example:
        >>> config = reload_config()
        >>> print(config["modes"]["it_support"]["display_name"])
        '🛠️ IT Support'
    """
    logger.info("Reloading configuration...")
    return ConfigLoader.load_config(config_path)
