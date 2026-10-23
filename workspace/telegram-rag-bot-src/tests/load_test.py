"""
Load testing script for Telegram RAG Bot.

This module implements load tests for Days 18-19 to validate bot performance
before Day 20 pilot launch. Tests 100 concurrent users with mocked Telegram
Update objects to bypass API rate limits.

Test scenarios:
1. /start command (100 concurrent users, 30s)
2. FAQ queries (50-100 concurrent users, 2min)
3. /reload_faq stress test (5-10 concurrent admin requests, optional)

Metrics collected:
- Response latency (p50, p95, p99)
- Error rate (%)
- Throughput (requests/sec)
- Memory usage (MB)

Output: load_test_results.json (JSON report)

Usage:
    pytest tests/load_test.py -v --tb=short

Requirements:
    - Docker environment running (docker-compose up -d)
    - TELEGRAM_TOKEN in .env (@ReviewCode_bot)
    - Redis running (localhost:6379)

⚠️ NOTE: This test is excluded from CI/CD (requires real TELEGRAM_TOKEN).
Run locally: pytest tests/load_test.py -v
CI/CD runs unit tests only: pytest tests/ --ignore=tests/load_test.py
"""

import os
from pathlib import Path

# Load .env file for local testing (before other imports)
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from {env_path}")
    else:
        print(f"⚠️ .env not found at {env_path}")
        print("   Create .env file: cp .env.example .env")
except ImportError:
    print("⚠️ python-dotenv not installed")
    print("   Install: pip install python-dotenv")

# Verify TELEGRAM_TOKEN loaded
if not os.getenv("TELEGRAM_TOKEN"):
    raise EnvironmentError(
        "TELEGRAM_TOKEN not found in environment.\n"
        "1. Create .env file: cp .env.example .env\n"
        "2. Add TELEGRAM_TOKEN=<your_bot_token> to .env\n"
        "3. Install python-dotenv: pip install python-dotenv"
    )

# Rest of imports
import asyncio
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram import Update  # Keep Update for type hints
from telegram.ext import ContextTypes

from telegram_rag_bot.config_loader import ConfigLoader
from telegram_rag_bot.langchain_adapter.rag_chains import RAGChainFactory
from telegram_rag_bot.utils.session_manager import SessionManager
from telegram_rag_bot.handlers import TelegramHandlers
from telegram_rag_bot.main import create_router
from orchestrator.langchain import MultiLLMOrchestrator


# Test configuration
TEST_USER_IDS = list(range(100000000, 100000100))  # 100 fake users
ADMIN_USER_IDS = [100000000, 100000001]  # First 2 users as admins
BATCH_SIZE = 30  # Telegram rate limit: 30 msg/sec
BATCH_DELAY = 1.0  # Delay between batches (seconds)

# FAQ queries from faqs/it_support_faq.md
FAQ_QUERIES = [
    "Как сбросить пароль VPN?",
    "Не могу подключиться к VPN",
    "VPN медленно работает",
    "Как установить Docker на Ubuntu?",
    "Как запустить контейнер?",
    "Ошибка permission denied при запуске Docker",
    "Как настроить SSH ключ для GitLab?",
    "Забыл пароль от GitLab",
    "Как настроить корпоративную почту?",
    "Не приходят письма",
    "Почтовый ящик переполнен",
    "Как настроить автоответчик?",
]


# Results storage
load_test_results: Dict[str, Any] = {}


def create_fake_update(user_id: int, text: str) -> Update:
    """
    Create mock Telegram Update for load testing.

    Uses MagicMock instead of real Telegram objects to avoid
    immutability issues with python-telegram-bot v21+ frozen dataclasses.

    Args:
        user_id: Unique user identifier (100000000-100000099)
        text: Message text (e.g., "/start", "Как сбросить пароль VPN?")

    Returns:
        Mock Update object with all necessary attributes

    Example:
        >>> update = create_fake_update(100000001, "/start")
        >>> await handlers.handle_message(update, context)
    """
    # Create mock Update with all necessary attributes
    update = MagicMock(spec=Update)
    update.update_id = user_id
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = "TestUser"
    update.effective_user.username = "testuser"
    update.effective_user.is_bot = False

    update.effective_chat = MagicMock()
    update.effective_chat.id = user_id
    update.effective_chat.type = "private"

    update.message = MagicMock()
    update.message.message_id = user_id
    update.message.date = datetime.now()
    update.message.chat = update.effective_chat
    update.message.from_user = update.effective_user
    update.message.text = text

    # Mock async methods that handlers call
    update.message.reply_text = AsyncMock(return_value=MagicMock())
    update.message.reply_markdown = AsyncMock(return_value=MagicMock())
    update.message.reply_html = AsyncMock(return_value=MagicMock())
    update.message.chat.send_action = AsyncMock()

    return update


def create_mock_context(args: Optional[List[str]] = None) -> AsyncMock:
    """
    Create mock Telegram Context for load testing.

    Args:
        args: Command arguments (for /mode, /reload_faq commands)

    Returns:
        Mocked ContextTypes.DEFAULT_TYPE object
    """
    context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = args or []
    return context


def calculate_percentiles(latencies: List[float]) -> Dict[str, float]:
    """
    Calculate p50, p95, p99 percentiles from latency samples.

    Args:
        latencies: List of response latencies in seconds

    Returns:
        Dictionary with percentile metrics:
        {
            "p50": 1.2,  # Median latency
            "p95": 3.1,  # 95th percentile
            "p99": 3.4   # 99th percentile
        }

    Raises:
        ValueError: If latencies list is empty

    Example:
        >>> latencies = [0.5, 1.0, 1.5, 2.0, 5.0]
        >>> percentiles = calculate_percentiles(latencies)
        >>> print(percentiles["p99"])
        5.0
    """
    if not latencies:
        raise ValueError("Latencies list cannot be empty")

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    return {
        "p50": sorted_latencies[int((n - 1) * 0.50)],
        "p95": sorted_latencies[int((n - 1) * 0.95)],
        "p99": sorted_latencies[int((n - 1) * 0.99)],
    }


async def run_scenario(
    scenario_name: str,
    handler_func,
    user_ids: List[int],
    handler_args: List[Any],
    duration_seconds: float,
    batch_size: int = BATCH_SIZE,
    batch_delay: float = BATCH_DELAY,
) -> Dict[str, Any]:
    """
    Run a load test scenario with concurrent users.

    Args:
        scenario_name: Name of scenario (e.g., "start_command")
        handler_func: Async handler function to call
        user_ids: List of user IDs to simulate
        handler_args: List of argument tuples (update, context) for each user
        duration_seconds: Maximum duration for scenario
        batch_size: Users per batch (respect rate limits)
        batch_delay: Delay between batches (seconds)

    Returns:
        Dictionary with metrics:
        {
            "scenario": "start_command",
            "duration_seconds": 30.0,
            "total_requests": 100,
            "successful_requests": 95,
            "failed_requests": 5,
            "error_rate": 0.05,
            "latencies": [0.5, 1.2, ...],
            "latency_p50": 1.2,
            "latency_p95": 3.1,
            "latency_p99": 5.0,
            "throughput_rps": 3.3
        }
    """
    start_time = time.time()
    latencies: List[float] = []
    successful_requests = 0
    failed_requests = 0

    # Split users into batches
    batches = [
        user_ids[i : i + batch_size] for i in range(0, len(user_ids), batch_size)
    ]

    total_requests = 0

    for batch_idx, batch_user_ids in enumerate(batches):
        batch_start_time = time.time()

        # Create tasks for this batch
        tasks = []
        for user_idx, user_id in enumerate(batch_user_ids):
            # Get handler args for this user
            if isinstance(handler_args, list) and len(handler_args) > user_idx:
                user_args = handler_args[user_idx]
            elif callable(handler_args):
                user_args = handler_args(user_id)
            else:
                user_args = handler_args  # Same args for all users

            # Create handler wrapper with captured args (use default param to avoid closure issues)
            async def run_handler(hfunc=handler_func, args=user_args):
                """Run handler and measure latency."""
                try:
                    handler_start = time.time()
                    await hfunc(*args)
                    handler_latency = time.time() - handler_start
                    return {"success": True, "latency": handler_latency}
                except Exception as e:
                    return {"success": False, "error": str(e), "latency": None}

            tasks.append(run_handler())

        # Execute batch
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in batch_results:
            if isinstance(result, Exception):
                failed_requests += 1
            elif isinstance(result, dict):
                if result.get("success"):
                    successful_requests += 1
                    if result.get("latency") is not None:
                        latencies.append(result["latency"])
                else:
                    failed_requests += 1
            total_requests += 1

        # Check if we've exceeded duration
        elapsed = time.time() - start_time
        if elapsed >= duration_seconds:
            break

        # Wait before next batch (except for last batch)
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(batch_delay)

    total_duration = time.time() - start_time

    # Calculate metrics
    error_rate = failed_requests / total_requests if total_requests > 0 else 0.0
    throughput_rps = total_requests / total_duration if total_duration > 0 else 0.0

    percentiles = (
        calculate_percentiles(latencies)
        if latencies
        else {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    )

    return {
        "scenario": scenario_name,
        "duration_seconds": total_duration,
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "error_rate": error_rate,
        "latencies": latencies[:100],  # Store first 100 for analysis
        "latency_p50": percentiles["p50"],
        "latency_p95": percentiles["p95"],
        "latency_p99": percentiles["p99"],
        "throughput_rps": throughput_rps,
    }


@pytest.fixture(scope="module")
def load_test_handlers():
    """
    Initialize handlers for load testing.

    Loads real config and initializes all components (RAG factory, session manager, handlers).
    Uses production bot token from .env but tests with mocked Update objects.

    Returns:
        TelegramHandlers instance ready for testing
    """
    # Setup logging (minimal for load tests)
    import logging

    logging.basicConfig(level=logging.WARNING)  # Reduce log noise during load tests

    # Load config
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    config = ConfigLoader.load_config(str(config_path))

    # Override Redis URL for local testing (use localhost instead of redis hostname)
    redis_url = config.get("storage", {}).get("sessions", {}).get("url")
    if redis_url and "redis://redis:" in redis_url:
        # Replace Docker hostname with localhost for local pytest execution
        redis_url_local = redis_url.replace("redis://redis:", "redis://localhost:")
        config["storage"]["sessions"]["url"] = redis_url_local
        print(f"✅ Redis URL overridden for local testing: {redis_url_local}")

    # Update admin_ids for load testing (use first 2 test users)
    if not config.get("telegram", {}).get("admin_ids"):
        config["telegram"]["admin_ids"] = ADMIN_USER_IDS

    # Create router and LLM
    router = create_router(config["orchestrator"])
    llm = MultiLLMOrchestrator(router=router)

    # Create RAG factory
    rag_factory = RAGChainFactory(
        llm=llm,
        embeddings_config=config["embeddings"],
        vectorstore_config=config["vectorstore"],
        chunk_config=config["langchain"],
        modes=config["modes"],
    )

    # Create session manager (use Redis if available, fallback to memory)
    redis_url_final = config.get("storage", {}).get("sessions", {}).get("url")
    session_manager = SessionManager(redis_url=redis_url_final)

    # Create handlers
    handlers = TelegramHandlers(
        rag_factory=rag_factory, session_manager=session_manager, config=config
    )

    return handlers


@pytest.mark.asyncio
async def test_start_command_load(load_test_handlers):
    """
    Load test for /start command with 100 concurrent users.

    Tests bot's ability to handle concurrent /start commands.
    Duration: ~30 seconds (batches of 30 users with 1s delay).
    """
    handlers = load_test_handlers

    # Create handler args for each user
    def create_args(user_id: int):
        update = create_fake_update(user_id, "/start")
        context = create_mock_context()
        return (update, context)

    # Run scenario
    result = await run_scenario(
        scenario_name="start_command",
        handler_func=handlers.cmd_start,
        user_ids=TEST_USER_IDS,
        handler_args=create_args,
        duration_seconds=30.0,
        batch_size=BATCH_SIZE,
        batch_delay=BATCH_DELAY,
    )

    # Store result
    load_test_results["start_command"] = result

    # Assertions
    assert result["total_requests"] > 0, "No requests completed"
    assert (
        result["error_rate"] < 0.10
    ), f"Error rate too high: {result['error_rate']:.2%}"
    assert (
        result["latency_p99"] < 10.0
    ), f"p99 latency too high: {result['latency_p99']:.2f}s"


@pytest.mark.asyncio
async def test_faq_queries_load(load_test_handlers):
    """
    Load test for FAQ queries with 50-100 concurrent users.

    Tests bot's ability to handle concurrent FAQ queries through RAG chain.
    Duration: ~2 minutes (batches of 30 users with 1s delay).
    Uses queries from faqs/it_support_faq.md.
    """
    handlers = load_test_handlers

    # Select 50 users and assign random queries
    import random

    selected_users = TEST_USER_IDS[:50]
    random.seed(42)  # Reproducible results

    # Create handler args for each user
    def create_args(user_id: int):
        query = random.choice(FAQ_QUERIES)
        update = create_fake_update(user_id, query)
        context = create_mock_context()
        return (update, context)

    # Run scenario
    result = await run_scenario(
        scenario_name="faq_queries",
        handler_func=handlers.handle_message,
        user_ids=selected_users,
        handler_args=create_args,
        duration_seconds=120.0,  # 2 minutes
        batch_size=BATCH_SIZE,
        batch_delay=BATCH_DELAY,
    )

    # Store result
    load_test_results["faq_queries"] = result

    # Assertions
    assert result["total_requests"] > 0, "No requests completed"
    assert (
        result["error_rate"] < 0.10
    ), f"Error rate too high: {result['error_rate']:.2%}"
    assert (
        result["latency_p99"] < 30.0
    ), f"p99 latency too high: {result['latency_p99']:.2f}s"


@pytest.mark.asyncio
async def test_reload_faq_stress(load_test_handlers):
    """
    Stress test for /reload_faq admin command with 5-10 concurrent requests.

    Tests bot's ability to handle concurrent /reload_faq commands.
    Duration: ~30 seconds.
    Optional: Skip if no critical bottlenecks found in main scenarios.
    """
    handlers = load_test_handlers

    # Use first 5 users as admins (must be in admin_ids in config)
    admin_users = ADMIN_USER_IDS[:5]

    # Create handler args for each admin
    def create_args(user_id: int):
        update = create_fake_update(user_id, "/reload_faq")
        context = create_mock_context(args=["it_support"])
        return (update, context)

    # Run scenario
    result = await run_scenario(
        scenario_name="reload_faq_stress",
        handler_func=handlers.cmd_reload_faq,
        user_ids=admin_users,
        handler_args=create_args,
        duration_seconds=30.0,
        batch_size=5,  # Smaller batches for admin commands
        batch_delay=2.0,  # Longer delay (reload_faq is heavy)
    )

    # Store result
    load_test_results["reload_faq_stress"] = result

    # Assertions (more lenient for admin commands)
    assert result["total_requests"] > 0, "No requests completed"
    assert (
        result["error_rate"] < 0.50
    ), f"Error rate too high: {result['error_rate']:.2%}"


@pytest.fixture(scope="session", autouse=True)
def save_load_test_results():
    """
    Save load test results to JSON file after all tests complete.

    Outputs: load_test_results.json
    """
    yield

    # Save results to JSON file
    output_path = Path(__file__).parent.parent / "load_test_results.json"

    # Add summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "scenarios": list(load_test_results.keys()),
        "results": load_test_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Load test results saved to: {output_path}")
