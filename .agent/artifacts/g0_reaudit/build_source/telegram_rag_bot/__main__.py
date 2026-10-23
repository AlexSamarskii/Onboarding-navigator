"""
CLI entry point for telegram-rag-bot.

Commands:
    telegram-bot init <name>     - Create new bot project
    telegram-bot run             - Run bot from current directory
    telegram-bot rebuild <mode>  - Rebuild FAQ index for mode
    telegram-bot version         - Show version
"""

import sys
import asyncio
import argparse
import shutil
from pathlib import Path
from telegram_rag_bot import __version__


def cmd_init(name: str) -> None:
    """
    Create new bot project from template.

    Creates a new directory with project structure:
    - config/config.yaml
    - faqs/it_support_faq.md
    - .env.example
    - README.md
    - .gitignore

    Args:
        name: Project name (directory will be created)

    Raises:
        SystemExit: If directory already exists or creation fails

    Example:
        >>> cmd_init("my-faq-bot")
        ✅ Created project: my-faq-bot
    """
    project_dir = Path(name)

    if project_dir.exists():
        print(f"❌ Directory {name} already exists")
        sys.exit(1)

    try:
        # Create project structure
        project_dir.mkdir(parents=True)
        (project_dir / "config").mkdir()
        (project_dir / "faqs").mkdir()
        (project_dir / ".faiss_indices").mkdir()  # For FAISS storage

        # Copy templates
        templates_dir = Path(__file__).parent / "templates"

        shutil.copy(
            templates_dir / "config.yaml.template",
            project_dir / "config" / "config.yaml",
        )
        shutil.copy(templates_dir / ".env.example", project_dir / ".env.example")
        shutil.copy(
            templates_dir / "faq_example.md", project_dir / "faqs" / "it_support_faq.md"
        )

        # Create .gitignore
        gitignore_content = """__pycache__/
*.py[cod]
*.so
.Python
.env
.venv
venv/
.faiss_indices/
*.log
.DS_Store
"""
        (project_dir / ".gitignore").write_text(gitignore_content)

        # Create README for new project
        readme = f"""# {name}

Telegram FAQ bot powered by telegram-rag-bot.

## Quick Start

1. Configure environment:
   ```
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. Run bot:
   ```
   telegram-bot run
   ```

3. Commands:
   - `/start` - Show help
   - `/mode <mode>` - Switch FAQ mode
   - `/reload_faq <mode>` - Rebuild FAQ index (admin only)

## Documentation

See [telegram-rag-bot documentation](https://github.com/MikhailMalorod/telegram-bot-universal)
"""
        (project_dir / "README.md").write_text(readme)

        print(f"✅ Created project: {name}")
        print("\n📁 Project structure:")
        print(f"  {name}/")
        print("  ├── config/config.yaml")
        print("  ├── faqs/it_support_faq.md")
        print("  ├── .env.example")
        print("  ├── .gitignore")
        print("  └── README.md")
        print("\n🚀 Next steps:")
        print(f"  cd {name}")
        print("  cp .env.example .env")
        print("  # Edit .env with your API keys:")
        print("  #   TELEGRAM_TOKEN=your_token")
        print("  #   GIGACHAT_KEY=your_key")
        print("  #   YANDEX_API_KEY=your_key")
        print("  telegram-bot run")

    except Exception as e:
        print(f"❌ Error creating project: {e}")
        # Cleanup on failure
        if project_dir.exists():
            shutil.rmtree(project_dir)
        sys.exit(1)


def cmd_run() -> None:
    """
    Run bot from current directory.

    Loads config from config/config.yaml and starts the Telegram bot.
    Must be run from a project directory created with 'telegram-bot init'.

    Raises:
        SystemExit: If config/config.yaml not found

    Example:
        >>> cmd_run()
        Starting Telegram bot...
    """
    # Check if config exists
    if not Path("config/config.yaml").exists():
        print("❌ config/config.yaml not found")
        print("💡 Make sure you're in a project directory")
        print("Run 'telegram-bot init <name>' to create a new project")
        sys.exit(1)

    from telegram_rag_bot.main import main

    asyncio.run(main())


async def _rebuild_index_async(mode: str) -> None:
    """
    Internal async function to rebuild index.

    Args:
        mode: Mode name to rebuild index for

    Raises:
        FileNotFoundError: If config or FAQ file not found
        ValueError: If mode not found or validation fails
        RuntimeError: If rebuild fails
    """
    from telegram_rag_bot.config_loader import ConfigLoader
    from telegram_rag_bot.langchain_adapter.rag_chains import RAGChainFactory
    from orchestrator import Router
    from orchestrator.langchain import MultiLLMOrchestrator

    # Load config
    config = ConfigLoader.load_config("config/config.yaml")

    # Validate mode
    if mode not in config["modes"]:
        available = ", ".join(config["modes"].keys())
        raise ValueError(f"Unknown mode: {mode}. Available modes: {available}")

    # Get FAQ file
    faq_file = config["modes"][mode]["faq_file"]
    if not Path(faq_file).exists():
        raise FileNotFoundError(f"FAQ file not found: {faq_file}")

    # Create router and LLM
    router = Router(strategy="best-available")

    # Add providers from config
    for provider_cfg in config["orchestrator"]["providers"]:
        if not provider_cfg.get("enabled", True):
            continue

        from orchestrator.providers import (
            GigaChatProvider,
            YandexGPTProvider,
            ProviderConfig,
        )

        if provider_cfg["type"] == "GigaChatProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            p_config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                model=provider_cfg["config"]["model"],
                scope=provider_cfg["config"]["scope"],
                verify_ssl=verify_ssl,
            )
            router.add_provider(GigaChatProvider(p_config))
        elif provider_cfg["type"] == "YandexGPTProvider":
            # Normalize verify_ssl: None → True (secure by default), backward compatible
            raw_verify_ssl = provider_cfg["config"].get("verify_ssl_certs", True)
            verify_ssl = True if raw_verify_ssl is None else raw_verify_ssl
            p_config = ProviderConfig(
                name=provider_cfg["name"],
                api_key=provider_cfg["config"]["api_key"],
                folder_id=provider_cfg["config"]["folder_id"],
                model=provider_cfg["config"]["model"],
                verify_ssl=verify_ssl,
            )
            router.add_provider(YandexGPTProvider(p_config))

    llm = MultiLLMOrchestrator(router=router)

    # Create factory and rebuild
    factory = RAGChainFactory(
        llm=llm,
        embeddings_config=config["embeddings"],
        vectorstore_config=config["vectorstore"],
        chunk_config=config["langchain"],
        modes=config["modes"],
    )

    await factory.rebuild_index(mode, faq_file)


def cmd_rebuild(mode: str) -> None:
    """
    Rebuild FAQ index for mode.

    Must be run from a project directory. Loads config, validates mode,
    and rebuilds the vector index for the specified FAQ mode.

    Args:
        mode: Mode name (e.g., "it_support")

    Raises:
        SystemExit: If config not found, mode invalid, or rebuild fails

    Example:
        >>> cmd_rebuild("it_support")
        🔨 Rebuilding index for mode: it_support
        ✅ Index rebuilt for mode: it_support
    """
    print(f"🔨 Rebuilding index for mode: {mode}")

    # Check if config exists
    if not Path("config/config.yaml").exists():
        print("❌ config/config.yaml not found")
        print("💡 Run this command from project directory")
        sys.exit(1)

    try:
        asyncio.run(_rebuild_index_async(mode))
        print(f"✅ Index rebuilt for mode: {mode}")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error rebuilding index: {e}")
        sys.exit(1)


def cmd_version() -> None:
    """
    Show version and project information.

    Displays the current version of telegram-rag-bot and GitHub URL.

    Example:
        >>> cmd_version()
        telegram-rag-bot v0.7.0
        https://github.com/MikhailMalorod/telegram-bot-universal
    """
    print(f"telegram-rag-bot v{__version__}")
    print("https://github.com/MikhailMalorod/telegram-bot-universal")


def main() -> None:
    """
    Main CLI entry point.

    Parses command-line arguments and dispatches to appropriate command handler.
    Supports 4 commands: init, run, rebuild, version.

    Example:
        >>> main()
        # Called from command line: telegram-bot init my-bot
    """
    parser = argparse.ArgumentParser(
        prog="telegram-bot",
        description="Telegram RAG Bot - Production-ready FAQ bot with Russian LLMs",
        epilog="For more information: https://github.com/MikhailMalorod/telegram-bot-universal",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser(
        "init", help="Create new bot project from template"
    )
    init_parser.add_argument("name", help="Project name")

    # run command
    subparsers.add_parser("run", help="Run bot from current directory")

    # rebuild command
    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild FAQ index for mode")
    rebuild_parser.add_argument("mode", help="Mode name (e.g., it_support)")

    # version command
    subparsers.add_parser("version", help="Show version and project information")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args.name)
    elif args.command == "run":
        cmd_run()
    elif args.command == "rebuild":
        cmd_rebuild(args.mode)
    elif args.command == "version":
        cmd_version()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
